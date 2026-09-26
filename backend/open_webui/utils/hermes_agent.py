"""
Hermes Agent integration.

Routes chats for configured model IDs through hermes's /v1/runs API (instead of
/v1/chat/completions) so that:

- tool activity streams into the chat as native <details type="tool_calls">
  blocks (rendered by the existing frontend, no frontend changes needed);
- command approval requests pop the hermes approval dialog in every live tab
  of the user (socket "hermes:approval" call, answered with once / session /
  always / deny) and the choice is posted back to hermes via
  POST /v1/runs/{run_id}/approval; with no tab connected (see utils/presence.py:
  registered socket or the requesting tab, after a short grace for a
  reconnect) the request is pushed to the user's notification webhook.

Configuration (environment variables):

- HERMES_AGENT_MODEL_IDS: comma-separated model IDs handled by this
  integration (default: "hermes-agent").
- HERMES_AGENT_BASE_URL / HERMES_AGENT_API_KEY: optional explicit connection
  override. When unset, the connection is resolved from the existing OpenAI
  connections by model ID.
- HERMES_AGENT_APPROVAL_TIMEOUT: seconds to wait for the user's approval
  decision before auto-denying (default: 240; keep below hermes's
  approvals.gateway_timeout which defaults to 300).
- HERMES_AGENT_RECOVERY_MAX_SECONDS: how long to keep asking hermes for the
  outcome of a run whose event stream dropped (default: 21600 = 6h).
- HERMES_AGENT_HOST_DATA_DIR: where this container's data directory lives on
  the hermes host, so uploaded files can be handed to hermes by path.
  Detected from /proc/self/mountinfo when unset; "off" disables.
"""

import asyncio
import html
import json
import logging
import os
import re
import time
from urllib.parse import urlparse, urlunparse

import aiohttp

from open_webui.env import (
    AIOHTTP_CLIENT_SESSION_SSL,
    DATA_DIR,
    SRC_LOG_LEVELS,
    WEBSOCKET_EVENT_CALLER_TIMEOUT,
)
from open_webui.models.chats import Chats
from open_webui.socket.main import (
    SESSION_POOL,
    USER_POOL,
    get_event_call,
    get_event_emitter,
    sio,
)
from open_webui.tasks import create_task, set_current_task_blocks_completion
from open_webui.utils.chat_image_refs import materialize_openai_image_message_refs
from open_webui.utils.hermes_unread import mark_unread
from open_webui.utils.html_visual_prompt import (
    _FENCED_HTML_BLOCK_RE,
    _fenced_html_artifacts_as_text,
    append_html_visual_fallback,
    design_html_visual_artifact_with_agy,
)
from open_webui.utils.model_identity import parse_selection_id
from open_webui.utils.presence import (
    APPROVAL_WEBHOOK_GRACE_SECONDS,
    schedule_away_webhook,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("MAIN", logging.INFO))


HERMES_AGENT_MODEL_IDS = [
    model_id.strip()
    for model_id in os.environ.get("HERMES_AGENT_MODEL_IDS", "hermes-agent").split(",")
    if model_id.strip()
]

HERMES_AGENT_BASE_URL = os.environ.get("HERMES_AGENT_BASE_URL", "").strip()
HERMES_AGENT_API_KEY = os.environ.get("HERMES_AGENT_API_KEY", "").strip()

try:
    HERMES_AGENT_APPROVAL_TIMEOUT = int(
        os.environ.get("HERMES_AGENT_APPROVAL_TIMEOUT", "240")
    )
except ValueError:
    HERMES_AGENT_APPROVAL_TIMEOUT = 240

try:
    HERMES_AGENT_RECOVERY_MAX_SECONDS = int(
        os.environ.get("HERMES_AGENT_RECOVERY_MAX_SECONDS", str(6 * 3600))
    )
except ValueError:
    HERMES_AGENT_RECOVERY_MAX_SECONDS = 6 * 3600

# Pauses between status polls of a run whose event stream dropped: quick at
# first (a blip), then settling at the slowest step for long runs.
RECOVERY_POLL_DELAYS = (1, 2, 3, 5, 10, 15)

# POST /v1/runs answers 429 while hermes runs its maximum of concurrent runs
# (it sends Retry-After). Wait it out for about a minute before giving up.
START_RETRY_MAX_SECONDS = 60
START_RETRY_MIN_DELAY = 3

# Where runs whose outcome is still owed to a chat are remembered, so a
# restart of this process picks them up again instead of leaving the reply
# half-written with its tools "running" forever.
INFLIGHT_RUNS_FILE = "hermes_inflight_runs.json"

# Answer text arrives one token per event and every event re-sent the whole
# reply, which the page then re-rendered: on a long run that is quadratic.
# Text updates are coalesced to at most one per interval; tool events, the
# final answer and steers still go out at once. 0 turns coalescing off.
try:
    HERMES_AGENT_STREAM_EMIT_INTERVAL = max(
        0.0, float(os.environ.get("HERMES_AGENT_STREAM_EMIT_INTERVAL", "0.15"))
    )
except ValueError:
    HERMES_AGENT_STREAM_EMIT_INTERVAL = 0.15

# "派发方式" (or a typed /reclaude …) is also sent as an explicit field, so a
# hermes with the local fast-dispatch patch starts the runner without a model
# call. Off: hermes gets only the typed prefix and its model launches the run.
HERMES_AGENT_FAST_DISPATCH = os.environ.get(
    "HERMES_AGENT_FAST_DISPATCH", "1"
).strip().lower() not in {"0", "false", "off", "no"}

# aiohttp's default per-line read buffer is 64KB, but a run.completed SSE
# event carrying inlined base64 images (hermes resolves MEDIA:<path> tags,
# up to 5MB per image) arrives as a single multi-MB line.
HERMES_EVENTS_READ_BUFSIZE = 64 * 1024 * 1024

# /v1/runs needs a user turn to start from. Two UI actions do not provide one:
# "continue response" replays a chat whose last message is the assistant's, and
# an attachment-only submit carries no text. Both used to die on a 400 before
# the run started ("Missing 'input' field" / "No user message found in input"),
# so say out loud what the user meant instead.
CONTINUE_RUN_INPUT = (
    "Continue your previous reply from exactly where it stopped. "
    "Do not repeat what you already wrote, and do not restart the task."
)
ATTACHMENT_ONLY_RUN_INPUT = (
    "The attached file(s) are the request; no other text was provided. "
    "Work with them and report what you find."
)

# A completion webhook is read on a phone: no tool transcript, no artifact
# source, and short enough that Telegram/Bark render it in one screen.
WEBHOOK_CONTENT_MAX_CHARS = 1200

# Longest guidance accepted mid-run.
STEER_TEXT_MAX_CHARS = 4000

# Choices hermes accepts on POST /v1/runs/{run_id}/approval, in the order the
# dialog lists them. "session" scopes the grant to the hermes session, which is
# this chat (session_id = chat_id), so it reads as "allow for this chat".
APPROVAL_CHOICES = ("once", "session", "always", "deny")
APPROVAL_EVENT_TYPE = "hermes:approval"
APPROVAL_RESOLVED_EVENT_TYPE = "hermes:approval:resolved"
APPROVAL_TITLE = "Hermes 请求执行命令"
# Pause between rounds of asking the browser: no tab connected, or every
# connected tab let the socket call time out (none of them shows this chat).
APPROVAL_RETRY_DELAY_SECONDS = 2


def _approval_choices(event) -> list[str]:
    """The choices to offer for one approval request: what hermes listed,
    in dialog order, always including "once" and "deny"."""
    offered = event.get("choices") if isinstance(event, dict) else None
    if not isinstance(offered, (list, tuple, set)):
        offered = []
    offered = {str(choice).strip().lower() for choice in offered}
    choices = [choice for choice in APPROVAL_CHOICES if choice in offered]
    if "once" not in choices:
        choices.insert(0, "once")
    if "deny" not in choices:
        choices.append("deny")
    return choices


def _normalize_approval_choice(result, choices) -> str:
    """Map what the browser answered to a choice hermes accepts.

    The dialog answers with the choice string; a bare boolean (the generic
    confirmation dialog of an older frontend) means once/deny. Anything else
    denies: never widen a grant on malformed input."""
    if isinstance(result, dict):
        result = result.get("choice")
    if isinstance(result, bool):
        return "once" if result else "deny"
    if isinstance(result, str):
        value = result.strip().lower()
        if value in choices:
            return value
    return "deny"


def _approval_target_sids(
    user_id: str, preferred_sid=None, *, session_pool=None, user_pool=None
) -> list[str]:
    """Socket sessions to show an approval dialog in: the tab that sent the
    message first, then the user's other live tabs, newest first.

    The original tab is gone after a reload or a navigation away and back;
    asking only it would let every approval time out into a deny."""
    session_pool = SESSION_POOL if session_pool is None else session_pool
    user_pool = USER_POOL if user_pool is None else user_pool
    sids: list[str] = []
    if preferred_sid and preferred_sid in session_pool:
        sids.append(preferred_sid)
    for sid in reversed(list(user_pool.get(user_id, []) or [])):
        if sid and sid not in sids and sid in session_pool:
            sids.append(sid)
    return sids


def _describe_run_error(error: Exception, base_url: str) -> str:
    """The error text shown in the chat for a failed run, in the user's terms."""
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return f"等待 Hermes 网关响应超时 ({base_url})，请稍后重试"
    if isinstance(error, (aiohttp.ClientConnectionError, ConnectionRefusedError)):
        return (
            f"无法连接 Hermes 网关 ({base_url})，请确认 hermes gateway 正在运行: "
            f"{error}"
        )
    return f"Hermes 出错：{error}"


def _describe_start_failure(status: int, body: str) -> str:
    """The chat error for a POST /v1/runs that hermes refused."""
    detail = body
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict) and error.get("message"):
                detail = str(error["message"])
            elif isinstance(error, str):
                detail = error
    except (TypeError, ValueError):
        pass
    detail = str(detail or "").strip()[:300]
    if status == 429:
        return (
            "Hermes 同时运行的任务已达上限，等了一分钟仍没有空位。"
            "请等其他任务结束后重新发送。"
            + (f"（{detail}）" if detail else "")
        )
    if status in (401, 403):
        return f"Hermes 拒绝了访问（HTTP {status}），请检查连接里的 API 密钥。"
    return f"Hermes 启动任务失败（HTTP {status}）" + (f"：{detail}" if detail else "")


def _retry_after_seconds(headers, attempt: int) -> float:
    """Seconds to wait before re-posting a run hermes answered with 429."""
    try:
        value = float((headers or {}).get("Retry-After") or 0)
    except (TypeError, ValueError):
        value = 0
    return max(value, START_RETRY_MIN_DELAY + min(attempt, 4))


# What hermes' dangerous-command detector calls a command, in the words the
# approval dialog uses. Unknown descriptions keep hermes' text after a label.
APPROVAL_DESCRIPTIONS_ZH = {
    "recursive delete of root filesystem": "递归删除根文件系统",
    "recursive delete of system directory": "递归删除系统目录",
    "recursive delete of home directory": "递归删除用户主目录",
    "format filesystem (mkfs)": "格式化文件系统（mkfs）",
    "format filesystem": "格式化文件系统",
    "dd to raw block device": "用 dd 写入块设备",
    "redirect to raw block device": "重定向写入块设备",
    "write to block device": "写入块设备",
    "disk copy": "整盘复制",
    "fork bomb": "fork 炸弹",
    "kill all processes": "结束所有进程",
    "system shutdown/reboot": "关机或重启系统",
    "init 0/6 (shutdown/reboot)": "关机或重启系统（init 0/6）",
    "systemctl poweroff/reboot": "关机或重启系统（systemctl）",
    "telinit 0/6 (shutdown/reboot)": "关机或重启系统（telinit）",
    "sudo password guessing via stdin (sudo -S)": "通过标准输入给 sudo 传密码（sudo -S）",
    "delete in root path": "删除根路径下的文件",
    "recursive delete": "递归删除",
    "recursive delete (long flag)": "递归删除",
    "world/other-writable permissions": "设置所有人可写权限",
    "recursive world/other-writable (long flag)": "递归设置所有人可写权限",
    "recursive chown to root": "递归把属主改成 root",
    "recursive chown to root (long flag)": "递归把属主改成 root",
    "SQL DROP": "SQL 删除表或库（DROP）",
    "SQL DELETE without WHERE": "不带 WHERE 的 SQL DELETE",
    "SQL TRUNCATE": "SQL 清空表（TRUNCATE）",
    "overwrite system config": "覆盖系统配置",
    "stop/restart system service": "停止或重启系统服务",
    "force kill processes": "强制结束进程",
    "force kill processes (killall -KILL)": "强制结束进程（killall -KILL）",
    "force kill processes (killall -s KILL)": "强制结束进程（killall -s KILL）",
    "kill processes by regex (killall -r)": "按正则结束进程（killall -r）",
    "pipe remote content to shell": "把远程内容直接交给 shell 执行",
    "execute remote script via process substitution": "通过进程替换执行远程脚本",
    "execute remote content via command substitution": "通过命令替换执行远程内容",
    "pipe decoded content to shell (possible command obfuscation)": "把解码后的内容交给 shell 执行（可能是混淆命令）",
    "overwrite system file via tee": "用 tee 覆盖系统文件",
    "overwrite system file via redirection": "用重定向覆盖系统文件",
    "overwrite project env/config via tee": "用 tee 覆盖项目的 env/配置文件",
    "overwrite project env/config via redirection": "用重定向覆盖项目的 env/配置文件",
    "overwrite project env/config file": "覆盖项目的 env/配置文件",
    "xargs with rm": "xargs 配合 rm 批量删除",
    "find -exec/-execdir rm": "find -exec 批量删除",
    "find -delete": "find -delete 批量删除",
    "stop/restart hermes gateway (kills running agents)": "停止或重启 Hermes 网关（会中断正在运行的任务）",
    "hermes update (restarts gateway, kills running agents)": "更新 Hermes（会重启网关并中断正在运行的任务）",
    "docker compose restart/stop/kill/down (container lifecycle)": "重启、停止或删除 docker compose 容器",
    "docker restart/stop/kill (container lifecycle)": "重启或停止 docker 容器",
    "kill hermes/gateway process (self-termination)": "结束 Hermes 或网关进程（会中断自己）",
    "kill process via pgrep/pidof expansion (self-termination)": "按 pgrep/pidof 结果结束进程（可能中断自己）",
    "copy/move file into system config path": "把文件复制或移动到系统配置目录",
    "copy/move file into sensitive credential/SSH/shell-rc path": "把文件复制或移动到凭据/SSH/shell 配置目录",
    "in-place edit of sensitive credential/SSH/shell-rc path": "直接修改凭据/SSH/shell 配置文件",
    "in-place edit of system config": "直接修改系统配置",
    "in-place edit of Hermes config/env": "直接修改 Hermes 配置或 env",
    "shell execution via heredoc": "通过 heredoc 执行 shell",
    "git reset --hard (destroys uncommitted changes)": "git reset --hard（丢弃未提交的改动）",
    "git force push (rewrites remote history)": "git 强制推送（改写远程历史）",
    "git force push short flag (rewrites remote history)": "git 强制推送（改写远程历史）",
    "git clean with force (deletes untracked files)": "git clean -f（删除未跟踪的文件）",
    "git branch force delete": "强制删除 git 分支",
    "chmod +x followed by immediate execution": "加执行权限后立即执行",
    "sudo with privilege flag (stdin/askpass/shell/list)": "带提权参数的 sudo",
    "sudo with combined-flag privilege escalation": "带组合提权参数的 sudo",
}


def _approval_description_zh(description: str) -> str:
    """hermes' English reason for an approval, as the dialog shows it."""
    text = str(description or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r";\s*|\n+", text) if part.strip()]
    translated = []
    for part in parts:
        key = part.rstrip(".")
        zh = APPROVAL_DESCRIPTIONS_ZH.get(key) or APPROVAL_DESCRIPTIONS_ZH.get(
            re.sub(r"\s*\((?:long flag|long flags.*?)\)$", "", key)
        )
        translated.append(zh or f"危险操作：{part}")
    return "；".join(translated)


class HermesSteerError(Exception):
    """A steer that cannot be honoured; carries the HTTP status to answer with."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# chat_id -> the hermes run streaming into that chat right now. A chat has at
# most one live run (the UI queues further messages until it finishes), so the
# chat id is the handle for steering it and for listing what is executing.
_ACTIVE_RUNS: dict[str, dict] = {}


def _register_run(chat_id: str, entry: dict) -> None:
    _ACTIVE_RUNS[chat_id] = entry


def _unregister_run(chat_id: str, run_id) -> None:
    """Drop the registry entry, but only for the run that registered it."""
    entry = _ACTIVE_RUNS.get(chat_id)
    if run_id and entry is not None and entry.get("run_id") == run_id:
        _ACTIVE_RUNS.pop(chat_id, None)


def list_active_runs(user_id: str) -> list:
    runs = []
    for chat_id, entry in list(_ACTIVE_RUNS.items()):
        if entry.get("user_id") != user_id:
            continue
        approval = entry.get("approval")
        runs.append(
            {
                "chat_id": chat_id,
                "message_id": entry.get("message_id"),
                "run_id": entry.get("run_id"),
                "started_at": entry.get("started_at"),
                "steers": entry.get("steers", 0),
                "title": Chats.get_chat_title_by_id(chat_id),
                # A run blocked on a command approval: the sidebar shows it so
                # the person finds the dialog from any other chat.
                "awaiting_approval": bool(approval),
                "approval": (
                    {
                        "request_id": approval.get("request_id"),
                        "command": approval.get("command", ""),
                        "description": approval.get("description", ""),
                        "since": approval.get("since"),
                    }
                    if approval
                    else None
                ),
            }
        )
    runs.sort(key=lambda run: run["started_at"] or 0)
    return runs


async def steer_active_run(*, chat_id: str, user_id: str, text: str) -> dict:
    """Inject `text` into the run streaming in `chat_id`."""
    entry = _ACTIVE_RUNS.get(chat_id)
    # Another user's chat must look exactly like "no run": do not confirm it.
    if entry is None or entry.get("user_id") != user_id:
        raise HermesSteerError(404, "no hermes run is active for this chat")
    text = str(text or "").strip()
    if not text:
        raise HermesSteerError(400, "steer text is empty")
    await entry["steer"](text)
    entry["steers"] = entry.get("steers", 0) + 1
    return {
        "status": True,
        "chat_id": chat_id,
        "run_id": entry.get("run_id"),
        "accepted": True,
    }


def _model_upstream_id(model) -> str:
    """Return the upstream model id (without any connection prefix).

    Accepts either the raw model id string or a resolved model dict (which
    carries `original_id`/`model_ref.model_id` = the unprefixed upstream id,
    while its `id` may be prefixed like "ee5e02db.hermes-agent").
    """
    if isinstance(model, dict):
        original = model.get("original_id") or model.get("model_id")
        if original:
            return str(original)
        model_ref = model.get("model_ref")
        if isinstance(model_ref, dict) and model_ref.get("model_id"):
            return str(model_ref["model_id"])
        candidate = str(model.get("id") or model.get("selection_id") or "")
    else:
        candidate = str(model or "")
    if candidate in HERMES_AGENT_MODEL_IDS:
        return candidate
    # Selection ids ("modelref::openai::personal::id:<conn>::hermes-agent", what
    # the UI sends as `model`) carry the upstream id as their last segment.
    selection = parse_selection_id(candidate)
    if selection and selection.get("model_id"):
        return str(selection["model_id"])
    # Fall back to stripping a "<prefix>." connection prefix.
    if "." in candidate:
        stripped = candidate.split(".", 1)[1]
        if stripped in HERMES_AGENT_MODEL_IDS:
            return stripped
    return candidate


def is_hermes_agent_model(model) -> bool:
    """True when `model` (a raw id string or a resolved model dict) targets a
    hermes agent model, even if the UI selected a connection-prefixed id."""
    return _model_upstream_id(model) in HERMES_AGENT_MODEL_IDS


def _normalize_base_url(url: str) -> str:
    """Return the connection URL normalized to end with /v1 (no endpoint suffix)."""
    normalized = str(url or "").strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models"):
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def _resolve_hermes_connection(request, user, model, model_id):
    """Return (base_url, api_key, upstream_model_id) for the hermes connection,
    or (None, None, None) when it cannot be resolved."""
    upstream_model_id = _model_upstream_id(model) or model_id

    if HERMES_AGENT_BASE_URL:
        return (
            _normalize_base_url(HERMES_AGENT_BASE_URL),
            HERMES_AGENT_API_KEY,
            upstream_model_id,
        )

    try:
        from open_webui.routers.openai import (
            _get_openai_user_config,
            _normalize_openai_connection_key,
            _resolve_openai_connection_by_model_id,
        )
        from open_webui.utils.model_identity import get_model_ref_from_model

        # Mirror openai.generate_chat_completion's resolution exactly so we pick
        # the same connection it would. The resolved model dict carries the
        # connection routing info (connection_index + connection_id) that
        # disambiguates when several OpenAI connections are configured.
        request_models = getattr(
            getattr(request, "state", None), "MODELS", None
        ) or getattr(getattr(getattr(request, "app", None), "state", None), "MODELS", {})

        model_ref = get_model_ref_from_model(model) if isinstance(model, dict) else {}
        if not model_ref and isinstance(request_models, dict):
            model_ref = get_model_ref_from_model(request_models.get(model_id))

        connection_user = (
            getattr(getattr(request, "state", None), "connection_user", None) or user
        )
        base_urls, keys, cfgs = _get_openai_user_config(connection_user)
        if not base_urls:
            return None, None, None

        try:
            idx, url, key, api_config = _resolve_openai_connection_by_model_id(
                model_id,
                base_urls,
                keys,
                cfgs,
                model_ref=model_ref,
                request_models=request_models,
            )
            key, api_config = _normalize_openai_connection_key(
                key, api_config, url_idx=idx
            )
            if api_config.get("_resolved_model_id"):
                upstream_model_id = api_config["_resolved_model_id"]
        except Exception:
            # Single-connection fallback: with exactly one configured OpenAI
            # connection there is nothing ambiguous to resolve.
            usable = [(i, u) for i, u in enumerate(base_urls) if str(u or "").strip()]
            if len(usable) != 1:
                raise
            idx, url = usable[0]
            key = keys[idx] if idx < len(keys) else ""

        if not url:
            return None, None, None
        return _normalize_base_url(url), key or "", upstream_model_id
    except Exception as e:
        log.warning(f"Failed to resolve hermes agent connection for {model_id}: {e}")
        return None, None, None


def _normalize_multimodal_content(content):
    """Preserve OpenAI-compatible text and image parts for Hermes runs.

    The old adapter extracted only text, silently dropping uploaded images.
    Hermes accepts the same structured content shape used by the Responses
    API, so keep image parts intact (including image-only messages).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [part for part in content if isinstance(part, (dict, str))]
    return content if content is not None else ""


def _history_text_content(content) -> str:
    """Keep historical turns textual so inline image bytes are not replayed.

    Hermes treats inbound media as turn-scoped. Re-sending a prior data URL as
    conversation history can turn a small image into hundreds of thousands of
    text tokens when the runs endpoint serializes that history.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""

    text_parts = []
    has_image = False
    for part in content:
        if isinstance(part, str):
            if part.strip():
                text_parts.append(part.strip())
            continue
        if not isinstance(part, dict):
            continue

        part_type = part.get("type")
        if part_type in {"text", "input_text"}:
            text = part.get("text") or part.get("content") or ""
            if str(text).strip():
                text_parts.append(str(text).strip())
        elif part_type in {"image", "image_url", "input_image"}:
            has_image = True

    if has_image:
        text_parts.append("[Image attachment omitted from prior turn]")
    return "\n".join(text_parts)


def _content_has_text(content) -> bool:
    """True when `content` carries at least one non-blank text part."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for part in content:
            if isinstance(part, str) and part.strip():
                return True
            if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                if str(part.get("text") or part.get("content") or "").strip():
                    return True
        return False
    return bool(str(content or "").strip())


# What earlier assistant turns carry that hermes must not get back verbatim.
# The visual card is AGY's rendering of an answer hermes already wrote (69%
# of the characters a follow-up used to replay, on every model call of the
# turn); the tool transcript arrives as markup. Both become one line each.
HTML_CARD_PLACEHOLDER = "[已生成可视化卡片]"
HISTORY_TOOL_LINES_MAX = 24
HISTORY_TOOL_PREVIEW_MAX_CHARS = 160
_HTML_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
_TOOL_DETAILS_BLOCK_RE = re.compile(
    r"<details\b(?=[^>]*\btype=\"tool_calls\")([^>]*)>.*?</details\s*>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_CALLS_TAG_RE = re.compile(
    r"<tool_calls\b([^>]*?)/?>(?:\s*</tool_calls>)?", re.IGNORECASE
)
_OTHER_DETAILS_BLOCK_RE = re.compile(
    r"<details\b(?=[^>]*\btype=\"(?:reasoning|code_interpreter)\")[^>]*>.*?</details\s*>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_LINE_MARK = "\u0000tool\u0000"
_TOOL_STATUS_ZH = {"success": "成功", "error": "失败", "interrupted": "已中断"}


def _json_attr(value: str):
    """An HTML-escaped JSON attribute value, parsed (possibly double-encoded)."""
    current = html.unescape(str(value or ""))
    for _ in range(3):
        if not isinstance(current, str):
            break
        text = current.strip()
        if not text:
            return None
        try:
            current = json.loads(text)
        except ValueError:
            break
    return current


def _format_duration(seconds) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return ""
    if value < 0:
        return ""
    if value < 10:
        return f"{value:.1f}s"
    if value < 60:
        return f"{round(value)}s"
    minutes, rest = divmod(int(round(value)), 60)
    return f"{minutes}m{rest:02d}s"


def _tool_call_history_line(attributes: str) -> str:
    """One line for one tool call in a replayed turn: "terminal: git status（成功，2.1s）"."""
    attrs = {key: value for key, value in _HTML_ATTR_RE.findall(attributes or "")}
    name = html.unescape(attrs.get("name") or "tool").strip() or "tool"
    preview = html.unescape(attrs.get("input") or "").strip()
    if not preview:
        arguments = _json_attr(attrs.get("arguments", ""))
        if isinstance(arguments, dict) and isinstance(arguments.get("input"), str):
            preview = arguments["input"]
        elif isinstance(arguments, str):
            preview = arguments
    preview = re.sub(r"\s+", " ", preview).strip()
    if len(preview) > HISTORY_TOOL_PREVIEW_MAX_CHARS:
        preview = preview[: HISTORY_TOOL_PREVIEW_MAX_CHARS - 1].rstrip() + "\u2026"
    result = _json_attr(attrs.get("result", ""))
    outcome = []
    if isinstance(result, dict):
        status = str(result.get("status") or "").lower()
        if result.get("error") is True:
            status = "error"
        if status in _TOOL_STATUS_ZH:
            outcome.append(_TOOL_STATUS_ZH[status])
        duration = _format_duration(result.get("duration"))
        if duration and duration not in ("0.0s",):
            outcome.append(duration)
    elif attrs.get("done") == "false":
        outcome.append("未完成")
    line = f"{name}: {preview}" if preview else name
    if outcome:
        line = f"{line}（{'，'.join(outcome)}）"
    return f"{_TOOL_LINE_MARK}{line}\n"


def _collapse_tool_lines(text: str) -> str:
    """Group consecutive tool lines under one label, eliding the middle of long runs."""
    out_lines: list[str] = []
    run: list[str] = []

    def flush():
        if not run:
            return
        lines = run
        if len(lines) > HISTORY_TOOL_LINES_MAX:
            head = HISTORY_TOOL_LINES_MAX // 3
            tail = HISTORY_TOOL_LINES_MAX - head
            skipped = len(lines) - head - tail
            lines = lines[:head] + [f"…（省略 {skipped} 次工具调用）"] + lines[-tail:]
        out_lines.append(f"[工具调用 ×{len(run)}]")
        out_lines.extend(f"- {line}" for line in lines)
        run.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(_TOOL_LINE_MARK):
            run.append(stripped[len(_TOOL_LINE_MARK):])
            continue
        if not stripped and run:
            continue
        flush()
        out_lines.append(line)
    flush()
    return "\n".join(out_lines)


def _compact_assistant_history(content: str) -> str:
    """An earlier assistant turn as hermes should read it again: the answer
    text, each visual card as a placeholder, each tool call as one line."""
    text = str(content or "")
    if not text:
        return text
    text = _FENCED_HTML_BLOCK_RE.sub(f"{HTML_CARD_PLACEHOLDER}\n", text)
    text = _OTHER_DETAILS_BLOCK_RE.sub("", text)
    text = _TOOL_DETAILS_BLOCK_RE.sub(
        lambda match: _tool_call_history_line(match.group(1)), text
    )
    text = _TOOL_CALLS_TAG_RE.sub(
        lambda match: _tool_call_history_line(match.group(1)), text
    )
    if _TOOL_LINE_MARK in text:
        text = _collapse_tool_lines(text)
    return _BLANK_RUN_RE.sub("\n\n", text).strip()


_DETAILS_BLOCK_RE = re.compile(
    r"<details\b[^>]*>.*?</details>", re.IGNORECASE | re.DOTALL
)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _webhook_summary(content: str) -> str:
    """The answer as it should read on a phone, not as it renders in the chat."""
    text = _DETAILS_BLOCK_RE.sub("", str(content or ""))
    text = _fenced_html_artifacts_as_text(text)
    text = _BLANK_RUN_RE.sub("\n\n", text).strip()
    if len(text) > WEBHOOK_CONTENT_MAX_CHARS:
        text = text[:WEBHOOK_CONTENT_MAX_CHARS].rstrip() + "\u2026"
    return text


def is_temporary_chat_id(chat_id) -> bool:
    """A temporary chat ("临时对话") is never saved; the client sends the
    placeholder id ``local`` for every one of them."""
    chat_id = str(chat_id or "")
    return chat_id == "local" or chat_id.startswith("local:")


def _schedule_completion_webhook(request, user, metadata, title, content):
    """Push a finished hermes run to the user's notification webhook when no
    tab shows it to them.

    hermes runs return from main.chat_completion before process_chat_response,
    so the completion webhook that lives there never fires for them - and hermes
    turns are exactly the long ones the user walks away from. Presence decides
    (a registered socket, or the requesting tab still connected, with a grace
    window for a reconnect); the push runs in the background so it never delays
    the completion event or the title/tags bookkeeping.
    """
    try:
        summary = _webhook_summary(content)
        chat_url = f"{request.app.state.config.WEBUI_URL}/c/{metadata['chat_id']}"
        heading = f"{title} - {chat_url}" if title else chat_url
        schedule_away_webhook(
            user_id=user.id,
            session_id=metadata.get("session_id"),
            name=request.app.state.WEBUI_NAME,
            message=f"{heading}\n\n{summary}",
            event_data={
                "action": "chat",
                "message": summary,
                "title": title or "",
                "url": chat_url,
            },
            log_tag="hermes completion",
        )
    except Exception as e:
        log.warning(f"hermes completion webhook failed: {e}")


def _schedule_approval_webhook(request, user, metadata, approval: dict):
    """Push a pending command approval to the user's notification webhook when
    no tab can show the dialog.

    Approvals auto-deny after HERMES_AGENT_APPROVAL_TIMEOUT. With no tab
    connected nothing else tells the person a run is waiting on them, and
    hermes runs are exactly the ones they walk away from. The grace here is
    short: it only rides out a reconnecting tab, the rest of the timeout
    belongs to the person."""
    try:
        title = Chats.get_chat_title_by_id(metadata["chat_id"]) or ""
        chat_url = f"{request.app.state.config.WEBUI_URL}/c/{metadata['chat_id']}"
        lines = [f"⏳ {APPROVAL_TITLE}", f"{title} - {chat_url}" if title else chat_url, ""]
        if approval.get("description"):
            lines.append(str(approval["description"]))
        if approval.get("command"):
            lines.append(f"命令: {approval['command']}")
        lines.append(f"{int(approval.get('timeout') or 0)} 秒内未处理将自动拒绝")
        message = "\n".join(lines)
        if len(message) > WEBHOOK_CONTENT_MAX_CHARS:
            message = message[:WEBHOOK_CONTENT_MAX_CHARS].rstrip() + "\u2026"
        schedule_away_webhook(
            user_id=user.id,
            session_id=metadata.get("session_id"),
            name=request.app.state.WEBUI_NAME,
            message=message,
            event_data={
                "action": "approval",
                "message": message,
                "title": title,
                "url": chat_url,
            },
            grace_seconds=APPROVAL_WEBHOOK_GRACE_SECONDS,
            log_tag="hermes approval",
        )
    except Exception as e:
        log.warning(f"hermes approval webhook failed: {e}")


# The composer's "派发方式": the same prefixes a person types, so hermes (and
# its skill bundles) sees exactly what /reclaude typed by hand would send.
HERMES_DISPATCH_COMMANDS = {"reclaude": "/reclaude", "codex": "/codex", "agy": "/agy"}
# What hermes' runs API takes as model_options.reasoning_effort ("ultra" is
# hermes-only; the web UI never sends it).
HERMES_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _hermes_run_options(form_data) -> dict:
    """The per-chat hermes choices the composer sent, validated."""
    raw = form_data.get("hermes_options") if isinstance(form_data, dict) else None
    if not isinstance(raw, dict):
        return {}
    options = {}
    dispatch = str(raw.get("dispatch") or "").strip().lower()
    if dispatch in HERMES_DISPATCH_COMMANDS:
        options["dispatch"] = dispatch
    model = str(raw.get("model") or "").strip()
    if model and len(model) <= 200:
        options["model"] = model
        provider = str(raw.get("provider") or "").strip()
        if provider and len(provider) <= 200:
            options["provider"] = provider
    return options


def _inherited_reasoning_effort(form_data) -> str | None:
    """The chat's own thinking level (对话控制 / the admin default /
    "深度思考发送"), which the middleware lifts from params into the body.
    Without one hermes keeps its configured reasoning_effort.

    For codex_responses / chat_completions models hermes' halowebui-reasoning-sync
    plugin (integrations/hermes-plugin) then sets the admin default on every
    request, so a per-chat level only changes models on other API modes
    (anthropic_messages)."""
    if not isinstance(form_data, dict):
        return None
    effort = str(form_data.get("reasoning_effort") or "").strip().lower()
    return effort if effort in HERMES_REASONING_EFFORTS else None


# A command is "/name" followed by a space or the end: "/reclaude fix it",
# "/model". "/root/app/x.txt" is a path, not a command.
_SLASH_COMMAND_RE = re.compile(r"^/[A-Za-z][\w-]*(?:\s|$)")
_RUNNER_COMMAND_RE = re.compile(r"^/(reclaude|codex|agy)(?:\s|$)", re.IGNORECASE)


def _starts_with_command(text) -> bool:
    return bool(_SLASH_COMMAND_RE.match(str(text or "").lstrip()))


def _run_input_text(run_input) -> str:
    """The first text of a run input (a string or a one-message array)."""
    if isinstance(run_input, str):
        return run_input
    if isinstance(run_input, list) and run_input and isinstance(run_input[-1], dict):
        content = run_input[-1].get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                    return str(part.get("text") or "")
    return ""


def _dispatch_runner(run_input) -> str | None:
    """"reclaude" / "codex" / "agy" when the input launches that runner."""
    match = _RUNNER_COMMAND_RE.match(_run_input_text(run_input).lstrip())
    return match.group(1).lower() if match else None


def _prefix_run_input(run_input, prefix: str):
    """Put `prefix` in front of the user's text, unless the text already starts
    with a slash command (typed by hand, it wins over the composer setting)."""
    if isinstance(run_input, str):
        if _starts_with_command(run_input):
            return run_input
        return f"{prefix} {run_input.lstrip()}"
    if isinstance(run_input, list) and run_input and isinstance(run_input[-1], dict):
        content = run_input[-1].get("content")
        if isinstance(content, list):
            for index, part in enumerate(content):
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                    text = str(part.get("text") or "")
                    if _starts_with_command(text):
                        return run_input
                    parts = list(content)
                    parts[index] = {**part, "text": f"{prefix} {text.lstrip()}"}
                    return [*run_input[:-1], {**run_input[-1], "content": parts}]
            parts = [{"type": "text", "text": prefix}, *content]
            return [*run_input[:-1], {**run_input[-1], "content": parts}]
    return run_input


def _append_run_input_text(run_input, text: str):
    """Add a paragraph to the end of the user's text."""
    if not text:
        return run_input
    if isinstance(run_input, str):
        return f"{run_input.rstrip()}\n\n{text}"
    if isinstance(run_input, list) and run_input and isinstance(run_input[-1], dict):
        content = run_input[-1].get("content")
        if isinstance(content, list):
            parts = [*content, {"type": "text", "text": text}]
            return [*run_input[:-1], {**run_input[-1], "content": parts}]
    return run_input


_HOST_DATA_DIR_CACHE: dict = {}


def _host_data_dir():
    """This container's data directory as the hermes host sees it, or None.

    hermes runs on the host and cannot see container paths. The data volume's
    host path is in /proc/self/mountinfo (the mount's root within its device,
    which is the host path when that device is the host's root filesystem)."""
    if "value" in _HOST_DATA_DIR_CACHE:
        return _HOST_DATA_DIR_CACHE["value"]
    value = None
    configured = os.environ.get("HERMES_AGENT_HOST_DATA_DIR", "").strip()
    if configured.lower() in {"off", "none", "0", "false"}:
        value = None
    elif configured:
        value = configured.rstrip("/")
    else:
        try:
            data_dir = str(DATA_DIR).rstrip("/")
            with open("/proc/self/mountinfo", encoding="utf-8") as handle:
                for line in handle:
                    fields = line.split()
                    if len(fields) > 4 and fields[4] == data_dir and fields[3] != "/":
                        value = fields[3].rstrip("/")
                        break
        except OSError:
            value = None
    _HOST_DATA_DIR_CACHE["value"] = value
    return value


def _attachment_host_paths(metadata, user) -> list[tuple[str, str]]:
    """(name, host path) of the non-image files attached to this turn.

    Retrieval only put excerpts of them into the prompt; hermes runs on the
    same host and can read the whole file when it is told where it is."""
    host_dir = _host_data_dir()
    files = metadata.get("files") if isinstance(metadata, dict) else None
    if not host_dir or not isinstance(files, list):
        return []
    try:
        from open_webui.models.files import Files
    except Exception:
        return []
    data_dir = str(DATA_DIR).rstrip("/")
    found = []
    seen = set()
    for item in files:
        if not isinstance(item, dict) or item.get("type") not in (None, "file"):
            continue
        file_info = item.get("file") if isinstance(item.get("file"), dict) else {}
        file_id = str(item.get("id") or file_info.get("id") or "").strip()
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        content_type = str(
            ((file_info.get("meta") or {}) if isinstance(file_info.get("meta"), dict) else {}).get(
                "content_type"
            )
            or ""
        )
        if content_type.startswith("image/"):
            continue
        try:
            record = Files.get_file_by_id(file_id)
        except Exception:
            record = None
        if record is None or not record.path:
            continue
        if record.user_id != getattr(user, "id", None) and getattr(user, "role", "") != "admin":
            continue
        path = str(record.path)
        if not path.startswith(data_dir + "/"):
            continue
        name = str(item.get("name") or record.filename or os.path.basename(path))
        found.append((name, host_dir + path[len(data_dir):]))
    return found


def _attachment_note(paths: list[tuple[str, str]]) -> str:
    if not paths:
        return ""
    lines = ["[附件原文件] 以下文件已上传到 HaloWebUI，上面只放了检索摘录；需要完整内容时直接读取本机路径："]
    lines.extend(f"- {name}: {path}" for name, path in paths)
    return "\n".join(lines)


def _build_run_payload(form_data, metadata, upstream_model_id, user=None):
    messages = form_data.get("messages") or []

    instructions = None
    history = []
    for message in messages:
        role = message.get("role")
        content = _normalize_multimodal_content(message.get("content"))
        if role == "system":
            system_content = _history_text_content(content)
            instructions = (
                f"{instructions}\n{system_content}"
                if instructions
                else system_content
            )
        else:
            history.append({"role": role, "content": content})

    # No trailing user turn means the UI asked to continue the assistant's own
    # last message ("continue response"), which stays in the history below.
    continuing = bool(history) and history[-1].get("role") != "user"
    user_message = ""
    if history and history[-1].get("role") == "user":
        user_message = history.pop()["content"]

    # Inbound media is turn-scoped. Historical image data URLs must not be
    # replayed: /v1/runs would stringify them and count the base64 as text.
    history = [
        {
            "role": message["role"],
            "content": (
                _compact_assistant_history(_history_text_content(message["content"]))
                if message["role"] == "assistant"
                else _history_text_content(message["content"])
            ),
        }
        for message in history
    ]

    # The runs API accepts a string input or an OpenAI-style message array.  A
    # multimodal content list is a list of parts, not a list of messages; pass
    # it as the content of a user message so the API can find the user turn.
    fallback_input = CONTINUE_RUN_INPUT if continuing else ATTACHMENT_ONLY_RUN_INPUT
    if isinstance(user_message, list):
        run_input = (
            [{"role": "user", "content": user_message}]
            if user_message
            else fallback_input
        )
    else:
        if not _content_has_text(user_message):
            user_message = fallback_input
        run_input = user_message

    options = _hermes_run_options(form_data)
    if not continuing:
        run_input = _append_run_input_text(
            run_input, _attachment_note(_attachment_host_paths(metadata, user))
        )
        if options.get("dispatch"):
            run_input = _prefix_run_input(
                run_input, HERMES_DISPATCH_COMMANDS[options["dispatch"]]
            )

    payload = {
        "input": run_input,
        "model": options.get("model") or upstream_model_id,
    }
    runner = None if continuing else _dispatch_runner(run_input)
    if runner and HERMES_AGENT_FAST_DISPATCH:
        # The typed prefix stays in the input: a hermes without the fast path
        # (or one that declines it) launches the same run through its model.
        payload["dispatch"] = {"runner": runner}
    if options.get("provider"):
        payload["provider"] = options["provider"]
    reasoning_effort = _inherited_reasoning_effort(form_data)
    if reasoning_effort:
        payload["model_options"] = {"reasoning_effort": reasoning_effort}
    if history:
        payload["conversation_history"] = history
    if instructions:
        payload["instructions"] = instructions
    # The chat id doubles as the hermes session, so a chat keeps its session
    # (approvals "for this chat", resumable history). Temporary chats all
    # share the id "local": as a session it would hand one temporary chat
    # another's history. Without an id hermes starts a fresh session per run;
    # the conversation still travels in conversation_history.
    if metadata.get("chat_id") and not is_temporary_chat_id(metadata["chat_id"]):
        payload["session_id"] = metadata["chat_id"]
    return payload


def _materialize_run_input_image_refs(payload, *, user_id: str, is_admin: bool):
    """Materialize only images attached to the current Hermes run input."""
    run_input = payload.get("input")
    if not isinstance(run_input, list):
        return payload

    materialized = materialize_openai_image_message_refs(
        {"messages": run_input},
        user_id=user_id,
        is_admin=is_admin,
    )
    return {
        **payload,
        "input": materialized.get("messages") or run_input,
    }


def _mark_undelivered_steers(blocks, pending_steer) -> int:
    """Flag the steer blocks hermes never read.

    hermes reports guidance it accepted after the final response in
    ``pending_steer`` on ``run.completed``. Those quotes already sit in the
    transcript; mark them so the rendering says the run ended before reading
    them instead of implying they were followed. Returns the number flagged.
    """
    pending = str(pending_steer or "").strip()
    if not pending:
        return 0
    flagged = 0
    for block in reversed(blocks):
        if block.get("type") != "steer" or block.get("undelivered"):
            continue
        text = str(block.get("content", "")).strip()
        if text and text in pending:
            block["undelivered"] = True
            flagged += 1
            pending = pending.replace(text, "", 1)
            if not pending.strip():
                break
    return flagged


def _serialize_blocks(blocks) -> str:
    content = ""
    for block in blocks:
        if block["type"] == "text":
            text = str(block.get("content", "")).strip()
            if text:
                content = f"{content}{text}\n"
        elif block["type"] == "steer":
            # Guidance the user injected while the run executed, quoted at the
            # point in the transcript where it landed.
            lines = str(block.get("content", "")).strip().splitlines() or [""]
            quoted = []
            for index, line in enumerate(lines):
                prefix = "\U0001f9ed " if index == 0 else ""
                quoted.append(f"> {prefix}{line}")
            if block.get("undelivered"):
                quoted.append("> \u26a0\ufe0f 未送达：任务在采纳这条指引前已结束")
            content = f"{content}\n" + "\n".join(quoted) + "\n\n"
        elif block["type"] == "tool":
            arguments = html.escape(
                json.dumps({"input": block.get("preview") or ""}, ensure_ascii=False)
            )
            # When the call started (epoch seconds): the running row shows
            # its own clock instead of a bare "executing".
            started = (
                f' started="{float(block["started_at"]):.1f}"'
                if block.get("started_at")
                else ""
            )
            if block.get("done"):
                outcome = {"duration": block.get("duration", 0)}
                if block.get("interrupted"):
                    outcome = {"status": "interrupted", **outcome}
                elif block.get("status_unknown"):
                    pass
                else:
                    outcome = {
                        "status": "error" if block.get("error") else "success",
                        **outcome,
                    }
                if block.get("reason"):
                    outcome["reason"] = str(block["reason"])
                result = html.escape(json.dumps(outcome, ensure_ascii=False))
                content = (
                    f"{content}\n"
                    f'<details type="tool_calls" done="true" id="{block["id"]}" '
                    f'name="{html.escape(str(block.get("name") or "tool"))}"{started} '
                    f'arguments="{arguments}" result="{result}">\n'
                    f"<summary>Tool Executed</summary>\n</details>\n"
                )
            else:
                content = (
                    f"{content}\n"
                    f'<details type="tool_calls" done="false" id="{block["id"]}" '
                    f'name="{html.escape(str(block.get("name") or "tool"))}"{started} '
                    f'arguments="{arguments}">\n'
                    f"<summary>Executing...</summary>\n</details>\n"
                )
    return content.strip()


def _complete_tool_block(blocks, event) -> bool:
    """Mark the call a tool.completed event reports as done.

    hermes (local patch) sends the call's id with both events; two calls of the
    same tool running in parallel are then told apart. Without an id the latest
    unfinished call of that name is taken, as before."""
    call_id = str(event.get("tool_call_id") or "")
    tool_name = event.get("tool")
    target = None
    if call_id:
        target = next(
            (
                block
                for block in blocks
                if block["type"] == "tool"
                and not block.get("done")
                and block.get("call_id") == call_id
            ),
            None,
        )
    if target is None:
        target = next(
            (
                block
                for block in reversed(blocks)
                if block["type"] == "tool"
                and not block.get("done")
                and (block.get("name") == tool_name or tool_name is None)
            ),
            None,
        )
    if target is None:
        return False
    target["done"] = True
    target["duration"] = event.get("duration", 0)
    target["error"] = bool(event.get("error"))
    return True


def _describe_model_fallback(event) -> str:
    source = str(event.get("from_model") or "").strip() or "所选模型"
    target = str(event.get("to_model") or "").strip() or "备用模型"
    return f"{source} 不可用，已改用 {target}"


def _settle_unfinished_tools(blocks, *, interrupted: bool, reason: str = "") -> int:
    """Close the tool calls that never reported completion.

    After a run ends, a call still "running" can only be one whose completion
    event was lost. On a run that failed, stopped or broke off it was cut
    short: mark it interrupted, with the reason. On a run that completed its
    outcome is unknown: close it without a status rather than claim success.
    Returns the number of calls closed."""
    now = time.time()
    closed = 0
    for block in blocks:
        if block.get("type") != "tool" or block.get("done"):
            continue
        block["done"] = True
        started_at = block.get("started_at")
        block["duration"] = round(max(0.0, now - float(started_at)), 1) if started_at else 0
        if interrupted:
            block["interrupted"] = True
            if reason:
                block["reason"] = reason
        else:
            block["status_unknown"] = True
        closed += 1
    return closed


_UNFINISHED_TOOL_DETAILS_RE = re.compile(
    r'<details type="tool_calls" done="false"([^>]*)>\s*<summary>[^<]*</summary>\s*</details>',
    re.IGNORECASE,
)


def _settle_unfinished_tool_markup(content: str, reason: str) -> str:
    """_settle_unfinished_tools for a reply known only as saved markup (a run
    picked up again after this process restarted)."""
    result = html.escape(
        json.dumps({"status": "interrupted", "reason": reason}, ensure_ascii=False)
    )

    def _close(match):
        attributes = match.group(1)
        return (
            f'<details type="tool_calls" done="true"{attributes} result="{result}">\n'
            f"<summary>Tool Executed</summary>\n</details>"
        )

    return _UNFINISHED_TOOL_DETAILS_RE.sub(_close, str(content or ""))


def _trailing_text(content: str) -> str:
    """The reply text after its last tool call."""
    text = str(content or "")
    last = text.rfind("</details>")
    return text[last + len("</details>"):] if last >= 0 else text


def _merge_recovered_output(content: str, output: str) -> str:
    """Add the final answer hermes kept to a reply whose stream broke off.

    The stream may already have carried the start of that answer (text after
    the last tool call); the answer replaces it instead of repeating it."""
    output = str(output or "").strip()
    if not output:
        return content
    content = str(content or "").rstrip()
    trailing = _trailing_text(content).strip()
    if trailing and (output.startswith(trailing) or trailing in output):
        return f"{content[: len(content) - len(_trailing_text(content))].rstrip()}\n{output}".strip()
    return f"{content}\n{output}".strip() if content else output


_DATA_URL_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\((data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+)\)"
)


def _store_data_url_images(request, user, metadata, text: str) -> str:
    """Persist inline base64 images as uploaded files and rewrite them to
    file-content URLs.

    Hermes resolves MEDIA:<path> image tags in the final run output into
    markdown data URLs (the web UI container cannot read hermes's local file
    paths). Storing the multi-MB base64 blob in the chat would bloat the DB
    and get echoed back to hermes as conversation history on every following
    message, so save it via the same upload path the built-in image
    generation uses and reference it by URL instead.
    """
    if not text or "data:image/" not in text:
        return text

    from open_webui.routers.images import load_b64_image_data, upload_image

    def _repl(match):
        try:
            loaded = load_b64_image_data(match.group(2))
            if not loaded:
                return match.group(0)
            image_data, content_type = loaded
            url = upload_image(
                request,
                {"source": "hermes-agent", "chat_id": metadata.get("chat_id")},
                image_data,
                content_type,
                user,
            )
            return f"![{match.group(1) or 'image'}]({url})"
        except Exception as e:
            log.warning(f"hermes media image upload failed: {e}")
            return match.group(0)

    return _DATA_URL_IMAGE_RE.sub(_repl, text)


# ---------------------------------------------------------------- recovery

# Set when this process starts shutting down. A run task cancelled then is
# not a user's stop: hermes keeps working, and the run is picked up again
# from INFLIGHT_RUNS_FILE after the restart.
_SHUTTING_DOWN = False


def begin_shutdown() -> None:
    global _SHUTTING_DOWN
    _SHUTTING_DOWN = True


def _inflight_path() -> str:
    return os.path.join(str(DATA_DIR), INFLIGHT_RUNS_FILE)


def _load_inflight() -> dict:
    try:
        with open(_inflight_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_inflight(data: dict) -> None:
    path = _inflight_path()
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        os.replace(temporary, path)
    except OSError as e:
        log.warning(f"hermes in-flight registry write failed: {e}")


def _remember_inflight(chat_id: str, record: dict) -> None:
    data = _load_inflight()
    data[chat_id] = record
    _save_inflight(data)


def _forget_inflight(chat_id: str, run_id) -> None:
    data = _load_inflight()
    entry = data.get(chat_id)
    if entry is not None and (not run_id or entry.get("run_id") == run_id):
        data.pop(chat_id, None)
        _save_inflight(data)


# Statuses GET /v1/runs/{id} reports once a run is over.
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "interrupted"}

RECOVERY_MESSAGES = {
    "waiting": "与 Hermes 的实时连接断开了，任务仍在运行，正在等它结束…",
    "interrupted": (
        "Hermes 网关在任务结束前重启了，任务已中断。已经执行的步骤不会回滚，"
        "可以发一句“继续”让 Hermes 接着做。"
    ),
    "lost": (
        "与 Hermes 的连接断开后没能取回这次任务的结果（网关可能已重启）。"
        "已经执行的步骤不会回滚，可以发一句“继续”让 Hermes 接着做。"
    ),
    "timeout": "等了很久也没等到 Hermes 任务结束，已停止等待。任务可能仍在后台运行。",
}


def _recovery_delay(attempt: int) -> float:
    return RECOVERY_POLL_DELAYS[min(attempt, len(RECOVERY_POLL_DELAYS) - 1)]


async def _fetch_run_status(base_url: str, headers: dict, run_id: str):
    """(http status, body) of GET /v1/runs/{id}; (None, None) when unreachable."""
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
            async with session.get(
                f"{base_url}/runs/{run_id}",
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as resp:
                if resp.status >= 400:
                    return resp.status, None
                return resp.status, await resp.json()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.debug(f"hermes run status poll failed for {run_id}: {e}")
        return None, None


async def _await_run_outcome(
    base_url: str,
    headers: dict,
    run_id: str,
    *,
    max_seconds: float = None,
    on_waiting=None,
    on_approval=None,
) -> dict:
    """Poll GET /v1/runs/{id} until the run is over.

    Returns hermes' status body for a finished run, ``{"status": "lost"}``
    when hermes no longer knows the run (it restarted without a durable
    record, or forgot it) and ``{"status": "timeout"}`` after `max_seconds`.
    An unreachable gateway (restarting) is waited out like a running run.
    ``on_approval(event)`` is awaited for an approval the run is blocked on."""
    max_seconds = HERMES_AGENT_RECOVERY_MAX_SECONDS if max_seconds is None else max_seconds
    deadline = time.time() + max_seconds
    attempt = 0
    announced = False
    answered_approvals = set()
    while True:
        status_code, body = await _fetch_run_status(base_url, headers, run_id)
        if status_code == 404:
            return {"status": "lost"}
        if isinstance(body, dict):
            status = str(body.get("status") or "")
            if status in TERMINAL_RUN_STATUSES:
                return body
            approval = body.get("approval")
            if (
                status == "waiting_for_approval"
                and on_approval is not None
                and isinstance(approval, dict)
            ):
                key = str(approval.get("request_id") or approval.get("command") or "")
                if key not in answered_approvals:
                    answered_approvals.add(key)
                    await on_approval(approval)
                    attempt = 0
                    continue
        if not announced and on_waiting is not None:
            announced = True
            try:
                await on_waiting()
            except Exception:
                pass
        if time.time() >= deadline:
            return {"status": "timeout"}
        await asyncio.sleep(_recovery_delay(attempt))
        attempt += 1


def _api_root(base_url: str) -> str:
    base_url = str(base_url or "").rstrip("/")
    return base_url[: -len("/v1")] if base_url.endswith("/v1") else base_url


async def _final_answer_from_session(
    base_url: str, headers: dict, session_id: str, since: float
):
    """The answer a run left in its hermes session, when the run itself is gone.

    hermes writes every turn to the session store before it reports the run
    finished, so after a restart the newest assistant message of the chat's
    session (newer than the run, and not followed by a newer user turn) is
    the answer the chat never received."""
    if not session_id or is_temporary_chat_id(session_id):
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
            async with session.get(
                f"{_api_root(base_url)}/api/sessions/{session_id}/messages",
                params={"order": "latest", "limit": "30", "offset": "0"},
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as resp:
                if resp.status >= 400:
                    return None
                page = await resp.json()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.debug(f"hermes session read failed for {session_id}: {e}")
        return None
    rows = page.get("data") if isinstance(page, dict) else None
    if not isinstance(rows, list):
        return None

    def _stamp(row):
        try:
            value = float(row.get("timestamp") or 0)
        except (TypeError, ValueError):
            return 0.0
        return value / 1000 if value > 1e12 else value

    rows = sorted(
        (row for row in rows if isinstance(row, dict)), key=_stamp, reverse=True
    )
    for row in rows:
        role = row.get("role")
        if role == "user":
            return None
        if role != "assistant" or row.get("display_kind") == "hidden":
            continue
        if _stamp(row) and _stamp(row) < since - 5:
            return None
        text = row.get("content")
        if isinstance(text, list):
            text = "\n".join(
                str(part.get("text") or "")
                for part in text
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            )
        text = str(text or "").strip()
        if text:
            return text
    return None


# A file hermes attached to its answer (MEDIA:<path> of a non-image file,
# inlined by hermes' /v1/runs as a markdown link to a data URL).
_DATA_URL_FILE_RE = re.compile(
    r"(?<!!)\[([^\]\n]{0,200})\]\((data:(?!image/)[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+)\)"
)


def _store_generated_file(request, user, metadata, name: str, data: bytes, content_type: str) -> str:
    """Save bytes hermes produced as one of the user's files; returns its URL."""
    import io
    import uuid

    from open_webui.models.files import FileForm, Files
    from open_webui.storage.provider import Storage

    name = os.path.basename(str(name or "").strip()) or "file"
    file_id = str(uuid.uuid4())
    size, path = Storage.upload_file(io.BytesIO(data), f"{file_id}_{name}")
    Files.insert_new_file(
        user.id,
        FileForm(
            id=file_id,
            filename=name,
            path=path,
            meta={
                "name": name,
                "content_type": content_type,
                "size": size,
                "data": {"source": "hermes-agent", "chat_id": metadata.get("chat_id")},
            },
        ),
    )
    return f"/api/v1/files/{file_id}/content"


def _store_data_url_files(request, user, metadata, text: str) -> str:
    """Persist files hermes inlined as data URLs and link to them instead.

    Same reason as _store_data_url_images: the web UI cannot read hermes'
    paths, and base64 in the chat would bloat it and be replayed to hermes."""
    if not text or "data:" not in text:
        return text

    import base64
    import binascii

    def _repl(match):
        label = match.group(1).strip()
        header, _, payload = match.group(2).partition(",")
        content_type = header[len("data:"):].split(";", 1)[0] or "application/octet-stream"
        try:
            data = base64.b64decode(re.sub(r"\s+", "", payload), validate=True)
            name = label or f"hermes-file{mimetypes_guess(content_type)}"
            url = _store_generated_file(request, user, metadata, name, data, content_type)
            return f"[{label or name}]({url})"
        except (binascii.Error, ValueError) as e:
            log.warning(f"hermes media file decode failed: {e}")
        except Exception as e:
            log.warning(f"hermes media file upload failed: {e}")
        return f"`{label or '文件'}`（文件未能保存）"

    return _DATA_URL_FILE_RE.sub(_repl, text)


def mimetypes_guess(content_type: str) -> str:
    import mimetypes

    return mimetypes.guess_extension(content_type or "") or ""


def _map_usage(usage):
    """OpenAI-style usage from a run's; None when it counted nothing (a fast
    dispatch, or a hermes that reported no usage), which the UI would otherwise
    show as "消耗 0 Token"."""
    if not isinstance(usage, dict):
        return None
    mapped = {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
    return mapped if any(isinstance(v, (int, float)) and v > 0 for v in mapped.values()) else None


def _runtime_from_event(event) -> dict:
    """What a hermes run reports about how it ran (local hermes patch): the
    model that actually answered (``model_used`` / ``provider_used``), the one
    it fell back from, and for a fast dispatch the runner it started. Found on
    run.completed and on the run status a recovery poll reads."""
    if not isinstance(event, dict):
        return {}
    runtime = {}
    for source, target in (
        ("model_used", "model"),
        ("provider_used", "provider"),
        ("fallback_from", "fallback_from"),
    ):
        value = str(event.get(source) or "").strip()
        if value:
            runtime[target] = value[:200]
    dispatch = event.get("dispatch")
    if isinstance(dispatch, dict):
        runner = str(dispatch.get("runner") or "").strip().lower()
        if runner in HERMES_DISPATCH_COMMANDS:
            runtime["dispatch"] = runner
        runner_run_id = str(dispatch.get("run_id") or "").strip()
        if runner_run_id:
            runtime["runner_run_id"] = runner_run_id[:128]
        if dispatch.get("fast"):
            runtime["fast_dispatch"] = True
    return runtime


# The launch command of a background runner (reclaude-run.sh run|answer,
# codex-run.sh, agy-run.sh), as the terminal call's preview shows it.
_RUNNER_LAUNCH_RE = re.compile(
    r"(?:reclaude|codex|agy)-run\.sh\s+(?:run|answer)\b|runner-detach\.py"
)


def _launched_runner(blocks, runtime) -> bool:
    """True when the run started a background runner. Its reply is a
    three-line receipt: no visual card (the runner's report gets one)."""
    if runtime.get("runner_run_id") or runtime.get("fast_dispatch"):
        return True
    return any(
        block.get("type") == "tool"
        and _RUNNER_LAUNCH_RE.search(str(block.get("preview") or ""))
        for block in blocks
    )


async def run_hermes_agent(request, form_data, user, metadata, model, events, tasks=None):
    """
    Execute the chat via hermes's runs API, streaming results over the chat
    socket. Returns a background-task response dict, or None when this path
    cannot handle the request (caller should fall back to the normal flow).
    """
    if not (
        metadata.get("session_id")
        and metadata.get("chat_id")
        and metadata.get("message_id")
    ):
        return None

    model_id = form_data.get("model")
    base_url, api_key, upstream_model_id = _resolve_hermes_connection(
        request, user, model, model_id
    )
    if not base_url:
        return None

    event_emitter = get_event_emitter(metadata)
    event_caller = get_event_call(metadata)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # The normal OpenAI path materializes /api/v1/files/... image references,
    # but Hermes is dispatched before that path. Materialize the current input
    # only; replaying prior images would inflate later turns with base64 data.
    run_payload = _build_run_payload(form_data, metadata, upstream_model_id, user)
    run_payload = _materialize_run_input_image_refs(
        run_payload,
        user_id=user.id,
        is_admin=user.role == "admin",
    )

    def upsert_response_message(message: dict):
        return Chats.upsert_message_to_chat_by_id_and_message_id(
            metadata["chat_id"],
            metadata["message_id"],
            message,
            guard_stopped=True,
        )

    upsert_response_message({"model": model_id})

    async def _emit_completion(data: dict):
        await event_emitter({"type": "chat:completion", "data": data})

    async def _emit_status(description: str, done: bool, action: str = "hermes_agent"):
        try:
            await event_emitter(
                {
                    "type": "status",
                    "data": {
                        "action": action,
                        "description": description,
                        "done": done,
                    },
                }
            )
        except Exception:
            pass

    async def _ask_user_sessions(approval_data: dict, deadline: float):
        """Show the approval dialog in every live tab of the user; the first
        answer wins. Returns None when no tab answered this round (no tab at
        all, or none of them has this chat open so the call timed out)."""
        sids = _approval_target_sids(user.id, metadata.get("session_id"))
        if not sids:
            await asyncio.sleep(APPROVAL_RETRY_DELAY_SECONDS)
            return None
        payload = {
            "chat_id": metadata["chat_id"],
            "message_id": metadata["message_id"],
            "data": {"type": APPROVAL_EVENT_TYPE, "data": approval_data},
        }
        timeout = max(1, min(WEBSOCKET_EVENT_CALLER_TIMEOUT, int(deadline - time.time())))
        calls = [
            asyncio.create_task(sio.call("chat-events", payload, to=sid, timeout=timeout))
            for sid in sids
        ]
        answer = None
        try:
            for finished in asyncio.as_completed(calls):
                try:
                    result = await finished
                except Exception:
                    continue
                if result is not None:
                    answer = result
                    break
        finally:
            for call in calls:
                if not call.done():
                    call.cancel()
        if answer is None:
            await asyncio.sleep(APPROVAL_RETRY_DELAY_SECONDS)
        return answer

    async def _request_approval(session, run_id, event):
        command = str(event.get("command") or "")
        description = _approval_description_zh(event.get("description") or "")
        choices = _approval_choices(event)
        timeout_seconds = max(HERMES_AGENT_APPROVAL_TIMEOUT, 30)
        requested_at = time.time()
        deadline = requested_at + timeout_seconds
        request_id = str(
            event.get("request_id") or f"{run_id}:{int(requested_at * 1000)}"
        )
        approval_data = {
            "request_id": request_id,
            "run_id": run_id,
            "chat_id": metadata["chat_id"],
            "title": APPROVAL_TITLE,
            "description": description,
            "command": command,
            "choices": choices,
            "timeout": timeout_seconds,
            "requested_at": requested_at,
        }

        entry = _ACTIVE_RUNS.get(metadata["chat_id"])
        if entry is not None and entry.get("run_id") == run_id:
            entry["approval"] = {
                "request_id": request_id,
                "command": command,
                "description": description,
                "since": requested_at,
            }

        await _emit_status("等待你批准命令审批...", False, action="hermes_approval")
        _schedule_approval_webhook(request, user, metadata, approval_data)

        choice = "deny"
        try:
            while time.time() < deadline:
                result = await _ask_user_sessions(approval_data, deadline)
                if result is None:
                    continue
                choice = _normalize_approval_choice(result, choices)
                break
        finally:
            if entry is not None and entry.get("run_id") == run_id:
                entry.pop("approval", None)

        # Close the dialog in every other tab that still shows it.
        try:
            await event_emitter(
                {
                    "type": APPROVAL_RESOLVED_EVENT_TYPE,
                    "data": {"request_id": request_id, "choice": choice},
                }
            )
        except Exception:
            pass

        try:
            async with session.post(
                f"{base_url}/runs/{run_id}/approval",
                json={"choice": choice},
                headers=headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    log.warning(
                        f"hermes approval post failed ({resp.status}): {body[:500]}"
                    )
        except Exception as e:
            log.warning(f"hermes approval post error: {e}")

        await _emit_status(
            {
                "once": "命令已批准，继续执行...",
                "session": "命令已批准（本对话内不再询问），继续执行...",
                "always": "命令已批准（始终允许），继续执行...",
            }.get(choice, "命令已拒绝"),
            True,
            action="hermes_approval",
        )

    async def _post_stop(run_id):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(
                trust_env=True, timeout=timeout
            ) as session:
                await session.post(
                    f"{base_url}/runs/{run_id}/stop",
                    json={},
                    headers=headers,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                )
        except Exception as e:
            log.debug(f"hermes stop post error: {e}")

    run_options = _hermes_run_options(form_data)
    requested_dispatch = (run_payload.get("dispatch") or {}).get("runner") or _dispatch_runner(
        run_payload.get("input")
    )

    async def _run_handler():
        blocks = []
        run_id = None
        finalized = False
        # How the run actually went (model used, fallback, fast dispatch);
        # recorded on the reply next to what was asked for.
        runtime: dict = {}
        last_content_emit = 0.0
        pending_flush = None

        def _cancel_pending_flush():
            nonlocal pending_flush
            task = pending_flush
            pending_flush = None
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()

        async def _flush_content_later(delay: float):
            nonlocal pending_flush, last_content_emit
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            pending_flush = None
            if finalized:
                return
            last_content_emit = time.monotonic()
            try:
                await _emit_completion({"content": _serialize_blocks(blocks)})
            except Exception as e:
                log.debug(f"hermes content flush failed: {e}")

        async def _emit_content(throttle: bool = False):
            """Send the reply so far. Text deltas pass throttle=True: at most
            one update per HERMES_AGENT_STREAM_EMIT_INTERVAL, the rest folded
            into a flush scheduled for the end of the interval."""
            nonlocal pending_flush, last_content_emit
            if finalized:
                return
            now = time.monotonic()
            wait = HERMES_AGENT_STREAM_EMIT_INTERVAL - (now - last_content_emit)
            if throttle and wait > 0:
                if pending_flush is None or pending_flush.done():
                    pending_flush = asyncio.create_task(_flush_content_later(wait))
                return
            _cancel_pending_flush()
            last_content_emit = now
            await _emit_completion({"content": _serialize_blocks(blocks)})

        def current_text_block():
            if not blocks or blocks[-1]["type"] != "text":
                blocks.append({"type": "text", "content": ""})
            return blocks[-1]

        def _apply_final_output(output, recovered=False):
            # Hermes resolves MEDIA:<path> image tags into markdown images
            # only in the final output; the delta stream carried the raw tag
            # text. Swap the streamed text for the resolved output so the
            # image renders instead of a server-side file path.
            if not output:
                return
            output = _store_data_url_images(request, user, metadata, output)
            output = _store_data_url_files(request, user, metadata, output)
            if recovered:
                # The stream broke off: the answer may be missing entirely or
                # only its first part arrived (the text after the last tool).
                tail = len(blocks)
                while tail > 0 and blocks[tail - 1]["type"] == "text":
                    tail -= 1
                trailing = "".join(
                    str(block.get("content", "")) for block in blocks[tail:]
                ).strip()
                if trailing and (output.strip().startswith(trailing) or trailing in output):
                    del blocks[tail:]
                    blocks.append({"type": "text", "content": output})
                elif trailing != output.strip():
                    blocks.append({"type": "text", "content": output})
                return
            for block in reversed(blocks):
                if block["type"] == "text" and str(block.get("content", "")).strip():
                    if "MEDIA:" in block["content"] and "![" in output:
                        block["content"] = output
                    return
            blocks.append({"type": "text", "content": output})

        def _run_state(pending_steer=None) -> dict:
            state = {
                "active": False,
                "run_id": run_id,
                "steers": sum(1 for block in blocks if block.get("type") == "steer"),
            }
            if pending_steer:
                state["pending_steer"] = str(pending_steer)
            # Who answered: the runner it was handed to and the model asked
            # for (the reply header shows them, and a later look at the chat
            # can tell), plus what hermes reports it actually used.
            details = {
                "dispatch": runtime.get("dispatch") or requested_dispatch,
                "requested_model": run_options.get("model"),
                "model": runtime.get("model"),
                "provider": runtime.get("provider"),
                "fallback_from": runtime.get("fallback_from"),
                "runner_run_id": runtime.get("runner_run_id"),
                "fast_dispatch": runtime.get("fast_dispatch"),
            }
            state.update({key: value for key, value in details.items() if value})
            return state

        async def _finalize(
            error=None, usage=None, successful=False, pending_steer=None
        ):
            nonlocal finalized
            if finalized:
                return
            finalized = True
            _cancel_pending_flush()
            _unregister_run(metadata["chat_id"], run_id)
            _forget_inflight(metadata["chat_id"], run_id)
            _settle_unfinished_tools(
                blocks,
                interrupted=bool(error) or not successful,
                reason=(error or "")[:200] if error else "",
            )
            # hermes stopped reading input the moment the run ended. Tell the
            # composer now so its send button turns from "steer" into "queue"
            # instead of offering a steer that can only be refused. Persisted
            # too, so a reload shows the same.
            _mark_undelivered_steers(blocks, pending_steer)
            run_state = _run_state(pending_steer)
            try:
                await _emit_completion({"hermes_run": run_state})
            except Exception as e:
                log.debug(f"hermes run-state emit failed: {e}")
            try:
                upsert_response_message({"hermes_run": run_state})
            except Exception as e:
                log.debug(f"hermes run-state persist failed: {e}")
            # The reply is marked done with the plain answer; the AGY HTML
            # design pass (tens of seconds, up to its timeout) runs afterwards
            # in _design_html_visual and swaps the artifact in when ready.
            content = _serialize_blocks(blocks)
            completed_at = int(time.time())
            data = {
                "done": True,
                "content": content,
                "completedAt": completed_at,
                "hermes_run": run_state,
            }
            mapped_usage = _map_usage(usage)
            if mapped_usage:
                data["usage"] = mapped_usage
            if error:
                data["error"] = {"content": error}
            title = Chats.get_chat_title_by_id(metadata["chat_id"])
            if title:
                data["title"] = title
            # Unread until the chat is opened: the sidebar dot for runs that
            # finished while nobody was looking (the client clears it on open).
            # A temporary chat has no sidebar entry to open.
            temporary = is_temporary_chat_id(metadata["chat_id"])
            if not temporary:
                mark_unread(metadata["chat_id"], user.id)
            try:
                upsert_response_message(
                    {
                        "content": content,
                        "done": True,
                        "completedAt": completed_at,
                        "hermes_run": run_state,
                        **({"usage": mapped_usage} if mapped_usage else {}),
                        **({"error": {"content": error}} if error else {}),
                    }
                )
            except Exception as e:
                log.warning(f"hermes completion persist failed: {e}")
            try:
                await _emit_completion(data)
            except Exception as e:
                log.warning(f"hermes completion emit failed: {e}")
            # Finished from the user's point of view; what follows is
            # post-processing that must not keep the chat looking busy.
            set_current_task_blocks_completion(False)
            # The push links to the chat; a temporary one cannot be reopened.
            if not temporary:
                _schedule_completion_webhook(request, user, metadata, title, content)

            async def _background_tasks():
                # Post-response bookkeeping (title/tags/follow-ups), same as the
                # normal chat flow in process_chat_response.
                try:
                    from open_webui.utils.middleware import background_tasks_handler

                    await background_tasks_handler(
                        request, user, metadata, tasks, event_emitter
                    )
                except Exception as e:
                    log.warning(f"hermes background tasks failed: {e}")

            # A reply that only says a runner started is a receipt: turning it
            # into a card took ~40 s and replaced three lines with a big block.
            if successful and not error and not _launched_runner(blocks, runtime):
                await asyncio.gather(
                    _background_tasks(), _design_html_visual(content)
                )
            else:
                await _background_tasks()

        async def _design_html_visual(content):
            try:
                designed = await design_html_visual_artifact_with_agy(content, metadata)
                designed = append_html_visual_fallback(designed, metadata)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(f"hermes html visual design failed: {e}")
                return
            if designed == content:
                return
            try:
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    metadata["chat_id"],
                    metadata["message_id"],
                    {"content": designed},
                    guard_stopped=True,
                    set_current=False,
                )
            except Exception as e:
                log.warning(f"hermes html visual persist failed: {e}")
            try:
                await _emit_completion({"content": designed})
            except Exception as e:
                log.warning(f"hermes html visual emit failed: {e}")

        async def _conclude_after_stream_loss(run_started_at: float):
            announced = False

            async def _announce_waiting():
                nonlocal announced
                announced = True
                await _emit_status(
                    RECOVERY_MESSAGES["waiting"], False, action="hermes_recovering"
                )

            async def _approve_while_polling(approval_event):
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(
                    trust_env=True, timeout=timeout
                ) as approval_session:
                    await _request_approval(approval_session, run_id, approval_event)

            outcome = await _await_run_outcome(
                base_url,
                headers,
                run_id,
                on_waiting=_announce_waiting,
                on_approval=_approve_while_polling,
            )
            status = str(outcome.get("status") or "")
            runtime.update(_runtime_from_event(outcome))
            if announced:
                await _emit_status(
                    "已取回 Hermes 的结果" if status in ("completed", "lost") else "Hermes 任务已结束",
                    True,
                    action="hermes_recovering",
                )
            if status == "completed":
                _apply_final_output(outcome.get("output") or "", recovered=True)
                await _finalize(
                    usage=outcome.get("usage"),
                    successful=True,
                    pending_steer=outcome.get("pending_steer"),
                )
            elif status == "failed":
                await _finalize(error=outcome.get("error") or "Hermes 任务失败")
            elif status == "cancelled":
                await _finalize()
            elif status == "interrupted":
                await _finalize(error=RECOVERY_MESSAGES["interrupted"])
            elif status == "lost":
                answer = await _final_answer_from_session(
                    base_url, headers, metadata["chat_id"], run_started_at
                )
                if answer:
                    _apply_final_output(answer, recovered=True)
                    await _finalize(successful=True)
                else:
                    await _finalize(error=RECOVERY_MESSAGES["lost"])
            else:
                await _finalize(error=RECOVERY_MESSAGES["timeout"])

        async def _steer(text: str):
            # Forward to hermes first; only a run that accepted the text gets
            # the transcript marker. 404/409 from hermes both mean "no longer
            # accepting input", which is a 409 for our caller.
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(
                trust_env=True, timeout=timeout
            ) as session:
                async with session.post(
                    f"{base_url}/runs/{run_id}/steer",
                    json={"input": text},
                    headers=headers,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        raise HermesSteerError(
                            409 if resp.status in (404, 409) else 502,
                            f"hermes did not accept the steer ({resp.status}): {body[:300]}",
                        )
            blocks.append({"type": "steer", "content": text})
            await _emit_content()

        try:
            for event in events or []:
                await _emit_completion(event)
                upsert_response_message({**event})

            timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=120)
            # The reply id as idempotency key: hermes then keeps the run's
            # status durably, so after a gateway restart GET /v1/runs/{id}
            # says "interrupted" instead of forgetting the run, and a start
            # re-posted after a lost response cannot launch it twice.
            start_headers = {
                **headers,
                "Idempotency-Key": f"halowebui-{metadata['message_id']}"[:255],
            }
            async with aiohttp.ClientSession(
                trust_env=True, timeout=timeout
            ) as session:
                start_deadline = time.time() + START_RETRY_MAX_SECONDS
                attempt = 0
                while True:
                    async with session.post(
                        f"{base_url}/runs",
                        json=run_payload,
                        headers=start_headers,
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    ) as resp:
                        if resp.status == 429 and time.time() < start_deadline:
                            delay = _retry_after_seconds(resp.headers, attempt)
                            attempt += 1
                            await _emit_status(
                                f"Hermes 同时运行的任务已满，{int(delay)} 秒后自动重试（第 {attempt} 次）…",
                                False,
                                action="hermes_start_retry",
                            )
                            await asyncio.sleep(delay)
                            continue
                        if resp.status >= 400:
                            body = await resp.text()
                            await _finalize(
                                error=_describe_start_failure(resp.status, body)
                            )
                            return
                        run_data = await resp.json()
                        break
                if attempt:
                    await _emit_status("Hermes 已开始执行", True, action="hermes_start_retry")
                run_id = run_data.get("run_id")
                if not run_id:
                    await _finalize(error="Hermes 没有返回任务 ID，任务可能没有启动")
                    return
                run_started_at = time.time()
                _register_run(
                    metadata["chat_id"],
                    {
                        "user_id": user.id,
                        "message_id": metadata["message_id"],
                        "run_id": run_id,
                        "started_at": run_started_at,
                        "steers": 0,
                        "steer": _steer,
                    },
                )
                if not is_temporary_chat_id(metadata["chat_id"]):
                    _remember_inflight(
                        metadata["chat_id"],
                        {
                            "run_id": run_id,
                            "message_id": metadata["message_id"],
                            "user_id": user.id,
                            "base_url": base_url,
                            "model_id": model_id,
                            "started_at": run_started_at,
                        },
                    )

                # A broken connection (gateway restart, network drop) is not
                # the end of the run: fall through to the outcome poll below.
                try:
                    async with session.get(
                        f"{base_url}/runs/{run_id}/events",
                        headers=headers,
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                        read_bufsize=HERMES_EVENTS_READ_BUFSIZE,
                    ) as resp:
                        if resp.status >= 400:
                            body = await resp.text()
                            await _finalize(
                                error=f"无法读取 Hermes 任务进度（HTTP {resp.status}）：{body[:300]}"
                            )
                            return

                        while True:
                            try:
                                raw_line = await resp.content.readline()
                            except ValueError as e:
                                # "Chunk too big": a single SSE line exceeded
                                # read_bufsize. Don't fail the chat — fall through
                                # to the status poll below, which reads the same
                                # final output as plain JSON with no line limit.
                                log.warning(f"hermes event stream read aborted: {e}")
                                break
                            if not raw_line:
                                break
                            line = raw_line.decode("utf-8", errors="ignore").strip()
                            if not line or line.startswith(":"):
                                continue
                            if not line.startswith("data:"):
                                continue
                            try:
                                event = json.loads(line[len("data:") :].strip())
                            except Exception:
                                continue

                            event_type = event.get("event")

                            if event_type == "message.delta":
                                delta = event.get("delta") or ""
                                if delta:
                                    current_text_block()["content"] += delta
                                    await _emit_content(throttle=True)
                            elif event_type == "tool.started":
                                blocks.append(
                                    {
                                        "type": "tool",
                                        "id": f"hermes-{len(blocks)}",
                                        "call_id": str(event.get("tool_call_id") or ""),
                                        "name": event.get("tool") or "tool",
                                        "preview": event.get("preview") or "",
                                        "done": False,
                                        "started_at": event.get("timestamp") or time.time(),
                                    }
                                )
                                await _emit_content()
                            elif event_type == "tool.completed":
                                _complete_tool_block(blocks, event)
                                await _emit_content()
                            elif event_type == "run.model_fallback":
                                # The chosen model failed and hermes moved on
                                # to its fallback: say so now, not only in the
                                # header once the run is over.
                                runtime.update(
                                    {
                                        key: value
                                        for key, value in {
                                            "fallback_from": str(event.get("from_model") or "")[:200],
                                            "model": str(event.get("to_model") or "")[:200],
                                            "provider": str(event.get("to_provider") or "")[:200],
                                        }.items()
                                        if value
                                    }
                                )
                                await _emit_status(
                                    _describe_model_fallback(event),
                                    True,
                                    action="hermes_model_fallback",
                                )
                            elif event_type == "reasoning.available":
                                # Not real reasoning: hermes re-emits the assistant
                                # message content (first 500 chars) after every turn
                                # for delegation progress displays. The same text
                                # already arrives via message.delta, so rendering it
                                # would duplicate the answer as a "thinking" block.
                                pass
                            elif event_type == "approval.request":
                                await _request_approval(session, run_id, event)
                            elif event_type == "approval.responded":
                                pass
                            elif event_type == "run.completed":
                                runtime.update(_runtime_from_event(event))
                                _apply_final_output(event.get("output") or "")
                                await _finalize(
                                    usage=event.get("usage"),
                                    successful=True,
                                    pending_steer=event.get("pending_steer"),
                                )
                            elif event_type == "run.failed":
                                await _finalize(
                                    error=event.get("error") or "Hermes 任务失败"
                                )
                            elif event_type == "run.cancelled":
                                await _finalize()
                except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as e:
                    if finalized:
                        raise
                    log.warning(f"hermes event stream for {run_id} broke off: {e!r}")

            if not finalized:
                # The event stream ended without the run's terminal event: the
                # gateway restarted, the connection dropped, or a line was too
                # big to read. The run may still be going (or be done); ask
                # hermes until it is over instead of closing the reply as if
                # it were complete with its tools "running" forever.
                await _conclude_after_stream_loss(run_started_at)
        except asyncio.CancelledError:
            _cancel_pending_flush()
            if _SHUTTING_DOWN and run_id:
                # This process is going away, not the person stopping the
                # run: hermes keeps working. Save what arrived so far; after
                # the restart the run is picked up again from the registry.
                try:
                    upsert_response_message({"content": _serialize_blocks(blocks)})
                except Exception:
                    pass
                raise
            if run_id:
                try:
                    await asyncio.shield(_post_stop(run_id))
                except Exception:
                    pass
                _forget_inflight(metadata["chat_id"], run_id)
            try:
                _settle_unfinished_tools(blocks, interrupted=True, reason="已手动停止")
                content = _serialize_blocks(blocks)
                upsert_response_message(
                    {
                        "content": content,
                        "done": True,
                        "completedAt": int(time.time()),
                        "hermes_run": _run_state(),
                    }
                )
            except Exception:
                pass
            raise
        except Exception as e:
            log.exception("hermes agent run failed")
            await _finalize(error=_describe_run_error(e, base_url))
        finally:
            _cancel_pending_flush()
            _unregister_run(metadata["chat_id"], run_id)

    task_id, _ = create_task(_run_handler(), id=metadata["chat_id"])
    return {"status": True, "task_id": task_id}


# ------------------------------------------------ recovery after a restart


def _api_key_for_base_url(user, base_url: str) -> str:
    """The key of the user's connection that points at `base_url`."""
    if HERMES_AGENT_BASE_URL:
        return HERMES_AGENT_API_KEY
    try:
        from open_webui.routers.openai import (
            _get_openai_user_config,
            _normalize_openai_connection_key,
        )

        base_urls, keys, configs = _get_openai_user_config(user)
        for index, url in enumerate(base_urls):
            if _normalize_base_url(url) != base_url:
                continue
            api_config = configs.get(str(index)) or configs.get(url) or {}
            key, _ = _normalize_openai_connection_key(
                keys[index] if index < len(keys) else "", api_config, url_idx=index
            )
            return key or ""
    except Exception as e:
        log.warning(f"hermes recovery could not resolve the connection key: {e}")
    return ""


async def _recover_inflight_run(app, chat_id: str, record: dict) -> None:
    """Finish a reply whose run was still going when this process stopped."""
    from types import SimpleNamespace

    from open_webui.models.users import Users

    run_id = str(record.get("run_id") or "")
    message_id = str(record.get("message_id") or "")
    user = Users.get_user_by_id(str(record.get("user_id") or ""))
    base_url = str(record.get("base_url") or "")
    if not (run_id and message_id and user and base_url):
        _forget_inflight(chat_id, run_id)
        return
    message = Chats.get_message_by_id_and_message_id(chat_id, message_id) or {}
    if message.get("done") or message.get("stoppedByUser") or message.get("stopped"):
        _forget_inflight(chat_id, run_id)
        return

    api_key = _api_key_for_base_url(user, base_url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    metadata = {"chat_id": chat_id, "message_id": message_id, "user_id": user.id}
    emitter = get_event_emitter(metadata)
    request = SimpleNamespace(app=app, state=SimpleNamespace())

    async def _status(description: str, done: bool):
        try:
            await emitter(
                {
                    "type": "status",
                    "data": {
                        "action": "hermes_recovering",
                        "description": description,
                        "done": done,
                    },
                }
            )
        except Exception:
            pass

    log.info(f"picking up hermes run {run_id} for chat {chat_id} after a restart")
    await _status("HaloWebUI 重启过，正在向 Hermes 取回这次任务的结果…", False)
    try:
        outcome = await _await_run_outcome(base_url, headers, run_id)
    except asyncio.CancelledError:
        if not _SHUTTING_DOWN:
            # Stopped from the chat while waiting: stop hermes too.
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
                    await session.post(
                        f"{base_url}/runs/{run_id}/stop",
                        json={},
                        headers=headers,
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    )
            except Exception:
                pass
            _forget_inflight(chat_id, run_id)
        raise

    status = str(outcome.get("status") or "")
    output = None
    error = None
    usage = None
    if status == "completed":
        output = outcome.get("output") or ""
        usage = _map_usage(outcome.get("usage"))
    elif status == "failed":
        error = outcome.get("error") or "Hermes 任务失败"
    elif status == "interrupted":
        error = RECOVERY_MESSAGES["interrupted"]
    elif status == "lost":
        output = await _final_answer_from_session(
            base_url, headers, chat_id, float(record.get("started_at") or 0)
        )
        if not output:
            error = RECOVERY_MESSAGES["lost"]
    elif status != "cancelled":
        error = RECOVERY_MESSAGES["timeout"]

    content = str(message.get("content") or "")
    content = _settle_unfinished_tool_markup(
        content, (error or "任务在 HaloWebUI 重启期间结束，这一步的结果没有传回来")[:200]
    )
    if output:
        try:
            output = _store_data_url_images(request, user, metadata, output)
            output = _store_data_url_files(request, user, metadata, output)
        except Exception as e:
            log.warning(f"hermes recovered output media failed: {e}")
        content = _merge_recovered_output(content, output)
    completed_at = int(time.time())
    run_state = {"active": False, "run_id": run_id, "recovered": True}
    runtime = _runtime_from_event(outcome)
    for key in ("dispatch", "model", "provider", "fallback_from", "runner_run_id", "fast_dispatch"):
        if runtime.get(key):
            run_state[key] = runtime[key]
    update = {
        "content": content,
        "done": True,
        "completedAt": completed_at,
        "hermes_run": run_state,
        **({"usage": usage} if usage else {}),
        **({"error": {"content": error}} if error else {}),
    }
    try:
        Chats.upsert_message_to_chat_by_id_and_message_id(
            chat_id, message_id, update, guard_stopped=True, set_current=False
        )
    except Exception as e:
        log.warning(f"hermes recovered reply persist failed: {e}")
    _forget_inflight(chat_id, run_id)
    mark_unread(chat_id, user.id)
    title = Chats.get_chat_title_by_id(chat_id)
    await _status("已取回 Hermes 的结果" if output else "Hermes 任务已结束", True)
    try:
        await emitter(
            {
                "type": "chat:completion",
                "data": {**update, **({"title": title} if title else {})},
            }
        )
    except Exception as e:
        log.debug(f"hermes recovered reply emit failed: {e}")
    try:
        _schedule_completion_webhook(request, user, metadata, title, content)
    except Exception:
        pass


def resume_inflight_runs(app) -> int:
    """Pick up every run this process was streaming when it last stopped.

    Called once at startup. Each becomes a chat task again, so the chat shows
    it as running (and can stop it) until hermes reports the outcome."""
    records = _load_inflight()
    resumed = 0
    for chat_id, record in list(records.items()):
        if not isinstance(record, dict):
            _forget_inflight(chat_id, None)
            continue
        try:
            create_task(_recover_inflight_run(app, chat_id, record), id=chat_id)
            resumed += 1
        except Exception as e:
            log.warning(f"hermes run recovery for chat {chat_id} failed to start: {e}")
    if resumed:
        log.info(f"resuming {resumed} hermes run(s) left in flight by the last shutdown")
    return resumed

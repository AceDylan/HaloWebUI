"""Automatic chat folder assignment.

Runs right after a reply on the title-generation cadence (user turn 1, then
every multiple of 3) and asks the configured task model to pick ONE of the
user's existing top-level folders for the chat, or ``null``.

Rules (kept deliberately small and testable):

* ``chat.meta.folder_assignment`` carries ``source`` (``auto`` | ``manual``),
  ``evaluations`` and the last evaluated turn / message id.
* ``manual`` is written by the sidebar move / remove endpoint and freezes the
  chat forever. A chat that sits in a folder without any marker is treated as
  manual as well.
* ``auto`` chats may be corrected while ``evaluations`` is below
  :data:`MAX_AUTO_EVALUATIONS`. A ``null`` answer never moves a chat out of
  its folder. Every attempt counts, whether or not the model answered.
* Old chats are never back-filled; an unmarked, unfoldered chat starts being
  evaluated at the next title milestone it reaches and then gets the usual
  budget of three evaluations at consecutive milestones.
* The model only ever chooses among the caller's own existing folders; it
  cannot create folders. Sub-folders are not candidates in this first version.
* The six default folders are created once per user, the first time the
  feature runs for a user who has no folders at all. Deleting them is final.

Everything that touches the database or the model goes through
:class:`FolderAssignmentDeps`, so the orchestration can be unit-tested with
fakes and the middleware glue stays a few lines.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from open_webui.env import (
    FOLDER_AUTO_ASSIGNMENT_TIMEOUT,
    FOLDER_MAX_ITEM_COUNT,
    SRC_LOG_LEVELS,
)
from open_webui.models.chats import Chats, get_folder_assignment_metadata

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


MAX_AUTO_EVALUATIONS = 3
USER_INFO_KEY = "folder_auto_assignment"
PRESETS_VERSION = 1

# Fixed top-level folders. Names are what the model sees and must echo back;
# descriptions are stored in ``folder.meta.description`` and shown to the
# model as the folder's purpose. Renaming a folder later is fine: candidates
# are always read back from the database.
DEFAULT_FOLDER_PRESETS = (
    {
        "key": "ops",
        "name": "服务器与 Hermes 运维",
        "description": "服务状态、reclaude、YCE、CCG、定时任务、配置与密钥、额度与故障排查",
    },
    {
        "key": "halowebui",
        "name": "HaloWebUI 开发",
        "description": "本项目 HaloWebUI 的修复、同步、功能改造、构建与部署",
    },
    {
        "key": "coding",
        "name": "编程与技术问答",
        "description": "通用语言语法、Linux 命令、算法题等技术问题，不针对本机服务",
    },
    {
        "key": "image",
        "name": "图片生成",
        "description": "出图、写真、图解、图像模型调试与分辨率排查",
    },
    {
        "key": "news",
        "name": "资讯与热点",
        "description": "新闻、贴吧热帖、灾情、产品上线时间等外部信息查询",
    },
    {
        "key": "life",
        "name": "生活与闲聊",
        "description": "小说剧情、节日习俗、益智题、助手能力试探等",
    },
)

NULL_ANSWERS = {"", "null", "none", "no", "n/a", "无", "不归类", "不分组", "未分组"}

_DETAILS_BLOCK_RE = re.compile(r"<details\b[^>]*>.*?</details>", re.S | re.I)
_TEMPLATE_VAR_RE = re.compile(r"{{(FOLDER_OPTIONS|CHAT_TITLE|CHAT_HISTORY)}}")


####################
# Eligibility
####################


def is_folder_assignment_milestone(user_message_count: Any) -> bool:
    """Same cadence as the frontend title milestones: turn 1, then 3, 6, 9..."""
    if isinstance(user_message_count, bool) or not isinstance(user_message_count, int):
        return False
    return user_message_count >= 1 and (
        user_message_count == 1 or user_message_count % 3 == 0
    )


def get_evaluation_count(meta: Optional[dict]) -> int:
    evaluations = get_folder_assignment_metadata(meta).get("evaluations")
    if isinstance(evaluations, bool) or not isinstance(evaluations, int):
        return 0
    return max(evaluations, 0)


def can_auto_assign_folder(
    folder_id: Optional[str],
    meta: Optional[dict],
    user_message_count: Any,
    message_id: Optional[str] = None,
) -> bool:
    """Return whether the background task may evaluate this chat right now."""
    if not is_folder_assignment_milestone(user_message_count):
        return False

    assignment = get_folder_assignment_metadata(meta)
    source = assignment.get("source")

    if source == "manual":
        return False
    if not assignment:
        # Never evaluated. Chats already sitting in a folder were put there by
        # hand before markers existed, so leave them alone.
        return not folder_id
    if source != "auto":
        return False

    if get_evaluation_count(meta) >= MAX_AUTO_EVALUATIONS:
        return False

    last_message_id = assignment.get("last_message_id")
    if message_id and isinstance(last_message_id, str) and message_id == last_message_id:
        return False

    last_user_message_count = assignment.get("last_user_message_count")
    if (
        isinstance(last_user_message_count, int)
        and not isinstance(last_user_message_count, bool)
        and user_message_count <= last_user_message_count
    ):
        return False

    return True


####################
# Candidates & prompt
####################


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_folder_candidates(folders: Optional[list]) -> list[dict]:
    """Top-level folders of one user, in creation order, with their purpose."""
    candidates = []
    for folder in folders or []:
        if _get(folder, "parent_id"):
            continue
        name = str(_get(folder, "name") or "").strip()
        folder_id = _get(folder, "id")
        if not name or not folder_id:
            continue
        meta = _get(folder, "meta") or {}
        description = ""
        if isinstance(meta, dict):
            description = str(meta.get("description") or "").strip()
        candidates.append(
            {
                "id": folder_id,
                "name": name,
                "description": description,
                "_order": (int(_get(folder, "created_at") or 0), name),
            }
        )

    candidates.sort(key=lambda candidate: candidate["_order"])
    for candidate in candidates:
        candidate.pop("_order", None)
    return candidates


def format_folder_options(candidates: list[dict]) -> str:
    lines = []
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        if not name:
            continue
        description = str(candidate.get("description") or "").strip()
        lines.append(f"- {name}: {description}" if description else f"- {name}")
    return "\n".join(lines)


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        content = "\n".join(parts)
    text = str(content or "")
    text = _DETAILS_BLOCK_RE.sub("", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def format_chat_history(
    messages: Optional[list[dict]],
    *,
    max_messages: int = 8,
    max_chars_per_message: int = 500,
    max_total_chars: int = 3000,
) -> str:
    """Compact transcript for the classifier: last N messages, each clipped."""
    rows = []
    for message in (messages or [])[-max_messages:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").upper() or "MESSAGE"
        text = _message_text(message)
        if not text:
            continue
        if max_chars_per_message > 0 and len(text) > max_chars_per_message:
            text = text[:max_chars_per_message] + "…"
        rows.append(f"{role}: {text}")

    history = "\n".join(rows)
    if max_total_chars > 0 and len(history) > max_total_chars:
        history = history[-max_total_chars:]
    return history


def folder_assignment_template(
    template: str,
    candidates: list[dict],
    title: Optional[str],
    messages: Optional[list[dict]],
) -> str:
    values = {
        "FOLDER_OPTIONS": format_folder_options(candidates),
        "CHAT_TITLE": str(title or "").strip() or "(none)",
        "CHAT_HISTORY": format_chat_history(messages),
    }
    return _TEMPLATE_VAR_RE.sub(lambda match: values[match.group(1)], template)


####################
# Response parsing
####################


def parse_completion_text(res: Any) -> str:
    if not isinstance(res, dict):
        return ""
    choices = res.get("choices") or []
    if len(choices) != 1 or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return str(content or "").strip()


def parse_folder_choice(text: Optional[str], candidates: list[dict]) -> Optional[dict]:
    """Map the model answer onto exactly one candidate, or None.

    Accepts ``{"folder": "name"}``, ``{"folder": null}`` or a bare folder name.
    Anything that is not an exact (or unique case-insensitive) match of an
    existing candidate name is treated as "leave the chat where it is"."""
    text = str(text or "").strip()
    if not text:
        return None

    answer: Any = text
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except Exception:
            data = None
        if isinstance(data, dict):
            answer = data.get("folder")

    if answer is None or not isinstance(answer, str):
        return None
    answer = answer.strip().strip("\"'`").strip()
    if answer.casefold() in NULL_ANSWERS:
        return None

    exact = [candidate for candidate in candidates if candidate.get("name") == answer]
    if len(exact) == 1:
        return exact[0]
    folded = [
        candidate
        for candidate in candidates
        if str(candidate.get("name") or "").casefold() == answer.casefold()
    ]
    if len(folded) == 1:
        return folded[0]
    return None


####################
# Dependencies
####################


@dataclass
class FolderAssignmentDeps:
    call_model: Callable[[dict], Awaitable[Any]]
    get_chat: Callable[[str, str], Any]
    get_folders: Callable[[str], list]
    get_folder: Callable[[str, str], Any]
    insert_folder: Callable[[str, str, dict], Any]
    count_folder_chats: Callable[[str, str], int]
    commit_assignment: Callable[..., Any]
    get_user_info: Callable[[str], dict]
    patch_user_info: Callable[[str, dict], Any]
    enabled: bool = True
    timeout: float = FOLDER_AUTO_ASSIGNMENT_TIMEOUT
    max_item_count: int = FOLDER_MAX_ITEM_COUNT


def build_default_deps(
    call_model: Callable[[dict], Awaitable[Any]], *, enabled: bool = True
) -> FolderAssignmentDeps:
    from open_webui.models.folders import Folders
    from open_webui.models.users import Users

    def get_user_info(user_id: str) -> dict:
        user = Users.get_user_by_id(user_id)
        info = getattr(user, "info", None) if user else None
        return info if isinstance(info, dict) else {}

    return FolderAssignmentDeps(
        call_model=call_model,
        get_chat=Chats.get_chat_by_id_and_user_id,
        get_folders=Folders.get_folders_by_user_id,
        get_folder=Folders.get_folder_by_id_and_user_id,
        insert_folder=lambda user_id, name, meta: Folders.insert_new_folder(
            user_id, name, None, meta
        ),
        count_folder_chats=Chats.count_chats_by_folder_id_and_user_id,
        commit_assignment=Chats.update_chat_folder_assignment_by_id_and_user_id,
        get_user_info=get_user_info,
        patch_user_info=Users.patch_user_info_by_id,
        enabled=enabled,
    )


@dataclass
class FolderAssignmentResult:
    status: str
    changed: bool = False
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    evaluations: Optional[int] = None
    detail: str = ""
    presets_created: int = 0


####################
# Default folders (once per user)
####################

_INIT_LOCKS: dict[str, asyncio.Lock] = {}


def _presets_initialized(info: Optional[dict]) -> bool:
    if not isinstance(info, dict):
        return False
    marker = info.get(USER_INFO_KEY)
    return isinstance(marker, dict) and bool(marker.get("presets_initialized_at"))


def preset_folder_meta(preset: dict) -> dict:
    return {
        "description": preset["description"],
        "auto_assignment": {"preset": preset["key"], "version": PRESETS_VERSION},
    }


async def ensure_default_folders(user_id: str, deps: FolderAssignmentDeps) -> int:
    """Create the preset folders once for a user who has none. Returns how
    many folders were created. Safe to call concurrently and repeatedly."""
    if _presets_initialized(deps.get_user_info(user_id)):
        return 0

    lock = _INIT_LOCKS.setdefault(user_id, asyncio.Lock())
    async with lock:
        if _presets_initialized(deps.get_user_info(user_id)):
            return 0

        created = 0
        if not (deps.get_folders(user_id) or []):
            existing = set()
            for preset in DEFAULT_FOLDER_PRESETS:
                key = preset["name"].casefold()
                if key in existing:
                    continue
                folder = deps.insert_folder(
                    user_id, preset["name"], preset_folder_meta(preset)
                )
                if folder is not None:
                    created += 1
                    existing.add(key)

        deps.patch_user_info(
            user_id,
            {
                USER_INFO_KEY: {
                    "presets_initialized_at": int(time.time()),
                    "presets_created": created,
                    "version": PRESETS_VERSION,
                }
            },
        )
        return created


####################
# Orchestration
####################


async def assign_chat_folder(
    *,
    chat_id: str,
    user_id: str,
    model_id: str,
    messages: list[dict],
    user_message_count: int,
    message_id: Optional[str],
    title: Optional[str],
    deps: FolderAssignmentDeps,
    require_external_task_model: bool = False,
) -> FolderAssignmentResult:
    """Evaluate one chat at one milestone. Never raises for model problems;
    every failure path records the attempt and leaves the chat where it is."""
    if not deps.enabled:
        return FolderAssignmentResult("disabled")

    chat = deps.get_chat(chat_id, user_id)
    if chat is None:
        return FolderAssignmentResult("missing")

    meta = _get(chat, "meta")
    current_folder_id = _get(chat, "folder_id")
    if not can_auto_assign_folder(current_folder_id, meta, user_message_count, message_id):
        return FolderAssignmentResult("ineligible")

    presets_created = 0
    try:
        presets_created = await ensure_default_folders(user_id, deps)
    except Exception as e:
        log.warning(f"folder auto assignment: preset initialisation failed: {e}")

    evaluations = get_evaluation_count(meta) + 1

    def record(
        status: str, choice: Optional[dict] = None, *, apply: bool = False, detail: str = ""
    ) -> FolderAssignmentResult:
        updated = deps.commit_assignment(
            chat_id,
            user_id,
            choice["id"] if choice else None,
            apply_folder=apply,
            evaluations=evaluations,
            last_user_message_count=user_message_count,
            last_message_id=message_id,
        )
        if updated is None:
            return FolderAssignmentResult(
                "skipped_manual", evaluations=evaluations, detail=status
            )
        return FolderAssignmentResult(
            status,
            changed=apply,
            folder_id=choice["id"] if choice else None,
            folder_name=choice["name"] if choice else None,
            evaluations=evaluations,
            detail=detail,
            presets_created=presets_created,
        )

    candidates = build_folder_candidates(deps.get_folders(user_id))
    if not candidates:
        return record("no_candidates")

    payload = {
        "model": model_id,
        "messages": messages,
        "chat_id": chat_id,
        "title": str(title or ""),
        "folders": [
            {"name": candidate["name"], "description": candidate["description"]}
            for candidate in candidates
        ],
    }
    if require_external_task_model:
        payload["require_external_task_model"] = True

    try:
        res = await asyncio.wait_for(deps.call_model(payload), timeout=deps.timeout)
    except asyncio.TimeoutError:
        return record("timeout")
    except Exception as e:
        return record("error", detail=str(e)[:200])

    text = parse_completion_text(res)
    choice = parse_folder_choice(text, candidates)
    if choice is None:
        return record("no_match" if text else "empty", detail=text[:120])

    if choice["id"] == current_folder_id:
        return record("unchanged", choice)

    # Re-validate right before writing: the folder may have been deleted or
    # nested while the model was thinking, and it must belong to this user.
    folder = deps.get_folder(choice["id"], user_id)
    if folder is None or _get(folder, "parent_id"):
        return record("candidate_gone", detail=choice["name"])

    if deps.max_item_count > 0:
        if deps.count_folder_chats(choice["id"], user_id) >= deps.max_item_count:
            return record("folder_full", detail=choice["name"])

    return record("assigned", choice, apply=True)

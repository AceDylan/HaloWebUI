"""Project delivery pipeline for 协作台: merge → push → wait CI → deploy → clean up branch.

A team working in a git repository works safely in its own worktree and branch (``halo/<slug>``).
When the team finishes, this module either runs automatically (when ``team["auto_deploy"]`` is
enabled and the team changed files without failing acceptance) or on demand (the 「一键推送部署」
button in the 变更 tab, or Telegram's 「🚀 推送部署」 button).

Project-specific deploy recipes come from ``~/.hermes/halo-teams-deploy.json`` (overrideable via
``HALO_TEAMS_DEPLOY_CONFIG``), falling back to built-in host recipes when the corresponding local
scripts/files exist, and finally to a safe merge → push → cleanup pipeline for any git repository.
Credentials in git/command output are always redacted.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import projects, vault_archive
from .common import TEAM_EVENT_TASK, append_event, board_conn, logger, now, read_team, redact, update_team

STALE_RUNNING = 3600
CI_POLL_INTERVAL = 15
DEFAULT_CI_TIMEOUT = 1800
DEFAULT_CMD_TIMEOUT = 600
DEFAULT_REVIEW_ROUNDS = 2
DEFAULT_REVIEW_TIMEOUT = 900
FIX_TIMEOUT = 1800
FIX_MAX_TURNS = 120
REVIEW_MAX_CHARS = 8000
DEFAULT_VERIFY_TIMEOUT = 120
LOG_MAX_CHARS = 6000
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.I)
_GH_REPO_RE = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$")

_inflight: set[str] = set()
_lock = threading.Lock()


def _config_path() -> Path:
    override = os.environ.get("HALO_TEAMS_DEPLOY_CONFIG")
    if override:
        return Path(override)
    hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return hermes_home / "halo-teams-deploy.json"


def _load_config() -> dict:
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _builtin_profiles() -> list[tuple[Callable[[str], bool], dict]]:
    """Built-in deploy profiles for repositories on this host (active only when their local
    deployment entry points exist; always overridable in ~/.hermes/halo-teams-deploy.json)."""
    return [
        (
            lambda top: os.path.basename(top) == "HaloWebUI"
            and os.path.isfile("/root/work/halo-hermes-autopilot/deploy.sh"),
            {
                "configured": True,
                "label": "HaloWebUI（GitHub CI 构建镜像 → 拉取部署）",
                "wait_ci": True,
                "ci_workflow": "Docker Image CI",
                "ci_timeout": 1800,
                "command": "sh /root/work/halo-hermes-autopilot/deploy.sh {short_sha}",
                "verify_command": "test \"$(docker inspect -f '{{.State.Health.Status}}' halowebui 2>/dev/null)\" = healthy && curl -sf http://127.0.0.1:3000/health >/dev/null && echo 'HaloWebUI 线上健康检查通过'",
                "timeout": 600,
                "cleanup": True,
                "restart_gateway_paths": ["integrations/hermes-plugin/halowebui-teams/"],
            },
        ),
        (
            lambda top: os.path.basename(top) == "AICheckIn"
            and os.path.isfile("/root/vps/vpsctl.py"),
            {
                "configured": True,
                "label": "AICheckIn / Hub（hk-vps 拉取并重建容器）",
                "wait_ci": False,
                "command": (
                    "python3 /root/vps/vpsctl.py run hk-vps "
                    "'cd /root/AICheckIn && git pull --ff-only && docker compose up -d --build "
                    "&& docker image prune -f'"
                ),
                "verify_command": "python3 /root/vps/vpsctl.py run hk-vps 'cd /root/AICheckIn && docker compose ps --status running -q | grep -q . && echo AICheckIn 线上运行正常'",
                "timeout": 600,
                "cleanup": True,
            },
        ),
        (
            lambda top: os.path.basename(top).lower() == "webobsidian"
            and os.path.isfile("/opt/webobsidian/docker-compose.yml"),
            {
                "configured": True,
                "label": "WebObsidian（GitHub CI 构建镜像 → 拉取部署）",
                "wait_ci": True,
                "ci_workflow": "Docker Image CI",
                "ci_timeout": 1800,
                "command": "cd /opt/webobsidian && docker compose pull -q && docker compose up -d && docker image prune -f",
                "verify_command": "cd /opt/webobsidian && docker compose ps --status running | grep -qi webobsidian && echo 'WebObsidian 线上运行正常'",
                "timeout": 600,
                "cleanup": True,
            },
        ),
        (
            lambda top: os.path.basename(top) == "cf-server-monitor"
            and os.path.isfile(os.path.join(top, ".github", "workflows", "deploy.yml")),
            {
                "configured": True,
                "label": "CF-Server-Monitor（触发 GitHub Actions 部署）",
                "gh_workflow": "deploy.yml",
                "wait_ci": True,
                "ci_workflow": "Deploy to Cloudflare Workers",
                "ci_timeout": 900,
                "cleanup": True,
            },
        ),
    ]


def _normalize_profile(raw: dict, default_label: str) -> dict:
    wait_ci = bool(raw.get("wait_ci") or raw.get("gh_workflow"))
    command = str(raw.get("command") or "").strip()
    verify_command = str(raw.get("verify_command") or "").strip()
    gh_workflow = str(raw.get("gh_workflow") or "").strip()
    configured = bool(raw.get("configured", bool(command or wait_ci or gh_workflow)))
    return {
        "configured": configured,
        "label": str(raw.get("label") or default_label).strip()[:120],
        "wait_ci": wait_ci,
        "gh_workflow": gh_workflow,
        "ci_workflow": str(raw.get("ci_workflow") or "").strip()[:120],
        "ci_timeout": max(60, min(int(raw.get("ci_timeout") or DEFAULT_CI_TIMEOUT), 7200)),
        "command": command,
        "verify_command": verify_command,
        "verify_timeout": max(15, min(int(raw.get("verify_timeout") or DEFAULT_VERIFY_TIMEOUT), 600)),
        "codex_review": bool(raw.get("codex_review", True)),
        "codex_review_rounds": max(1, min(int(raw.get("codex_review_rounds") or DEFAULT_REVIEW_ROUNDS), 3)),
        "timeout": max(30, min(int(raw.get("timeout") or DEFAULT_CMD_TIMEOUT), 3600)),
        "cleanup": bool(raw.get("cleanup", True)),
        "restart_gateway_paths": [
            str(p).strip() for p in (raw.get("restart_gateway_paths") or []) if str(p or "").strip()
        ],
    }


def profile_for(repo_path: Optional[str]) -> dict:
    """Resolve the deploy profile for *repo_path* (user config first, then built-ins, then push-only)."""
    top = projects.toplevel(repo_path) if repo_path else None
    real = os.path.realpath(top or repo_path) if (top or repo_path) else ""
    name = os.path.basename(real) if real else ""
    cfg = _load_config()
    by_proj = cfg.get("projects") if isinstance(cfg.get("projects"), dict) else {}
    for key in (real, repo_path or "", name):
        if key and isinstance(by_proj.get(key), dict):
            return _normalize_profile(by_proj[key], f"{name or '项目'} 自定义部署")
    if real:
        for matcher, spec in _builtin_profiles():
            try:
                if matcher(real):
                    return _normalize_profile(spec, spec.get("label") or name)
            except OSError:
                continue
    return _normalize_profile(
        {"configured": False, "label": "合并到主分支、推送 origin 并清理团队分支", "cleanup": True},
        "合并到主分支、推送 origin 并清理团队分支",
    )


def public_profile(repo_path: Optional[str]) -> dict:
    """Safe, UI-facing deploy profile summary (never exposes raw commands or secrets)."""
    p = profile_for(repo_path)
    return {
        "configured": bool(p["configured"]),
        "label": p["label"],
        "has_ci": bool(p["wait_ci"] or p["gh_workflow"]),
        "has_command": bool(p["command"]),
        "has_verify": bool(p["verify_command"]),
        "codex_review": bool(p["codex_review"]),
        "cleanup": bool(p["cleanup"]),
    }


def public_state(team: dict) -> Optional[dict]:
    """Compact deploy state for snapshots / stage rail (no full log)."""
    entry = (team.get("project") or {}).get("deploy")
    if not isinstance(entry, dict) or not entry.get("status"):
        return None
    keep = ("status", "by", "step", "steps", "started_at", "finished_at", "seconds",
            "sha", "base_branch", "ci_url", "ci_run_id", "cleanup", "codex_review", "error", "note", "profile_label")
    return {k: entry[k] for k in keep if entry.get(k) not in (None, "")}


def _clean_output(text: Any, limit: int = LOG_MAX_CHARS) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    cleaned = projects._URL_CREDENTIALS.sub(r"\1***@", str(text or ""))
    cleaned = redact(cleaned, limit + 500, one_line=False)
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def _initial_steps(profile: dict, cleanup: bool, *, codex_review: bool = False) -> list[dict]:
    steps: list[dict] = []
    if codex_review:
        rounds = int(profile.get("codex_review_rounds") or DEFAULT_REVIEW_ROUNDS)
        steps.append({"key": "review", "label": f"Codex 审查（最多 {rounds} 轮）", "status": "pending"})
    steps += [
        {"key": "merge", "label": "合并到主分支", "status": "pending"},
        {"key": "push", "label": "推送 origin", "status": "pending"},
    ]
    if profile["wait_ci"] or profile["gh_workflow"]:
        steps.append({"key": "ci", "label": "等待 CI 构建" if not profile["gh_workflow"] else "执行部署工作流",
                      "status": "pending"})
    if profile["command"]:
        steps.append({"key": "deploy", "label": "拉取并部署", "status": "pending"})
    if cleanup:
        steps.append({"key": "cleanup", "label": "清理分支", "status": "pending"})
    if profile.get("verify_command"):
        steps.append({"key": "verify", "label": "核实线上", "status": "pending"})
    return steps


def _update_deploy(slug: str, fn: Callable[[dict], None], *, defer_archive: bool = False) -> Optional[dict]:
    def apply(rec: dict) -> None:
        entry = rec.setdefault("project", {}).setdefault("deploy", {})
        previous = (entry.get("status"), entry.get("finished_at"))
        fn(entry)
        if (entry.get("status") in vault_archive.DEPLOY_TERMINAL
                and (entry.get("status"), entry.get("finished_at")) != previous):
            # A bridge tick can see this terminal state before _notify_finished runs.
            marker = vault_archive.pre_mark(rec, waiting=False, defer_archive=defer_archive)
            if marker:
                rec["conclusion"]["vault_archive"] = marker

    updated = update_team(slug, apply)
    return ((updated or {}).get("project") or {}).get("deploy")


def _set_step(slug: str, key: str, status: str, detail: str = "") -> None:
    stamp = now()

    def apply(d: dict) -> None:
        if status == "running":
            d["step"] = key
        for s in d.get("steps") or []:
            if s.get("key") == key:
                s["status"] = status
                s["at"] = stamp
                if detail:
                    s["detail"] = redact(detail, 240)
                break

    _update_deploy(slug, apply)


def _append_team_event(slug: str, action: str, **payload: Any) -> None:
    try:
        with board_conn(slug) as conn:
            append_event(conn, TEAM_EVENT_TASK, "halo_team", {"action": action, **payload})
    except Exception:  # noqa: BLE001 — timeline audit must never break deploy
        logger.debug("halowebui-teams: could not append %s event for %s", action, slug)


def _github_repo(repo_path: str) -> Optional[str]:
    res = projects.git(repo_path, "remote", "get-url", "origin", timeout=10)
    if res.returncode != 0:
        return None
    m = _GH_REPO_RE.search((res.stdout or "").strip())
    return m.group(1) if m else None


def _run_gh(args: list[str], *, cwd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
    return subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def _wait_for_ci(slug: str, repo_path: str, sha: str, base_branch: str, profile: dict) -> tuple[str, Optional[int]]:
    """Wait for the GitHub Actions run for *sha* (triggering ``gh_workflow`` first if configured)."""
    gh_repo = _github_repo(repo_path)
    if not gh_repo:
        raise projects.ProjectError(409, "origin 不是 GitHub 仓库，无法等待 GitHub Actions")
    if profile["gh_workflow"]:
        trig = _run_gh(["workflow", "run", profile["gh_workflow"], "-R", gh_repo, "--ref", base_branch],
                       cwd=repo_path, timeout=45)
        if trig.returncode != 0:
            raise projects.ProjectError(502, "触发 GitHub Actions 失败：" + _clean_output(trig.stderr or trig.stdout, 300))
        time.sleep(min(5, CI_POLL_INTERVAL))

    deadline = time.time() + int(profile["ci_timeout"])
    workflow_name = profile.get("ci_workflow") or ""
    run_url = ""
    run_id: Optional[int] = None
    no_run_deadline = time.time() + 180

    while time.time() < deadline:
        args = ["run", "list", "-R", gh_repo, "--limit", "20",
                "--json", "databaseId,headSha,status,conclusion,name,url"]
        if workflow_name:
            args += ["--workflow", workflow_name]
        res = _run_gh(args, cwd=repo_path, timeout=30)
        if res.returncode != 0:
            raise projects.ProjectError(502, "查询 GitHub CI 状态失败：" + _clean_output(res.stderr or res.stdout, 300))
        try:
            runs = json.loads(res.stdout or "[]")
        except ValueError:
            runs = []
        matched = None
        if isinstance(runs, list) and runs:
            sha_runs = [r for r in runs if str(r.get("headSha") or "").startswith(sha[:8])]
            if workflow_name:
                matched = next((r for r in sha_runs if r.get("name") == workflow_name), None)
            if matched is None and sha_runs:
                matched = sha_runs[0]
        if matched:
            run_url = str(matched.get("url") or "")
            run_id = matched.get("databaseId")
            status = str(matched.get("status") or "")
            conclusion = str(matched.get("conclusion") or "")
            _update_deploy(slug, lambda d: d.update({"ci_url": run_url, "ci_run_id": run_id}))
            if status == "completed":
                if conclusion == "success":
                    return run_url, run_id
                raise projects.ProjectError(502, f"GitHub CI 未通过（{conclusion or 'failed'}）" + (f"：{run_url}" if run_url else ""))
            _set_step(slug, "ci", "running", f"CI 运行中（{status}）")
        elif time.time() > no_run_deadline:
            raise projects.ProjectError(504, f"推送后超过 3 分钟仍未发现 {sha[:8]} 的 GitHub Actions 运行")
        time.sleep(CI_POLL_INTERVAL)
    raise projects.ProjectError(504, f"等待 GitHub CI 超时（超过 {int(profile['ci_timeout'] // 60)} 分钟）")


def _append_log(slug: str, section: str) -> None:
    if not section:
        return

    def apply(d: dict) -> None:
        prev = str(d.get("log") or "")
        combined = (prev + "\n\n" + section).strip() if prev else section.strip()
        d["log"] = _clean_output(combined)

    _update_deploy(slug, apply)


def _run_shell_step(slug: str, repo_path: str, cmd_template: str, sha: str, base_branch: str, branch: str,
                    timeout: int, label: str) -> str:
    """Execute a configured shell command (deploy or online verify) and append redacted output."""
    if sha and not _SHA_RE.match(sha):
        raise projects.ProjectError(400, "提交 SHA 格式异常")
    short_sha = sha[:8] if sha else ""
    subs = {
        "sha": shlex.quote(sha),
        "short_sha": shlex.quote(short_sha),
        "base_branch": shlex.quote(base_branch),
        "branch": shlex.quote(branch),
        "repo": shlex.quote(repo_path),
    }
    cmd = cmd_template
    for key, val in subs.items():
        cmd = cmd.replace("{" + key + "}", val)
    env = {
        **os.environ,
        "HALO_DEPLOY_SHA": sha,
        "HALO_DEPLOY_SHORT_SHA": short_sha,
        "HALO_DEPLOY_BASE_BRANCH": base_branch,
        "HALO_DEPLOY_BRANCH": branch,
        "HALO_DEPLOY_REPO": repo_path,
    }
    try:
        proc = subprocess.run(
            # Not a login shell: its greeting would fill the log and pass for the failure's last line.
            ["bash", "-c", cmd],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=int(timeout),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired carries bytes even in text mode.
        out = "\n".join(part for part in (_clean_output(exc.stdout or ""), _clean_output(exc.stderr or "")) if part)
        _append_log(slug, f"=== {label}（超时）===\n{out}")
        raise projects.ProjectError(504, f"{label}超时（超过 {timeout} 秒）") from None
    output = _clean_output((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))
    _append_log(slug, f"=== {label} ===\n{output}" if output else "")
    if proc.returncode != 0:
        tail = output.strip().splitlines()[-1] if output.strip() else f"exit {proc.returncode}"
        raise projects.ProjectError(502, f"{label}失败（exit {proc.returncode}）：{tail[:240]}")
    return output


def _run_deploy_command(slug: str, repo_path: str, sha: str, base_branch: str, branch: str, profile: dict) -> str:
    return _run_shell_step(slug, repo_path, profile["command"], sha, base_branch, branch,
                           int(profile["timeout"]), "部署命令")


def _run_verify_command(slug: str, repo_path: str, sha: str, base_branch: str, branch: str, profile: dict) -> str:
    return _run_shell_step(slug, repo_path, profile["verify_command"], sha, base_branch, branch,
                           int(profile.get("verify_timeout") or DEFAULT_VERIFY_TIMEOUT), "线上核实")


def _run_runner(spec: Any, argv: list[str], workspace: str, timeout: int) -> subprocess.CompletedProcess:
    """One foreground runner run inside the pipeline: bounded by its own ``--timeout`` (so it never
    goes on editing after we gave up), no automatic continuation, no notice of its own."""
    env = {**os.environ, "RUNNER_SUPPRESS_NOTIFY": "1", "RECLAUDE_AUTO_CONTINUE": "0"}
    try:
        return subprocess.run([*argv, "--timeout", str(timeout), "--no-vault-archive"], cwd=workspace,
                              capture_output=True, text=True, timeout=timeout + 120, env=env)
    except subprocess.TimeoutExpired:
        raise projects.ProjectError(504, f"{spec.label} 超时（超过 {timeout // 60} 分钟）") from None


def _runner_files(spec: Any, run_id: str) -> tuple[dict, str]:
    run_dir = spec.runs_root / run_id
    data: dict = {}
    text = ""
    try:
        loaded = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        pass
    try:
        text = (run_dir / "result.md").read_text(encoding="utf-8")
    except OSError:
        pass
    return data, text


def _task_file(name: str, text: str) -> Path:
    from . import reclaude

    reclaude.TASK_DIR.mkdir(parents=True, exist_ok=True)
    path = reclaude.TASK_DIR / name
    path.write_text(text, encoding="utf-8")
    return path


def _run_codex_once(workspace: str, base_branch: str, round_num: int, max_rounds: int, *,
                    goal: str = "", previous: str = "") -> tuple[str, str]:
    """One read-only ``codex-run.sh run --audit`` (Codex's own configured model). Returns
    ``(verdict, report)``; the verdict is the one the runner parsed (PASS | FAIL | BLOCKED), never
    guessed from the text. ``previous``: the report of the round before, whose findings were fixed."""
    from . import reclaude, runners

    spec = runners.BY_NAME["codex"]
    run_id = reclaude.new_run_id()
    task_file = _task_file(
        f"deploy-review-r{round_num}-{run_id}.md",
        f"合并前代码审查（第 {round_num}/{max_rounds} 轮）：只读审查当前目录（git worktree）里团队分支相对 `{base_branch}` 的全部改动。\n"
        f"- 用 `git log {base_branch}..HEAD` 和 `git diff {base_branch}...HEAD` 看改动，需要时读相关代码。\n"
        "- 只有合并后会真实出问题的才判 FAIL：没做到目标要求的行为、正常使用会出错或崩溃、安全 / 权限隐患、丢数据、"
        "破坏已有功能。目标没有要求的假设输入、可选的加固、补测试、文档措辞、风格偏好、改动之前就有的问题都不判 FAIL，"
        "写成「建议」即可。\n"
        "- 一次把所有必须修的问题都列出来，不要留到下一轮。\n"
        "- 这是代码审查：只读环境里跑不了测试、连不上线上服务都不算缺少证据，按代码判断；"
        "团队的实测结果可以看 `.halo/` 下的回执（不一定有，没有不影响结论）。\n"
        "- 有必须修的问题就判 FAIL，逐条写出文件、行号、问题和改法；没有就判 PASS。\n"
        + (f"\n这次要达成的目标：\n{goal[:3000]}\n" if goal else "")
        + (f"\n上一轮的审查意见（之后已经修过）。这一轮先核对它们是否真的修好，再看修复有没有引入新问题；"
           f"上一轮看过而没提的代码，只有确实漏掉了会真实出问题的缺陷才判 FAIL：\n{previous}\n" if previous else ""),
    )
    proc = _run_runner(spec, [spec.script_path, "run", "--audit", "--cwd", workspace, "--task-file", str(task_file),
                              "--run-id", run_id], workspace, DEFAULT_REVIEW_TIMEOUT)
    data, text = _runner_files(spec, run_id)
    verdict = str(data.get("review_verdict") or "").upper()
    if verdict not in ("PASS", "FAIL"):
        verdict = "BLOCKED"
    text = text or str(data.get("result") or "") or f"{proc.stdout or ''}\n{proc.stderr or ''}"
    return verdict, _clean_output(text, REVIEW_MAX_CHARS).strip()


def _pick_claude_fixer(team: dict) -> tuple[Optional[str], str]:
    """Select the Claude runner to fix Codex review findings: respects explicit user pref
    (no auto-fallback) or walks the Claude family order."""
    from . import runners

    prefs = team.get("runner_prefs") if isinstance(team.get("runner_prefs"), dict) else {}
    explicit = str(prefs.get("claude") or "").strip().lower()
    if explicit and explicit in runners.BY_NAME:
        picked = runners.select(explicit, auto=False)
        if picked["executor"]:
            return picked["executor"], ""
        return None, f"你指定的 {explicit} 不可用（不自动顺延）：{runners.fallback_reason(picked)}"
    picked = runners.select(runners.kind_default("code"), auto=True)
    if picked["executor"]:
        return picked["executor"], ""
    return None, f"Claude 家族均不可用：{runners.fallback_reason(picked)}"


def _run_claude_fix(runner_name: str, workspace: str, review_text: str, round_num: int) -> str:
    from . import reclaude, runners

    spec = runners.BY_NAME[runner_name]
    run_id = reclaude.new_run_id()
    task_file = _task_file(
        f"deploy-fix-r{round_num}-{run_id}.md",
        f"Codex 第 {round_num} 轮合并前审查未通过，请按下面的审查意见修复当前分支的代码并重新运行相关测试：\n\n"
        f"{review_text}\n\n"
        "要求：只修复审查指出的问题；不要 git push、不要合并主分支、不要部署，也不要再调用其他代理或审查工具。\n",
    )
    proc = _run_runner(spec, [spec.script_path, "run", "--cwd", workspace, "--task-file", str(task_file),
                              "--run-id", run_id, "--max-turns", str(FIX_MAX_TURNS)], workspace, FIX_TIMEOUT)
    _data, text = _runner_files(spec, run_id)
    if proc.returncode != 0:
        why = "它有问题要你回答" if proc.returncode == 2 else f"exit {proc.returncode}"
        raise projects.ProjectError(502, f"{runner_name} 没能修完审查问题（{why}），已暂停合并")
    # On the team branch, so the next round reviews it.
    projects.commit_all(workspace, f"[Codex 审查修复 · 第 {round_num} 轮] {runner_name}")
    return _clean_output(text or proc.stdout or "", 1600)


def _run_codex_review(slug: str, team: dict, workspace: str, base_branch: str, profile: dict) -> str:
    """Up to ``codex_review_rounds`` (default 2) rounds of Codex review + Claude fix."""
    from . import runners
    from .workflow import user_goal

    max_rounds = int(profile.get("codex_review_rounds") or DEFAULT_REVIEW_ROUNDS)
    codex_avail = (runners.check(["codex"]).get("codex") or {})
    if not codex_avail.get("available"):
        raise projects.ProjectError(409, f"Codex 不可用，已暂停合并等待你处理：{codex_avail.get('reason') or '未知原因'}")
    projects.commit_all(workspace, f"[收尾] {team.get('title') or ''}")  # the review reads the committed diff

    goal = user_goal(team.get("goal") or "")
    text = ""
    for round_num in range(1, max_rounds + 1):
        _set_step(slug, "review", "running", f"第 {round_num}/{max_rounds} 轮 Codex 审查中")
        verdict, text = _run_codex_once(workspace, base_branch, round_num, max_rounds, goal=goal, previous=text)
        _append_log(slug, f"=== Codex 审查第 {round_num} 轮（{verdict}）===\n{text}")
        if verdict == "PASS":
            return f"第 {round_num} 轮审查通过"
        if verdict == "FAIL" and round_num < max_rounds:
            fixer, err = _pick_claude_fixer(team)
            if not fixer:
                raise projects.ProjectError(409, f"Codex 第 {round_num} 轮审查未通过，但无法自动修复（{err}）；已暂停合并")
            _set_step(slug, "review", "running", f"第 {round_num} 轮发现问题，正由 {fixer} 修复")
            fix_out = _run_claude_fix(fixer, workspace, text, round_num)
            _append_log(slug, f"=== {fixer} 自动修复（第 {round_num} 轮）===\n{fix_out}")
            continue
        if verdict == "BLOCKED":
            tail = text.splitlines()[-1][:160] if text else "没有输出"
            raise projects.ProjectError(
                409, f"Codex 第 {round_num}/{max_rounds} 轮审查没有给出结论，已暂停自动合并（{tail}）；请查看部署日志后处理")
        raise projects.ProjectError(
            409, f"Codex 第 {round_num}/{max_rounds} 轮审查未通过，已暂停自动合并；请查看部署日志后处理")
    raise projects.ProjectError(409, "Codex 审查未通过，已暂停自动合并")


def _schedule_gateway_restart() -> bool:
    """Detached graceful reload of hermes-gateway (SIGUSR1 drain -> systemd restart) so the
    current response and Telegram notice finish first."""
    if os.environ.get("HALO_TEAMS_NO_GATEWAY_RESTART") == "1":
        return False
    try:
        subprocess.Popen(
            ["bash", "-lc", "sleep 3 && systemctl --user reload hermes-gateway"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        logger.warning("halowebui-teams: failed to schedule gateway restart", exc_info=True)
        return False
    return True


def _notify_finished(slug: str, *, defer_archive: bool = False) -> None:
    from . import notify

    try:
        if not (defer_archive and vault_archive.defer_to_reload(slug)):
            vault_archive.run_bounded(slug)
    except Exception as exc:
        logger.warning("halowebui-teams: archive before deploy notice failed for %s (%s)", slug, type(exc).__name__)
    try:
        fresh = read_team(slug)
        if fresh:
            notify.deploy_notice(slug, fresh)
    except Exception:
        logger.warning("halowebui-teams: deploy notice failed for %s", slug, exc_info=True)


def _run_ship(slug: str, profile: dict, by: str, cleanup: bool, codex_review: bool = False) -> None:
    started = now()
    need_gateway_restart = False
    defer_archive = False
    try:
        team = read_team(slug)
        if not team:
            return
        project = team.get("project") or {}
        repo = project.get("path") or ""
        branch = project.get("branch") or ""
        base_branch = project.get("base_branch") or ""
        workspace = team.get("workspace") or ""

        # 0. Codex review loop (up to 2 rounds + Claude fix, optional)
        if codex_review:
            before_review = projects.changed_paths(team) or []
            _update_deploy(slug, lambda d: d.update({"touched_files": before_review[:80]}))
            info_pre = projects.changes(team)
            if info_pre.get("merged"):
                _set_step(slug, "review", "done", "分支已合并，跳过审查")
            else:
                review_detail = _run_codex_review(slug, team, workspace, base_branch, profile)
                _set_step(slug, "review", "done", review_detail)
                team = read_team(slug) or team

        # Record touched paths before merge/cleanup so we know if plugin files changed.
        touched = projects.changed_paths(team) or []
        _update_deploy(slug, lambda d: d.update({"touched_files": touched[:80]}))

        # 1. Merge
        _set_step(slug, "merge", "running", f"合并 {branch} 到 {base_branch}")
        info = projects.changes(team)
        if info.get("merged"):
            sha = project.get("merged_sha") or projects.git(repo, "rev-parse", base_branch, timeout=10).stdout.strip()
            _set_step(slug, "merge", "done", f"已合并（{sha[:8]}）")
        else:
            merged = projects.merge(slug, team)
            sha = merged.get("sha") or ""
            _set_step(slug, "merge", "done", f"{merged.get('how') or 'merged'} · {sha[:8]}")
        _update_deploy(slug, lambda d: d.update({"sha": sha}))

        # 2. Push
        team = read_team(slug) or team
        _set_step(slug, "push", "running", f"推送 {base_branch} 到 origin")
        pushed = (team.get("project") or {}).get("pushed") or {}
        if pushed.get("base"):
            _set_step(slug, "push", "done", f"{base_branch} 已推送")
        else:
            projects.push(slug, team, "base")
            _set_step(slug, "push", "done", f"已推送 {base_branch}")

        # 3. CI (optional)
        if profile["wait_ci"] or profile["gh_workflow"]:
            _set_step(slug, "ci", "running", "等待 GitHub Actions 完成")
            ci_url, ci_run_id = _wait_for_ci(slug, repo, sha, base_branch, profile)
            _set_step(slug, "ci", "done", f"CI 通过" + (f" (#{ci_run_id})" if ci_run_id else ""))
            if ci_url:
                _update_deploy(slug, lambda d: d.update({"ci_url": ci_url, "ci_run_id": ci_run_id}))

        # 4. Deploy command (optional)
        if profile["command"]:
            _set_step(slug, "deploy", "running", "正在执行部署命令")
            _run_deploy_command(slug, repo, sha, base_branch, branch, profile)
            _set_step(slug, "deploy", "done", "部署完成")

        # The new plugin is live on disk from here, whatever the remaining steps say.
        need_gateway_restart = any(p.startswith(pref) for pref in profile.get("restart_gateway_paths") or [] for p in touched)
        defer_archive = need_gateway_restart and os.environ.get("HALO_TEAMS_NO_GATEWAY_RESTART") != "1"

        # 5. Cleanup worktree & branch (optional)
        if cleanup:
            team = read_team(slug) or team
            _set_step(slug, "cleanup", "running", f"清理 {branch} 分支与 worktree")
            if (team.get("project") or {}).get("discarded_at"):
                _set_step(slug, "cleanup", "done", "分支已清理")
            else:
                projects.discard(slug, team, auto=False, shipped=True)
                _set_step(slug, "cleanup", "done", "已清理工作区与分支")

        # 6. Online verification (optional)
        if profile.get("verify_command"):
            _set_step(slug, "verify", "running", "正在核实线上状态")
            _run_verify_command(slug, repo, sha, base_branch, branch, profile)
            _set_step(slug, "verify", "done", "线上核实通过")

        finished = now()
        note = "检测到协作台插件改动，将在数秒后平滑重启 Hermes 网关加载新版插件" if defer_archive else ""
        _update_deploy(slug, lambda d: d.update({
            "status": "succeeded",
            "step": "done",
            "finished_at": finished,
            "seconds": max(1, finished - started),
            "error": "",
            **({"note": note} if note else {}),
        }), defer_archive=defer_archive)
        _append_team_event(slug, "deploy_succeeded", sha=sha[:10], by=by, cleanup=cleanup)
        logger.info("halowebui-teams: %s shipped %s (%s)", slug, sha[:10], profile["label"])
    except projects.ProjectError as exc:
        _fail_ship(slug, started, exc.message, by, defer_archive=defer_archive)
    except Exception as exc:  # noqa: BLE001
        logger.warning("halowebui-teams: ship failed for %s", slug, exc_info=True)
        _fail_ship(slug, started, f"发布异常：{type(exc).__name__}: {redact(exc, 240)}", by, defer_archive=defer_archive)
    finally:
        try:
            _mark_attempt(slug)
            _notify_finished(slug, defer_archive=defer_archive)
            if (need_gateway_restart and not _schedule_gateway_restart() and defer_archive
                    and vault_archive.release_deferred(slug)):
                vault_archive.run_bounded(slug)
        finally:
            with _lock:
                _inflight.discard(slug)


def _attempt_key(team: dict) -> str:
    """What an automatic ship would ship: the round and the branch's head."""
    head = projects.git(team["workspace"], "rev-parse", "HEAD", timeout=10).stdout.strip()
    return f"{int(team.get('round') or 0)}:{head[:12]}"


def _mark_attempt(slug: str) -> None:
    """This head has been through the pipeline (its own commits — review fixes, leftovers — included):
    auto-deploy waits for new work instead of shipping the same thing again."""
    team = read_team(slug) or {}
    if (team.get("project") or {}).get("discarded_at") or not os.path.isdir(team.get("workspace") or ""):
        return
    try:
        key = _attempt_key(team)
    except (OSError, subprocess.SubprocessError):
        return
    _update_deploy(slug, lambda d: d.update({"auto_key": key}))


def _fail_ship(slug: str, started: int, message: str, by: str, *, defer_archive: bool = False) -> None:
    finished = now()
    current_step = ""

    def apply(d: dict) -> None:
        nonlocal current_step
        current_step = str(d.get("step") or "")
        for s in d.get("steps") or []:
            if s.get("status") == "running":
                s["status"] = "failed"
                s["at"] = finished
                s["detail"] = redact(message, 240)
        d.update({
            "status": "failed",
            "finished_at": finished,
            "seconds": max(1, finished - started),
            "error": redact(message, 600),
        })

    _update_deploy(slug, apply, defer_archive=defer_archive)
    _append_team_event(slug, "deploy_failed", step=current_step, error=redact(message, 200), by=by)
    logger.warning("halowebui-teams: ship of %s failed at %s: %s", slug, current_step, message)


def start(slug: str, *, by: str = "user", cleanup: Optional[bool] = None, auto_key: str = "",
          codex_review: Optional[bool] = None) -> dict:
    """Start the [Codex review] → merge → push → CI → deploy → cleanup → [verify] pipeline."""
    team = read_team(slug)
    if not team:
        raise projects.ProjectError(404, "team not found")
    project = team.get("project") or {}
    repo, branch, base_branch = project.get("path"), project.get("branch"), project.get("base_branch")
    if not repo or not branch:
        raise projects.ProjectError(404, "这个团队不是在项目里做的")
    if not base_branch:
        raise projects.ProjectError(409, "开始时项目处于分离 HEAD，无法自动合并和推送主分支")
    if project.get("discarded_at") and not project.get("merged_at"):
        raise projects.ProjectError(409, "团队分支已删除，无法推送部署")
    profile = profile_for(repo)
    do_cleanup = profile["cleanup"] if cleanup is None else bool(cleanup)
    if codex_review is None:
        from .workflow import skips_codex_review

        do_review = profile["codex_review"] and not skips_codex_review(team.get("workflow"))
    else:
        do_review = bool(codex_review)
    if do_cleanup and (team.get("conclusion") or {}).get("status") == "generating":
        raise projects.ProjectError(409, "负责人正在写结论（要读工作区文件），写完后再推送部署并清理")

    with _lock:
        current = project.get("deploy") if isinstance(project.get("deploy"), dict) else {}
        if slug in _inflight or (current.get("status") == "running" and now() - int(current.get("started_at") or 0) < STALE_RUNNING):
            return dict(current)
        _inflight.add(slug)

    entry = {
        "status": "running",
        "by": by,
        "step": "review" if do_review else "merge",
        "steps": _initial_steps(profile, do_cleanup, codex_review=do_review),
        "started_at": now(),
        "finished_at": None,
        "seconds": None,
        "sha": project.get("merged_sha") or "",
        "base_branch": base_branch,
        "cleanup": do_cleanup,
        "codex_review": do_review,
        "ci_url": "",
        "ci_run_id": None,
        "error": "",
        "note": "",
        "log": "",
        "profile_label": profile["label"],
        **({"auto_key": auto_key} if auto_key else {}),
    }
    _update_deploy(slug, lambda d: (d.clear(), d.update(entry)))
    _append_team_event(slug, "deploy_started", by=by, profile=profile["label"])
    thread = threading.Thread(
        target=_run_ship,
        args=(slug, profile, by, do_cleanup, do_review),
        name=f"halo-deploy-{slug[-8:]}",
        daemon=True,
    )
    thread.start()
    return entry


def tick_board(slug: str, team: dict) -> bool:
    """Bridge loop hook: automatically ship a completed project team when ``auto_deploy`` is on."""
    if team.get("state") != "completed" or not team.get("auto_deploy"):
        return False
    project = team.get("project") or {}
    workspace = team.get("workspace") or ""
    if not project.get("branch") or project.get("discarded_at") or not os.path.isdir(workspace):
        return False
    entry = team.get("conclusion") or {}
    if entry.get("status") not in ("ready", "failed"):
        return False
    acceptance = entry.get("acceptance") or {}
    if acceptance.get("status") == "checking":
        return False
    if (entry.get("illustration") or {}).get("status") == "generating":
        return False

    auto_key = _attempt_key(team)
    existing = project.get("deploy") if isinstance(project.get("deploy"), dict) else {}
    if existing.get("status") == "running" or existing.get("auto_key") == auto_key:
        return False

    # Nothing changed at all? clean_if_empty handles it; never deploy an empty diff.
    info = projects.changes(team)
    if not info.get("commits") and not info.get("pending"):
        return False

    # Acceptance gate: if the lead explicitly judged the goal unmet, pause auto-deploy safely.
    if acceptance.get("status") == "ready" and acceptance.get("verdict") == "unmet":
        profile = profile_for(project.get("path"))
        reason = "负责人验收未通过（目标未达成），已跳过自动推送部署；检查后可在「变更」里手动一键推送部署"
        touched = projects.changed_paths(team) or []
        _update_deploy(slug, lambda d: (d.clear(), d.update({
            "status": "skipped",
            "by": "auto",
            "step": "skipped",
            "steps": _initial_steps(profile, profile["cleanup"]),
            "started_at": now(),
            "finished_at": now(),
            "base_branch": project.get("base_branch") or "",
            "cleanup": profile["cleanup"],
            "error": reason,
            "profile_label": profile["label"],
            "auto_key": auto_key,
            "touched_files": touched[:80],
        })))
        if vault_archive.is_eligible(team) and os.environ.get("HALO_TEAMS_VAULT_ARCHIVE_SYNC") != "1":
            threading.Thread(target=_notify_finished, args=(slug,), name=f"halo-deploy-notice-{slug[-8:]}",
                             daemon=True).start()
        else:
            _notify_finished(slug)
        return False

    try:
        start(slug, by="auto", auto_key=auto_key)
        return True
    except projects.ProjectError as exc:
        logger.info("halowebui-teams: auto-deploy skipped for %s: %s", slug, exc.message)
        return False

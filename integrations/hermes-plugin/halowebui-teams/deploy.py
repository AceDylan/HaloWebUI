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

from . import projects
from .common import TEAM_EVENT_TASK, append_event, board_conn, logger, now, read_team, redact, update_team

STALE_RUNNING = 3600
CI_POLL_INTERVAL = 15
DEFAULT_CI_TIMEOUT = 1800
DEFAULT_CMD_TIMEOUT = 600
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
        "cleanup": bool(p["cleanup"]),
    }


def public_state(team: dict) -> Optional[dict]:
    """Compact deploy state for snapshots / stage rail (no full log)."""
    entry = (team.get("project") or {}).get("deploy")
    if not isinstance(entry, dict) or not entry.get("status"):
        return None
    keep = ("status", "by", "step", "steps", "started_at", "finished_at", "seconds",
            "sha", "base_branch", "ci_url", "ci_run_id", "cleanup", "error", "note", "profile_label")
    return {k: entry[k] for k in keep if entry.get(k) not in (None, "")}


def _clean_output(text: Any, limit: int = LOG_MAX_CHARS) -> str:
    cleaned = projects._URL_CREDENTIALS.sub(r"\1***@", str(text or ""))
    cleaned = redact(cleaned, limit + 500, one_line=False)
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def _initial_steps(profile: dict, cleanup: bool) -> list[dict]:
    steps = [
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
    return steps


def _update_deploy(slug: str, fn: Callable[[dict], None]) -> Optional[dict]:
    def apply(rec: dict) -> None:
        entry = rec.setdefault("project", {}).setdefault("deploy", {})
        fn(entry)

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
        res = _run_gh(
            ["run", "list", "-R", gh_repo, "--commit", sha, "--limit", "10",
             "--json", "databaseId,status,conclusion,name,url,workflowName"],
            cwd=repo_path, timeout=30,
        )
        if res.returncode != 0:
            raise projects.ProjectError(502, "查询 GitHub CI 状态失败：" + _clean_output(res.stderr or res.stdout, 300))
        try:
            runs = json.loads(res.stdout or "[]")
        except ValueError:
            runs = []
        matched = None
        if isinstance(runs, list) and runs:
            if workflow_name:
                matched = next((r for r in runs if r.get("workflowName") == workflow_name or r.get("name") == workflow_name), None)
            if matched is None:
                matched = runs[0]
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


def _run_deploy_command(slug: str, repo_path: str, sha: str, base_branch: str, branch: str, profile: dict) -> str:
    """Execute the host-configured deploy command safely and capture redacted output."""
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
    cmd = profile["command"]
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
            ["bash", "-lc", cmd],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=int(profile["timeout"]),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        out = _clean_output((exc.stdout or "") + "\n" + (exc.stderr or ""))
        _update_deploy(slug, lambda d: d.update({"log": out}))
        raise projects.ProjectError(504, f"部署命令超时（超过 {profile['timeout']} 秒）") from None
    output = _clean_output((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))
    _update_deploy(slug, lambda d: d.update({"log": output}))
    if proc.returncode != 0:
        tail = output.strip().splitlines()[-1] if output.strip() else f"exit {proc.returncode}"
        raise projects.ProjectError(502, f"部署命令失败（exit {proc.returncode}）：{tail[:240]}")
    return output


def _schedule_gateway_restart() -> None:
    """Detached restart of hermes-gateway so the current response and Telegram notice finish first."""
    if os.environ.get("HALO_TEAMS_NO_GATEWAY_RESTART") == "1":
        return
    try:
        subprocess.Popen(
            ["bash", "-lc", "sleep 3 && systemctl --user restart hermes-gateway"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        logger.warning("halowebui-teams: failed to schedule gateway restart", exc_info=True)


def _run_ship(slug: str, profile: dict, by: str, cleanup: bool) -> None:
    started = now()
    need_gateway_restart = False
    try:
        team = read_team(slug)
        if not team:
            return
        project = team.get("project") or {}
        repo = project.get("path") or ""
        branch = project.get("branch") or ""
        base_branch = project.get("base_branch") or ""

        # Record touched paths before merge/cleanup so we know if plugin files changed.
        touched = projects.changed_paths(team) or []

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

        # 5. Cleanup worktree & branch (optional)
        if cleanup:
            team = read_team(slug) or team
            _set_step(slug, "cleanup", "running", f"清理 {branch} 分支与 worktree")
            if (team.get("project") or {}).get("discarded_at"):
                _set_step(slug, "cleanup", "done", "分支已清理")
            else:
                projects.discard(slug, team, auto=False, shipped=True)
                _set_step(slug, "cleanup", "done", "已清理工作区与分支")

        restart_prefixes = profile.get("restart_gateway_paths") or []
        if restart_prefixes and any(any(p.startswith(pref) for pref in restart_prefixes) for p in touched):
            need_gateway_restart = True

        finished = now()
        note = "检测到协作台插件改动，将在数秒后平滑重启 Hermes 网关加载新版插件" if need_gateway_restart else ""
        _update_deploy(slug, lambda d: d.update({
            "status": "succeeded",
            "step": "done",
            "finished_at": finished,
            "seconds": max(1, finished - started),
            "error": "",
            **({"note": note} if note else {}),
        }))
        _append_team_event(slug, "deploy_succeeded", sha=sha[:10], by=by, cleanup=cleanup)
        logger.info("halowebui-teams: %s shipped %s (%s)", slug, sha[:10], profile["label"])
    except projects.ProjectError as exc:
        _fail_ship(slug, started, exc.message, by)
    except Exception as exc:  # noqa: BLE001
        logger.warning("halowebui-teams: ship failed for %s", slug, exc_info=True)
        _fail_ship(slug, started, f"发布异常：{type(exc).__name__}: {redact(exc, 240)}", by)
    finally:
        with _lock:
            _inflight.discard(slug)
        try:
            from . import notify

            fresh = read_team(slug)
            if fresh:
                notify.deploy_notice(slug, fresh)
        except Exception:  # noqa: BLE001
            logger.warning("halowebui-teams: deploy Telegram notice failed for %s", slug, exc_info=True)
        if need_gateway_restart:
            _schedule_gateway_restart()


def _fail_ship(slug: str, started: int, message: str, by: str) -> None:
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

    _update_deploy(slug, apply)
    _append_team_event(slug, "deploy_failed", step=current_step, error=redact(message, 200), by=by)
    logger.warning("halowebui-teams: ship of %s failed at %s: %s", slug, current_step, message)


def start(slug: str, *, by: str = "user", cleanup: Optional[bool] = None, auto_key: str = "") -> dict:
    """Start the merge → push → CI → deploy → cleanup pipeline in the background."""
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
        "step": "merge",
        "steps": _initial_steps(profile, do_cleanup),
        "started_at": now(),
        "finished_at": None,
        "seconds": None,
        "sha": project.get("merged_sha") or "",
        "base_branch": base_branch,
        "ci_url": "",
        "ci_run_id": None,
        "cleanup": do_cleanup,
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
        args=(slug, profile, by, do_cleanup),
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

    head = projects.git(workspace, "rev-parse", "HEAD", timeout=10).stdout.strip()
    auto_key = f"{int(team.get('round') or 0)}:{head[:12]}"
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
        })))
        try:
            from . import notify

            fresh = read_team(slug)
            if fresh:
                notify.deploy_notice(slug, fresh)
        except Exception:  # noqa: BLE001
            pass
        return False

    try:
        start(slug, by="auto", auto_key=auto_key)
        return True
    except projects.ProjectError as exc:
        logger.info("halowebui-teams: auto-deploy skipped for %s: %s", slug, exc.message)
        return False

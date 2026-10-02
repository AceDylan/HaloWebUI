"""Teams that work on a real project: the team's own branch in a git worktree.

A project is a git repository on this machine (its top level; never the home directory or the
Hermes home). At approval the team gets the branch ``halo/<board>`` from the repository's current
HEAD, checked out as a linked worktree at the team's usual workspace path: members (Hermes and
runners alike) work there and the user's own checkout is never touched. Every finished task is
committed on that branch (``[T2 · member] title``); the 变更 view lists commits and files. Merging
into the base branch, pushing, and throwing the branch away are explicit user actions — nothing
here pushes on its own.

Parallel members share the worktree (the plan gives them different files), so a commit holds
whatever the worktree had when its task finished: the overall diff is exact, the per-task split
is best effort.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from .common import logger, now

GIT_TIMEOUT = 60
PUSH_TIMEOUT = 180
DIFF_MAX = 200_000
EXCLUDE = ":(exclude).halo"
# Never committed or shown even in a repository that does not ignore them: what running tests or
# installing packages leaves behind (members run tests in the worktree).
JUNK = (EXCLUDE, ":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.py[co]", ":(exclude,glob)**/.pytest_cache/**",
        ":(exclude,glob)**/node_modules/**", ":(exclude,glob)**/.DS_Store")
AUTHOR = ("Halo Team", "halo-team@localhost")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")


_URL_CREDENTIALS = re.compile(r"(\w+://)[^/\s@]+@")


class ProjectError(Exception):
    def __init__(self, status: int, message: str):
        # git output can carry a remote URL with credentials in it: never pass those on.
        from .common import redact

        message = redact(_URL_CREDENTIALS.sub(r"\1***@", str(message)), 600)
        super().__init__(message)
        self.status = status
        self.message = message


def git(cwd: str, *args: str, timeout: int = GIT_TIMEOUT, check: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    result = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout, env=env)
    if check and result.returncode != 0:
        raise ProjectError(409, (result.stderr or result.stdout or "git 失败").strip()[-400:])
    return result


def _home() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def _forbidden(path: str) -> bool:
    real = os.path.realpath(path)
    hermes_home = os.path.realpath(os.environ.get("HERMES_HOME") or os.path.join(_home(), ".hermes"))
    return real in ("/", _home()) or real == hermes_home or real.startswith(hermes_home + os.sep)


def toplevel(path: str) -> Optional[str]:
    """The repository top level of *path* when it is one we may work in, else None."""
    if not path or not os.path.isabs(path) or not os.path.isdir(path) or _forbidden(path):
        return None
    try:
        result = git(path, "rev-parse", "--show-toplevel", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    top = result.stdout.strip()
    if result.returncode != 0 or not top or _forbidden(top):
        return None
    return os.path.realpath(top)


def _recent_run_dirs(limit: int = 60) -> list[str]:
    """Directories recent runner runs worked in (newest first)."""
    roots = [Path(_home()) / ".hermes" / f"{name}-runs" for name in ("reclaude", "cchclaude", "anyclaude", "codex")]
    metas = []
    for root in roots:
        try:
            metas += [p for p in root.glob("*/meta.json")]
        except OSError:
            continue
    metas.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    out = []
    for meta in metas[:limit]:
        try:
            cwd = str(json.loads(meta.read_text(encoding="utf-8")).get("cwd") or "")
        except (OSError, ValueError):
            continue
        if cwd and cwd not in out:
            out.append(cwd)
    return out


def candidates() -> list[dict]:
    """Projects to offer: HERMES_DISPATCH_PROJECTS first, then where recent runs worked."""
    named: list[tuple[str, str]] = []
    for item in re.split(r"[;,\n]", os.environ.get("HERMES_DISPATCH_PROJECTS", "")):
        name, _, path = item.partition("=")
        if name.strip() and path.strip():
            named.append((name.strip(), os.path.expanduser(path.strip())))
    named += [("", cwd) for cwd in _recent_run_dirs()]
    seen: dict[str, dict] = {}
    for name, path in named:
        top = toplevel(path)
        if top is None or top.startswith(os.path.realpath(_workspace_root()) + os.sep):
            continue
        entry = seen.get(top)
        if entry is None:
            seen[top] = {"path": top, "name": os.path.basename(top), "aliases": []}
            entry = seen[top]
        if name and name.lower() != entry["name"].lower() and name not in entry["aliases"]:
            entry["aliases"].append(name)
    return list(seen.values())[:12]


def _workspace_root() -> str:
    from .teams import WORKSPACE_ROOT

    return str(WORKSPACE_ROOT)


def suggest(goal: str) -> Optional[dict]:
    """The project the goal names first (by folder name or alias), if any."""
    best = None
    for entry in candidates():
        for name in [entry["name"], *entry["aliases"]]:
            if len(name) < 3:
                continue
            match = re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(name)}(?![A-Za-z0-9_-])", goal or "", re.IGNORECASE)
            if match and (best is None or match.start() < best[0]):
                best = (match.start(), entry)
    return best[1] if best else None


def describe(path: str) -> Optional[dict]:
    """{path, name, branch, head, dirty} for the plan; None when not a usable repository."""
    top = toplevel(path)
    if top is None:
        return None
    branch = git(top, "rev-parse", "--abbrev-ref", "HEAD", timeout=10).stdout.strip()
    head = git(top, "rev-parse", "--short", "HEAD", timeout=10).stdout.strip()
    dirty = bool(git(top, "status", "--porcelain", "--untracked-files=no", timeout=20).stdout.strip())
    return {"path": top, "name": os.path.basename(top), "branch": branch, "head": head, "dirty": dirty}


def context_text(path: str, limit: int = 3500) -> str:
    """What the lead should know about the project: top-level entries and the start of its guide."""
    top = toplevel(path)
    if top is None:
        return ""
    try:
        entries = sorted(e.name + ("/" if e.is_dir() else "") for e in os.scandir(top) if not e.name.startswith("."))
    except OSError:
        entries = []
    parts = [f"项目：{os.path.basename(top)}（{top}）", "顶层：" + "  ".join(entries[:60])]
    for name in ("CLAUDE.md", "AGENTS.md", "README.md"):
        guide = Path(top) / name
        if guide.is_file():
            try:
                parts.append(f"{name} 开头：\n" + guide.read_text(encoding="utf-8", errors="replace")[:1800])
            except OSError:
                pass
            break
    return "\n".join(parts)[:limit]


def _common_dir(path: str) -> str:
    return git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=10).stdout.strip()


def prepare(repo: str, slug: str, workspace: str) -> dict:
    """Create the team's branch and worktree; the project record kept with the team."""
    top = toplevel(repo)
    if top is None:
        raise ProjectError(400, f"{repo} 不是可以协作的 git 仓库")
    base_branch = git(top, "rev-parse", "--abbrev-ref", "HEAD", timeout=10).stdout.strip()
    base_sha = git(top, "rev-parse", "HEAD", timeout=10, check=True).stdout.strip()
    branch = f"halo/{slug}"
    suffix = 2
    while git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", timeout=10).returncode == 0:
        branch = f"halo/{slug}-{suffix}"
        suffix += 1
    if os.path.exists(workspace) and os.listdir(workspace):
        # A create that got this far before (idempotent retry): the worktree is already ours.
        mine = git(workspace, "rev-parse", "--abbrev-ref", "HEAD", timeout=10).stdout.strip()
        if mine.startswith(f"halo/{slug}") and _common_dir(workspace) == _common_dir(top):
            base_sha = git(workspace, "merge-base", "HEAD", base_sha, timeout=10).stdout.strip() or base_sha
            return {"path": top, "name": os.path.basename(top), "base_branch": base_branch if base_branch != "HEAD" else "",
                    "base_sha": base_sha, "branch": mine, "created_at": now()}
        raise ProjectError(409, f"工作目录 {workspace} 已存在且不为空")
    Path(workspace).parent.mkdir(parents=True, exist_ok=True)
    git(top, "worktree", "add", "-b", branch, workspace, base_sha, check=True)
    return {"path": top, "name": os.path.basename(top), "base_branch": base_branch if base_branch != "HEAD" else "",
            "base_sha": base_sha, "branch": branch, "created_at": now()}


def _commit(workspace: str, message: str) -> Optional[str]:
    git(workspace, "add", "-A", "--", ".", *JUNK, check=True)
    if git(workspace, "diff", "--cached", "--quiet").returncode == 0:
        return None
    git(workspace, "-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "commit", "-q", "--no-verify",
        "-m", message, check=True)
    return git(workspace, "rev-parse", "HEAD").stdout.strip()


def commit_finished(slug: str, team: dict, done: list[dict]) -> list[str]:
    """Commit the worktree for every newly finished task (bridge loop). Returns the task ids handled."""
    project = team.get("project") or {}
    workspace = team.get("workspace") or ""
    if not project.get("branch") or not os.path.isdir(workspace):
        return []
    handled = []
    last = project.get("last_head") or project.get("base_sha")
    owners: dict[str, list] = {}
    for task in done:
        member = task.get("member") or ""
        message = f"[{task.get('key') or ''} · {member}] {task.get('title') or ''}".strip()
        try:
            sha = _commit(workspace, message[:200])
        except (ProjectError, OSError, subprocess.SubprocessError) as exc:
            logger.warning("halowebui-teams: commit for %s %s failed: %s", slug, task.get("id"),
                           getattr(exc, "message", type(exc).__name__))
            break
        handled.append(task["id"])
        if sha:
            logger.info("halowebui-teams: %s committed %s for %s", slug, sha[:10], task.get("key"))
        # Commits the member made itself since the last finished task are this task's too.
        head = git(workspace, "rev-parse", "HEAD").stdout.strip()
        if last and head and head != last:
            for made in git(workspace, "rev-list", f"{last}..{head}").stdout.split():
                owners[made] = [task.get("key") or "", member]
        last = head or last
    if handled:
        from .common import update_team

        def apply(rec: dict) -> None:
            entry = rec.setdefault("project", {})
            entry["last_head"] = last
            entry["task_commits"] = {**(entry.get("task_commits") or {}), **owners}

        update_team(slug, apply)
    return handled


def _numstat(cwd: str, *spec: str) -> list[dict]:
    out = []
    result = git(cwd, "diff", "--numstat", "-M", *spec, "--", ".", *JUNK)
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        out.append({"path": path, "added": int(added) if added.isdigit() else None,
                    "removed": int(removed) if removed.isdigit() else None, "binary": not added.isdigit()})
    return out


def changes(team: dict) -> dict:
    """The 变更 view: branch, commits since the base, files (+/-), what is not committed yet."""
    project = team.get("project") or {}
    workspace = team.get("workspace") or ""
    if not project.get("branch"):
        return {"project": None}
    info = {k: project.get(k) for k in ("path", "name", "base_branch", "base_sha", "branch", "merged_at",
                                         "merged_sha", "pushed", "discarded_at")}
    if project.get("discarded_at") or not os.path.isdir(workspace):
        return {"project": info, "commits": [], "files": [], "pending": [], "available": False}
    base = project["base_sha"]
    log = git(workspace, "log", "--format=%H%x1f%s%x1f%an%x1f%at", f"{base}..HEAD", "-n", "200").stdout
    commits = []
    owners = project.get("task_commits") or {}
    for line in log.splitlines():
        sha, subject, author, at = (line.split("\x1f") + ["", "", "", ""])[:4]
        key = re.match(r"^\[(\S+) · ([^\]]+)\]", subject)
        task_key, member = (key.group(1), key.group(2)) if key else (owners.get(sha) or [None, None])[:2]
        commits.append({"sha": sha, "subject": subject, "author": author, "at": int(at or 0),
                        "task_key": task_key or None, "member": member or None})
    files = _numstat(workspace, base)  # committed + not yet committed, against the base
    pending = [line[3:] for line in git(workspace, "status", "--porcelain", "--", ".", *JUNK).stdout.splitlines()
               if len(line) > 3]
    repo = project["path"]
    base_branch = project.get("base_branch") or ""
    behind = 0
    if base_branch:
        counted = git(repo, "rev-list", "--count", f"{project['branch']}..{base_branch}", timeout=20)
        behind = int(counted.stdout.strip() or 0) if counted.returncode == 0 else 0
    merged = bool(base_branch) and git(repo, "merge-base", "--is-ancestor", project["branch"], base_branch,
                                       timeout=20).returncode == 0 and bool(commits)
    return {"project": info, "commits": commits, "files": files, "pending": pending[:200], "available": True,
            "added": sum(f["added"] or 0 for f in files), "removed": sum(f["removed"] or 0 for f in files),
            "base_moved": behind, "merged": merged or bool(project.get("merged_at"))}


def changed_paths(team: dict) -> Optional[list[str]]:
    """Files the team changed or added against the base (None: not a project team)."""
    project = team.get("project") or {}
    workspace = team.get("workspace") or ""
    if not project.get("base_sha"):
        return None
    if not os.path.isdir(workspace):
        return []
    paths = [f["path"] for f in _numstat(workspace, project["base_sha"])]
    untracked = git(workspace, "ls-files", "--others", "--exclude-standard", "--", ".", *JUNK).stdout.splitlines()
    return list(dict.fromkeys(p.split(" => ")[-1].rstrip("}") for p in paths + untracked if p))


def summary_text(team: dict, limit: int = 4000) -> str:
    """The change set in a few lines, for the lead's conclusion."""
    data = changes(team)
    if not data.get("project") or not data.get("available"):
        return ""
    info = data["project"]
    lines = [f"项目 {info['name']}（{info['path']}），团队分支 {info['branch']}（基于 {info.get('base_branch') or '分离 HEAD'} "
             f"{(info.get('base_sha') or '')[:10]}）：{len(data['files'])} 个文件，+{data['added']} −{data['removed']}。"]
    lines += [f"- 提交 {c['sha'][:8]} {c['subject']}" for c in data["commits"][:30]]
    lines += [f"- {f['path']}：+{f['added'] if f['added'] is not None else '?'} −{f['removed'] if f['removed'] is not None else '?'}"
              for f in data["files"][:80]]
    if data["pending"]:
        lines.append(f"（还有 {len(data['pending'])} 个未提交的改动，合并或推送前会自动提交）")
    return "\n".join(lines)[:limit]


def diff(team: dict, path: str) -> str:
    project = team.get("project") or {}
    workspace = team.get("workspace") or ""
    if not project.get("base_sha") or not os.path.isdir(workspace):
        raise ProjectError(404, "没有可看的改动")
    if not path or path.startswith("/") or ".." in Path(path).parts or "\x00" in path:
        raise ProjectError(400, "路径不对")
    text = git(workspace, "diff", "-M", project["base_sha"], "--", path).stdout
    if not text and path in git(workspace, "ls-files", "--others", "--exclude-standard", "--", path).stdout.split("\n"):
        text = git(workspace, "diff", "--no-index", "/dev/null", path).stdout  # new, not added yet
    return text[:DIFF_MAX] + ("\n… （太长，截断）" if len(text) > DIFF_MAX else "")


def merge(slug: str, team: dict) -> dict:
    """Merge the team's branch into the base branch of the user's checkout (explicit action)."""
    project = team.get("project") or {}
    repo, branch, base_branch = project.get("path"), project.get("branch"), project.get("base_branch")
    if not repo or not branch:
        raise ProjectError(404, "这个团队不是在项目里做的")
    if not base_branch:
        raise ProjectError(409, "开始时项目处于分离 HEAD，没有可合并的目标分支；请推送团队分支后自己合并")
    workspace = team.get("workspace") or ""
    if os.path.isdir(workspace):
        _commit(workspace, f"[收尾] {team.get('title') or ''}")
    current = git(repo, "rev-parse", "--abbrev-ref", "HEAD", timeout=10).stdout.strip()
    if current == base_branch:
        if git(repo, "status", "--porcelain", "--untracked-files=no", timeout=20).stdout.strip():
            raise ProjectError(409, f"{repo} 里有未提交的改动，先提交或暂存再合并")
        result = git(repo, "merge", "--ff-only", branch)
        how = "fast-forward"
        if result.returncode != 0:
            result = git(repo, "-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "merge", "--no-ff",
                         "--no-edit", "-m", f"Merge {branch}: {team.get('title') or ''}", branch)
            how = "merge"
            if result.returncode != 0:
                git(repo, "merge", "--abort")
                raise ProjectError(409, f"合并冲突，已撤回（{(result.stdout or result.stderr).strip()[-300:]}）")
    else:
        checked_out = git(repo, "worktree", "list", "--porcelain", timeout=10).stdout
        if f"branch refs/heads/{base_branch}\n" in checked_out + "\n":
            raise ProjectError(409, f"{base_branch} 正在别的工作区里检出，请在那里合并 {branch}")
        if git(repo, "merge-base", "--is-ancestor", base_branch, branch, timeout=20).returncode != 0:
            raise ProjectError(409, f"{base_branch} 之后有了新提交，不能直接快进；请在你的工作区合并 {branch}")
        new = git(repo, "rev-parse", branch, timeout=10).stdout.strip()
        old = git(repo, "rev-parse", base_branch, timeout=10).stdout.strip()
        git(repo, "update-ref", f"refs/heads/{base_branch}", new, old, check=True)
        how = "fast-forward"
    sha = git(repo, "rev-parse", base_branch, timeout=10).stdout.strip()
    from .common import update_team

    update_team(slug, lambda rec: rec.setdefault("project", {}).update({"merged_at": now(), "merged_sha": sha}))
    return {"merged": True, "how": how, "sha": sha, "base_branch": base_branch}


def push(slug: str, team: dict, what: str) -> dict:
    """Push the team branch, or the base branch after a merge (explicit action)."""
    project = team.get("project") or {}
    repo, branch, base_branch = project.get("path"), project.get("branch"), project.get("base_branch")
    if not repo or not branch:
        raise ProjectError(404, "这个团队不是在项目里做的")
    ref = branch if what == "branch" else base_branch
    if what not in ("branch", "base") or not ref or not _BRANCH_RE.match(ref):
        raise ProjectError(400, "要推送哪个分支？")
    if what == "base" and not project.get("merged_at"):
        raise ProjectError(409, "还没合并，先合并再推送")
    remote = git(repo, "remote", timeout=10).stdout.split()
    if "origin" not in remote:
        raise ProjectError(409, "这个仓库没有 origin 远程")
    workspace = team.get("workspace") or ""
    if what == "branch" and os.path.isdir(workspace):
        _commit(workspace, f"[收尾] {team.get('title') or ''}")
    result = git(repo, "push", "origin", f"refs/heads/{ref}:refs/heads/{ref}", timeout=PUSH_TIMEOUT)
    if result.returncode != 0:
        raise ProjectError(502, "推送失败：" + (result.stderr or result.stdout).strip()[-300:])
    from .common import update_team

    update_team(slug, lambda rec: rec.setdefault("project", {}).setdefault("pushed", {}).update({what: now()}))
    return {"pushed": True, "ref": ref}


def discard(slug: str, team: dict) -> dict:
    """Remove the team's worktree and branch (after the team is over; explicit action)."""
    project = team.get("project") or {}
    repo, branch = project.get("path"), project.get("branch")
    if not repo or not branch:
        raise ProjectError(404, "这个团队不是在项目里做的")
    if (team.get("conclusion") or {}).get("status") == "generating":
        raise ProjectError(409, "负责人正在写结论（要读这些文件），写完再放弃分支")
    workspace = team.get("workspace") or ""
    if os.path.isdir(workspace):
        # The conclusion lives in <workspace>/.halo: keep it through the removal.
        import shutil
        import tempfile

        keep = Path(workspace) / ".halo"
        saved = None
        if keep.is_dir():
            saved = Path(tempfile.mkdtemp(prefix="halo-keep-")) / ".halo"
            shutil.copytree(keep, saved)
        git(repo, "worktree", "remove", "--force", workspace, check=True)
        Path(workspace).mkdir(parents=True, exist_ok=True)  # the team's record still points here
        if saved is not None:
            shutil.copytree(saved, keep)
            shutil.rmtree(saved.parent, ignore_errors=True)
    git(repo, "worktree", "prune", timeout=20)
    git(repo, "branch", "-D", branch, timeout=20)
    from .common import update_team

    update_team(slug, lambda rec: rec.setdefault("project", {}).update({"discarded_at": now()}))
    return {"discarded": True}

"""The team's final conclusion (结论): a report the lead writes once every task is done.

Inputs are the records, not a summary of a summary: the goal and plan, every task's full
result (runner members' final answers are kept up to 60 000 characters), and the files the team
left in its workspace (a listing, plus the text of small deliverables). The lead model is the
same one that planned (Hermes' default model, see ``plan.lead_routes``). When no model answers,
the conclusion is assembled from the task results instead, so a finished team always has one.

Stored as ``<workspace>/.halo/conclusion.md`` plus a ``conclusion`` entry in the team record
(status, model, when, size). Images and files the report links are served by ``read_file`` —
only from the team's workspace — and shown inline by HaloWebUI.
"""

from __future__ import annotations

import mimetypes
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .common import board_conn, kb, logger, now, read_team, redact, update_team

CONCLUSION_DIR = ".halo"
CONCLUSION_FILE = "conclusion.md"
STALE_GENERATING = 900          # a 'generating' entry this old lost its thread (gateway restart)
TASK_RESULT_CHARS = 12000       # per task, into the lead's prompt
PROMPT_RESULTS_CHARS = 60000    # all task results together
FILE_TEXT_CHARS = 8000          # per deliverable file
PROMPT_FILES_CHARS = 30000      # all deliverable files together
MAX_LISTED_FILES = 200
MAX_SERVED_BYTES = 25 * 1024 * 1024
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv", ".html", ".htm", ".xml",
                   ".py", ".ts", ".js", ".svelte", ".css", ".sh", ".sql", ".toml", ".ini", ".log", ".go", ".rs",
                   ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".rb", ".php", ".vue", ".tsx", ".jsx", ".mjs"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".halo", "dist", "build", ".svelte-kit"}
_jobs: dict[str, threading.Thread] = {}
_jobs_lock = threading.Lock()

SYSTEM_PROMPT = """你是协作团队的负责人（team-lead）。团队已经结束工作，你要给用户写这次协作任务的最终结论报告。

要求：
- 只根据下面提供的材料（目标、计划、每个任务的结果、工作目录里的文件）写，不编造没有做过的事；材料里没有的就说没有。
- 用 Markdown，结构清晰，适合直接阅读：
  # 一个准确的标题
  > 一句话结论（做成了什么 / 没做成什么）
  ## 结论摘要 —— 3 到 6 条要点
  ## 关键成果 —— 具体产出、数据、决定；必要时用表格对比
  ## 各成员产出 —— 每个成员做了什么、交付了哪些文件
  ## 产出物 —— 列出重要文件，用相对工作目录的路径写成链接，例如 [report.md](report.md)；图片用 ![说明](相对路径.png) 直接展示
  ## 遗留问题与风险 —— 没完成的、失败的、需要用户决定的
  ## 建议的下一步
- 代码、命令、配置用代码块并标注语言；不要把整份文件原样贴进来，引用要点即可。
- 用中文，写给不看代码的人也能看懂；不要写客套话。"""


def _workspace(team: dict) -> Optional[Path]:
    path = team.get("workspace")
    if not path:
        return None
    root = Path(path)
    return root if root.is_dir() else None


def conclusion_path(team: dict) -> Optional[Path]:
    root = _workspace(team)
    return root / CONCLUSION_DIR / CONCLUSION_FILE if root else None


# --- workspace files ---------------------------------------------------------------------------

def file_kind(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in TEXT_EXTENSIONS:
        return "text"
    return "binary"


def list_files(team: dict) -> list[dict]:
    """Files the team left in its workspace (newest first, hidden/vendor dirs skipped)."""
    root = _workspace(team)
    if root is None:
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in filenames:
            if name.startswith("."):
                continue
            full = Path(dirpath) / name
            try:
                st = full.lstat()
            except OSError:
                continue
            if not full.is_file() or full.is_symlink():
                continue
            rel = full.relative_to(root).as_posix()
            out.append({"path": rel, "size": st.st_size, "mtime": int(st.st_mtime), "kind": file_kind(name)})
            if len(out) >= MAX_LISTED_FILES * 3:
                break
    out.sort(key=lambda f: (-f["mtime"], f["path"]))
    return out[:MAX_LISTED_FILES]


def resolve_file(team: dict, rel: str) -> Optional[Path]:
    """*rel* inside the team's workspace, or None (absolute paths, .., symlinks out refused)."""
    root = _workspace(team)
    if root is None or not rel:
        return None
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return None
    root_real = root.resolve()
    candidate = (root_real / rel).resolve()
    try:
        candidate.relative_to(root_real)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def read_file(team: dict, rel: str) -> tuple[bytes, str, str]:
    """(data, content_type, name). Raises FileNotFoundError / ValueError (too big)."""
    path = resolve_file(team, rel)
    if path is None:
        raise FileNotFoundError(rel)
    size = path.stat().st_size
    if size > MAX_SERVED_BYTES:
        raise ValueError(f"文件太大（{size // 1024 // 1024} MB，上限 {MAX_SERVED_BYTES // 1024 // 1024} MB）")
    kind = file_kind(path.name)
    ctype = mimetypes.guess_type(path.name)[0] or ("text/plain" if kind == "text" else "application/octet-stream")
    if kind == "text" and not ctype.startswith("text/") and ctype not in ("application/json",):
        ctype = "text/plain"
    if ctype in ("text/html", "image/svg+xml") and kind != "image":
        ctype = "text/plain"  # never let a member's HTML run as a page on HaloWebUI's origin
    return path.read_bytes(), ctype, path.name


# --- inputs ------------------------------------------------------------------------------------

def _task_rows(slug: str, team: dict) -> list[dict]:
    task_map = team.get("tasks") or {}
    rows = []
    with board_conn(slug) as conn:
        for task in kb().list_tasks(conn, include_archived=True):
            entry = task_map.get(task.id)
            if not entry:
                continue
            runs = kb().list_runs(conn, task.id)
            last = runs[-1] if runs else None
            result = task.result or (last.summary if last else "") or ""
            rows.append({
                "id": task.id, "key": entry.get("key"), "seq": entry.get("seq") or 0, "member": entry.get("member"),
                "executor": entry.get("executor") or "", "title": re.sub(r"^\S+\s+", "", task.title, count=1),
                "status": task.status, "result": redact(result, 60000, one_line=False),
                "error": redact((last.error if last else "") or task.last_failure_error or "", 400),
                "attempts": len(runs),
            })
    rows.sort(key=lambda r: (r["seq"], r["key"] or ""))
    return rows


def _deliverables(team: dict, files: list[dict], rows: list[dict]) -> list[tuple[str, str]]:
    """Text of the small files the tasks mention first, then other small text files."""
    root = _workspace(team)
    if root is None:
        return []
    mentioned = " ".join((r["result"] or "") for r in rows)
    ranked = sorted((f for f in files if f["kind"] == "text" and f["size"] <= 200_000),
                    key=lambda f: (f["path"] not in mentioned and os.path.basename(f["path"]) not in mentioned, f["size"]))
    out, used = [], 0
    for f in ranked:
        if used >= PROMPT_FILES_CHARS:
            break
        try:
            text = (root / f["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = redact(text, FILE_TEXT_CHARS, one_line=False)
        out.append((f["path"], text))
        used += len(text)
    return out


def _messages(team: dict, rows: list[dict], files: list[dict], texts: list[tuple[str, str]]) -> list:
    members = "\n".join(
        f"- {m.get('name')}（{m.get('role')}{'，助手模板「' + m['assistant']['name'] + '」' if isinstance(m.get('assistant'), dict) else ''}）"
        for m in team.get("members") or [])
    parts = [f"协作目标：\n{team.get('goal') or ''}", f"团队：{team.get('title') or ''}\n负责人的分工说明：{team.get('summary') or '（无）'}\n成员：\n{members}"]
    budget = PROMPT_RESULTS_CHARS
    for r in rows:
        result = r["result"] or "（没有结果）"
        result = result[: min(TASK_RESULT_CHARS, max(800, budget))]
        budget -= len(result)
        stopped = r["status"] == "blocked" and "用户停止" in (r["error"] or "")
        status = "被用户停止，没做完" if stopped else {"done": "已完成", "blocked": "失败/受阻", "running": "未结束"}.get(
            r["status"], r["status"])
        parts.append(f"### 任务 {r['key']} {r['title']}（成员 {r['member']}，执行 {r['executor'] or '—'}，{status}，{r['attempts']} 次执行）\n"
                     + (f"错误：{r['error']}\n" if r["error"] and r["status"] != "done" and not stopped else "") + result)
    listing = "\n".join(f"- {f['path']}（{f['kind']}，{f['size']} 字节）" for f in files[:120]) or "（工作目录里没有文件）"
    parts.append(f"工作目录 {team.get('workspace')} 的文件：\n{listing}")
    for path, text in texts:
        parts.append(f"文件 {path} 的内容：\n```\n{text}\n```")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}]


def assemble(team: dict, rows: list[dict], files: list[dict], note: str = "") -> str:
    """A conclusion built from the records alone (no model)."""
    done = [r for r in rows if r["status"] == "done"]
    lines = [f"# {team.get('title') or '协作任务'}：结论", ""]
    lines.append(f"> {len(done)}/{len(rows)} 个任务完成。" + (f"（{note}）" if note else ""))
    lines += ["", "## 目标", "", team.get("goal") or "", "", "## 各任务结果", ""]
    for r in rows:
        status = "✅ 已完成" if r["status"] == "done" else f"⚠️ {r['status']}"
        lines += [f"### {r['key']} {r['title']}", "", f"*成员 {r['member']} · 执行 {r['executor'] or '—'} · {status}*", "",
                  (r["result"] or r["error"] or "（没有结果）").strip(), ""]
    images = [f for f in files if f["kind"] == "image"][:12]
    others = [f for f in files if f["kind"] != "image"][:40]
    if files:
        lines += ["## 产出物", ""]
        lines += [f"- [{f['path']}]({f['path']})" for f in others]
        for f in images:
            lines += ["", f"![{f['path']}]({f['path']})"]
    return "\n".join(lines).strip() + "\n"


# --- generation --------------------------------------------------------------------------------

def _set(slug: str, **fields: Any) -> dict:
    def mutate(rec: dict) -> None:
        current = dict(rec.get("conclusion") or {})
        current.update(fields)
        rec["conclusion"] = current

    return (update_team(slug, mutate).get("conclusion") or {})


def generate(slug: str, *, by: str = "auto") -> dict:
    """Write the conclusion now (blocking). Returns the conclusion entry."""
    team = read_team(slug)
    if not team:
        return {"status": "failed", "error": "team not found"}
    path = conclusion_path(team)
    if path is None:
        return _set(slug, status="failed", error="工作目录不存在", finished_at=now())
    rows = _task_rows(slug, team)
    files = list_files(team)
    texts = _deliverables(team, files, rows)
    from .plan import call_model

    started = time.time()
    lead = team.get("lead_model") if isinstance(team.get("lead_model"), dict) else {}
    text, reason, used = call_model(_messages(team, rows, files, texts), timeout=300, max_tokens=8000, temperature=0.2,
                                    preferred=lead.get("requested") or None)
    source = "lead"
    if text is None or len(text.strip()) < 40:
        source = "assembled"
        text = assemble(team, rows, files, note="负责人模型没有给出结论，以下按任务记录整理" if text is None else "")
    text = redact(text, 200000, one_line=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    entry = _set(slug, status="ready", source=source, model=used.get("model") or "",
                 model_label=used.get("label") or "", fallback_reason=used.get("fallback_reason") or (reason if source == "assembled" else ""),
                 generated_at=now(), seconds=round(time.time() - started, 1), chars=len(text),
                 tasks_done=sum(1 for r in rows if r["status"] == "done"), tasks_total=len(rows), by=by, error="")
    with board_conn(slug) as conn:
        from .common import TEAM_EVENT_TASK, append_event

        append_event(conn, TEAM_EVENT_TASK, "halo_team", {
            "action": "concluded", "source": source, "model": used.get("model") or "", "chars": len(text)})
    return entry


def _run(slug: str, by: str) -> None:
    try:
        generate(slug, by=by)
    except Exception as exc:
        logger.warning("halowebui-teams: conclusion for %s failed", slug, exc_info=True)
        _set(slug, status="failed", error=f"生成结论出错：{type(exc).__name__}", finished_at=now())
    finally:
        with _jobs_lock:
            _jobs.pop(slug, None)


def start(slug: str, *, by: str = "auto", force: bool = False) -> dict:
    """Start generating in a background thread unless it is running or already done."""
    team = read_team(slug) or {}
    current = team.get("conclusion") or {}
    with _jobs_lock:
        if slug in _jobs and _jobs[slug].is_alive():
            return current
        if not force and current.get("status") == "ready":
            return current
        if (not force and current.get("status") == "generating"
                and now() - int(current.get("started_at") or 0) < STALE_GENERATING):
            return current
        entry = _set(slug, status="generating", started_at=now(), by=by, error="")
        if os.environ.get("HALO_TEAMS_CONCLUSION_SYNC") == "1":  # tests
            _jobs[slug] = threading.current_thread()
        else:
            thread = threading.Thread(target=_run, args=(slug, by), name=f"halo-conclusion-{slug}", daemon=True)
            _jobs[slug] = thread
            thread.start()
            return entry
    _run(slug, by)
    return (read_team(slug) or {}).get("conclusion") or entry


def read(slug: str, team: dict) -> dict:
    """The conclusion for the API: entry + markdown + task results + files."""
    entry = dict(team.get("conclusion") or {})
    if entry.get("status") == "generating" and now() - int(entry.get("started_at") or 0) > STALE_GENERATING:
        with _jobs_lock:
            alive = slug in _jobs and _jobs[slug].is_alive()
        if not alive:
            entry["status"] = "failed"
            entry["error"] = "生成被中断（网关重启），可以重新生成"
    markdown = ""
    path = conclusion_path(team)
    if path is not None and path.exists():
        try:
            markdown = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            markdown = ""
    rows = _task_rows(slug, team)
    files = list_files(team)
    return {
        # A failed regeneration keeps showing the previous report, with the error beside it.
        "status": entry.get("status") or ("ready" if markdown else "none"),
        "entry": entry,
        "markdown": markdown,
        "tasks": [{k: r[k] for k in ("id", "key", "title", "member", "executor", "status", "result", "error", "attempts")}
                  for r in rows],
        "files": files,
        "workspace": team.get("workspace"),
    }

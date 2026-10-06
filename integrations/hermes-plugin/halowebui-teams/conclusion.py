"""The team's final conclusion (结论): the complete result of the task, written by the lead once
every task is done — the full answer / document / images the goal asked for, not a report on who
did what (the board and the task records keep that).

Inputs are the records, not a summary of a summary: the goal and plan, every task's full
result (runner members' final answers are kept up to 60 000 characters), and the files the team
left in its workspace (a listing, plus the text of the deliverables). A member's finished document
is not rewritten: the lead places it with ``<!-- halo:include path -->`` and ``expand_includes``
puts the file's full text there. The lead model is the same one that planned (Hermes' default
model, see ``plan.lead_routes``). When no model answers, the conclusion is assembled from the
deliverables and task results instead, so a finished team always has one.

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
TASK_RESULT_CHARS = 30000       # per task, into the lead's prompt
PROMPT_RESULTS_CHARS = 80000    # all task results together
FILE_TEXT_CHARS = 40000         # per deliverable file
PROMPT_FILES_CHARS = 80000      # all deliverable files together
CONCLUSION_MAX_TOKENS = 16000   # the result can be long (providers with a lower cap get theirs)
CONCLUSION_TIMEOUT = 600
CONCLUSION_MAX_CHARS = 400000   # after includes
INCLUDE_MAX_BYTES = 400_000     # one included file
DOC_EXTENSIONS = {".md", ".markdown", ".txt"}
MAX_LISTED_FILES = 200
MAX_SERVED_BYTES = 25 * 1024 * 1024
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv", ".html", ".htm", ".xml",
                   ".py", ".ts", ".js", ".svelte", ".css", ".sh", ".sql", ".toml", ".ini", ".log", ".go", ".rs",
                   ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".rb", ".php", ".vue", ".tsx", ".jsx", ".mjs"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".halo", "dist", "build", ".svelte-kit"}
_jobs: dict[str, threading.Thread] = {}
_jobs_lock = threading.Lock()

SYSTEM_PROMPT = """你是协作团队的负责人（team-lead）。团队已经做完了，现在由你把这次任务的**完整结果**交给用户。你写的这一页就是用户要的东西本身，不是工作汇报：用户不关心每一步谁做了什么，只关心结果。

先想清楚目标要的是什么，然后直接给出它完整的样子：
- 问题 / 咨询 → 完整、可以直接照着做的答案（不要写成「指南已写好，见某文件」）；
- 文章 / 报告 / 方案 / 指南 / 文案 → 完整正文；
- 调研 / 对比 / 核实 → 完整的发现、数据、对比表和明确的结论或建议，附上材料里的来源链接；
- 图片 / 设计 / 图解 → 把图直接展示出来（![说明](相对路径.png)），写清每张图是什么；
- 工作目录 images/ 里的图是成员用 gpt-image 生成的，同名的 .prompt.md 记着它的提示词：凡是和目标相关的图都要展示在结果里合适的位置，并在图下面用引用块写「提示词：」加上提示词（模板很长时保留描述画面的部分）；
- 代码 / 项目改动 → 做成了什么、怎么用、改了哪些文件（链接）、怎么验证、合并前要注意什么；关键代码用代码块，不贴整份文件。

成员已经写好的完整成品文件（例如一篇完整的指南、报告、文章），不要重写，也不要缩成摘要：在要放它的位置单独占一行写
<!-- halo:include 相对路径 -->
系统会把这个文件的全文原样放到那里（只能引用下面「文件 … 的内容」里出现过的文本文件）。你可以在它前后加导语、补上其他成员的内容，或者把几个文件按顺序拼起来；同一份内容不要既引用又自己再写一遍。被引用的文件自己有 # 标题时，你就不要再写一个重复的标题。

成果分散在几个任务结果里时，由你整合成一份完整、连贯、不重复的成品；内容以材料为准，不要为了篇幅压缩成要点。只根据材料写，不编造，材料里没有的就说没有。

格式：Markdown。第一行是 `# 标题`——成果本身的标题（例如「科学戒烟行动指南」），不要写「结论报告」「协作总结」；需要时紧跟一行 `> ` 写一句话结论。文件链接用相对工作目录的路径，例如 [report.md](report.md)。
最后可以有一个简短的 `## 附注`：只写用户需要知道的限制、没做成的部分、需要用户决定或注意的事；没有就不写。不要写「结论摘要」「各成员产出」「工作过程」「产出物清单」这类过程性章节（页面会单独列出产出文件和每个任务的记录），也不要客套话。
用中文写，除非目标要求别的语言。"""


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
    from . import projects

    changed = projects.changed_paths(team)
    if changed is not None:  # a project team: its deliverables are what it changed, not the whole repository
        for rel in changed:
            full = root / rel
            try:
                st = full.lstat()
            except OSError:
                continue
            if full.is_file() and not full.is_symlink():
                out.append({"path": rel, "size": st.st_size, "mtime": int(st.st_mtime), "kind": file_kind(full.name)})
        out.sort(key=lambda f: (-f["mtime"], f["path"]))
        return out[:MAX_LISTED_FILES]
    for dirpath, dirnames, filenames in os.walk(root):
        # inputs/ at the top holds the files the user gave with the goal: not something the team made
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                             and not (d == "inputs" and Path(dirpath) == root))
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


def _deliverables(team: dict, files: list[dict], rows: list[dict]) -> list[tuple[str, str, int]]:
    """(path, text, full length) of the deliverables for the lead's prompt: files the tasks
    mention first, documents (.md / .txt) before other text files, then by size."""
    root = _workspace(team)
    if root is None:
        return []
    mentioned = " ".join((r["result"] or "") for r in rows)

    def rank(f: dict) -> tuple:
        named = f["path"] in mentioned or os.path.basename(f["path"]) in mentioned
        doc = os.path.splitext(f["path"])[1].lower() in DOC_EXTENSIONS
        return (not named, not doc, f["size"])

    ranked = sorted((f for f in files if f["kind"] == "text" and f["size"] <= INCLUDE_MAX_BYTES), key=rank)
    out, used = [], 0
    for f in ranked:
        if used >= PROMPT_FILES_CHARS:
            break
        try:
            full = (root / f["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = redact(full, min(FILE_TEXT_CHARS, max(2000, PROMPT_FILES_CHARS - used)), one_line=False)
        out.append((f["path"], text, len(full)))
        used += len(text)
    return out


def _messages(team: dict, rows: list[dict], files: list[dict], texts: list[tuple[str, str]]) -> list:
    members = "\n".join(
        f"- {m.get('name')}（{m.get('role')}{'，助手「' + m['assistant']['name'] + '」' if isinstance(m.get('assistant'), dict) else ''}）"
        for m in team.get("members") or [])
    from .lead import later_requests

    parts = [f"协作目标：\n{team.get('goal') or ''}" + ("\n\n" + later_requests(team) if later_requests(team) else ""), f"团队：{team.get('title') or ''}\n负责人的分工说明：{team.get('summary') or '（无）'}\n成员：\n{members}"]
    budget = PROMPT_RESULTS_CHARS
    for r in rows:
        result = r["result"] or "（没有结果）"
        result = result[: min(TASK_RESULT_CHARS, max(800, budget))]
        budget -= len(result)
        stopped = r["status"] == "blocked" and "用户停止" in (r["error"] or "")
        status = "被用户停止，没做完" if stopped else {"done": "已完成", "blocked": "失败/受阻", "running": "未结束",
                                                  "archived": "已取消（用户要求取消或采纳了负责人跳过的建议）"}.get(
            r["status"], r["status"])
        parts.append(f"### 任务 {r['key']} {r['title']}（成员 {r['member']}，执行 {r['executor'] or '—'}，{status}，{r['attempts']} 次执行）\n"
                     + (f"错误：{r['error']}\n" if r["error"] and r["status"] != "done" and not stopped else "") + result)
    listing = "\n".join(f"- {f['path']}（{f['kind']}，{f['size']} 字节）" for f in files[:120]) or "（工作目录里没有文件）"
    from . import projects

    change_set = projects.summary_text(team) if team.get("project") else ""
    if change_set:
        parts.append("代码改动（团队在项目的独立分支上工作；结论里写清改了什么、为什么、怎么验证、合并前要注意什么）：\n"
                     + change_set)
        parts.append(f"改动的文件：\n{listing}")
    else:
        parts.append(f"工作目录 {team.get('workspace')} 的文件：\n{listing}")
    for path, text, full in texts:
        cut = f"（只给你看了前 {len(text)} 字，全文 {full} 字；用 halo:include 引用时放的是全文）" if full > len(text) + 1 else ""
        parts.append(f"文件 {path} 的内容{cut}：\n````\n{text}\n````")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}]


def assemble(team: dict, rows: list[dict], files: list[dict], note: str = "",
             texts: Optional[list] = None) -> str:
    """A conclusion built from the records alone (no model): the main deliverable document in full
    when there is one, then every task's result."""
    done = [r for r in rows if r["status"] == "done"]
    lines = [f"# {team.get('title') or '协作任务'}", ""]
    lines.append(f"> {len(done)}/{len(rows)} 个任务完成。" + (f"（{note}）" if note else ""))
    docs = [path for path, _text, _full in (texts or []) if os.path.splitext(path)[1].lower() in DOC_EXTENSIONS]
    if docs:
        lines += ["", f"<!-- halo:include {docs[0]} -->"]
    lines += ["", "## 各任务结果", ""]
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


# --- includes ----------------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r"^\s*<!--\s*halo:include\s+(.+?)\s*-->\s*$")
_FENCE_LINE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(#{1,6})(\s+\S)")
_LINK_RE = re.compile(r"(!?\[[^\]]*\]\()(\s*<?)([^)\s>]+)(>?(?:\s+\"[^\"]*\")?\))")
_FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
CODE_LANGS = {".py": "python", ".ts": "ts", ".js": "js", ".mjs": "js", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
              ".sh": "sh", ".sql": "sql", ".html": "html", ".htm": "html", ".css": "css", ".svelte": "svelte",
              ".toml": "toml", ".go": "go", ".rs": "rust", ".java": "java", ".tsx": "tsx", ".jsx": "jsx",
              ".csv": "csv", ".tsv": "tsv", ".xml": "xml", ".vue": "vue"}


def _rebase_links(markdown: str, base: str) -> str:
    """Relative links / images of a document in *base* (a workspace subdirectory) made relative to
    the workspace root, so they still resolve once the document is placed in the conclusion."""
    if not base:
        return markdown

    def fix(m: re.Match) -> str:
        href = m.group(3)
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|/|#)", href, re.I):
            return m.group(0)
        joined = os.path.normpath(os.path.join(base, href)).replace("\\", "/")
        if joined.startswith(".."):
            return m.group(0)
        return m.group(1) + m.group(2) + joined + m.group(4)

    out, fence = [], None
    for line in markdown.split("\n"):
        marker = _FENCE_LINE_RE.match(line)
        if marker:
            fence = marker.group(1)[0] if fence is None else (None if marker.group(1)[0] == fence else fence)
        out.append(line if fence is not None or marker else _LINK_RE.sub(fix, line))
    return "\n".join(out)


def _demote(markdown: str) -> str:
    """Every heading one level down (outside code), for a document placed under the result's own # title."""
    out, fence = [], None
    for line in markdown.split("\n"):
        marker = _FENCE_LINE_RE.match(line)
        if marker:
            fence = marker.group(1)[0] if fence is None else (None if marker.group(1)[0] == fence else fence)
        elif fence is None:
            m = _HEADING_RE.match(line)
            if m and len(m.group(1)) < 6:
                line = "#" + line
        out.append(line)
    return "\n".join(out)


def expand_includes(text: str, team: dict) -> tuple[str, list[str]]:
    """Put the full text of every ``<!-- halo:include path -->`` file (in the team's workspace) where
    the lead placed it. Documents go in as Markdown (relative links rebased, headings one level down
    when the result already has a # title above), other text files as a code block. Returns the text
    and the paths included."""
    lines = text.split("\n")
    out: list[str] = []
    included: list[str] = []
    fence = None
    seen_h1 = False
    for line in lines:
        marker = _FENCE_LINE_RE.match(line)
        if marker:
            fence = marker.group(1)[0] if fence is None else (None if marker.group(1)[0] == fence else fence)
            out.append(line)
            continue
        m = _INCLUDE_RE.match(line) if fence is None else None
        if not m:
            if fence is None and line.startswith("# "):
                seen_h1 = True
            out.append(line)
            continue
        rel = re.sub(r"^\./", "", m.group(1).strip().strip("`'\"").replace("\\", "/"))
        path = resolve_file(team, rel)
        if path is None or file_kind(path.name) != "text" or path.stat().st_size > INCLUDE_MAX_BYTES:
            logger.info("halowebui-teams: conclusion include %r skipped (missing, not text or too big)", rel)
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        root = _workspace(team)
        rel_path = path.relative_to(root.resolve()).as_posix() if root is not None else rel
        ext = os.path.splitext(path.name)[1].lower()
        body = redact(body, INCLUDE_MAX_BYTES, one_line=False)
        if ext in DOC_EXTENSIONS:
            body = _FRONT_MATTER_RE.sub("", body, count=1)
            body = _rebase_links(body, os.path.dirname(rel_path))
            if seen_h1 and re.search(r"^# \S", body, re.M):
                body = _demote(body)
            elif re.search(r"^# \S", body, re.M):
                seen_h1 = True
        else:
            ticks = "````" if "```" in body else "```"
            body = f"{ticks}{CODE_LANGS.get(ext, '')}\n{body.rstrip()}\n{ticks}"
        out.append(body.strip("\n"))
        if rel_path not in included:
            included.append(rel_path)
    return "\n".join(out), included


# --- generation --------------------------------------------------------------------------------

def _strip_wrapping_fence(text: str) -> str:
    """A model that wrapped its whole answer in ```markdown … ``` — unwrap it."""
    m = re.match(r"^\s*```(?:markdown|md)?\s*\n(.*)\n```\s*$", text, re.S)
    return m.group(1) if m and "\n```" not in m.group(1) else text


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
    text, reason, used = call_model(_messages(team, rows, files, texts), timeout=CONCLUSION_TIMEOUT,
                                    max_tokens=CONCLUSION_MAX_TOKENS, temperature=0.2,
                                    preferred=lead.get("requested") or None)
    source = "lead"
    if text is None or (len(text.strip()) < 40 and "halo:include" not in text):
        source = "assembled"
        text = assemble(team, rows, files, note="负责人模型没有给出结论，以下按任务记录整理" if text is None else "",
                        texts=texts)
    text = _strip_wrapping_fence(redact(text, CONCLUSION_MAX_CHARS, one_line=False))
    text, included = expand_includes(text, team)
    text = text[:CONCLUSION_MAX_CHARS]
    from . import illustrate

    text = illustrate.reinsert(team, text)  # the picture made for the previous version stays
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    entry = _set(slug, status="ready", source=source, model=used.get("model") or "",
                 model_label=used.get("label") or "", fallback_reason=used.get("fallback_reason") or (reason if source == "assembled" else ""),
                 generated_at=now(), seconds=round(time.time() - started, 1), chars=len(text),
                 tasks_done=sum(1 for r in rows if r["status"] == "done"), tasks_total=len(rows), by=by, error="",
                 # format 2: the complete result (format 1 was a report about the work); files placed in full
                 format=2, included=included,
                 # the lead checks it against the goal next (see _run); the done notice waits for that
                 acceptance={"status": "checking", "started_at": now()} if source == "lead" else None)
    with board_conn(slug) as conn:
        from .common import TEAM_EVENT_TASK, append_event

        append_event(conn, TEAM_EVENT_TASK, "halo_team", {
            "action": "concluded", "source": source, "model": used.get("model") or "", "chars": len(text)})
    return entry


def _run(slug: str, by: str) -> None:
    try:
        entry = generate(slug, by=by)
        if entry.get("status") == "ready":
            from . import illustrate

            try:  # its picture is drawn meanwhile (the hand-over to the chat waits for both)
                illustrate.auto(slug)
            except Exception:  # noqa: BLE001
                logger.warning("halowebui-teams: automatic illustration for %s did not start", slug, exc_info=True)
        if entry.get("status") == "ready" and entry.get("source") == "lead":
            from .lead import check_acceptance

            try:  # the lead checks the result against the goal (gaps → 「让团队补上」)
                check_acceptance(slug)
            except Exception:  # noqa: BLE001
                logger.warning("halowebui-teams: acceptance check for %s failed", slug, exc_info=True)
                _set(slug, acceptance={"status": "failed", "error": "验收出错", "at": now()})
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
    from . import illustrate

    if entry.get("illustration"):
        entry["illustration"] = illustrate.public(entry["illustration"])
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

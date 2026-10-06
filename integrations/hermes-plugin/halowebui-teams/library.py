"""The user's assistants (HaloWebUI's 助手库) in a plan.

HaloWebUI sends a shortlist of the user's library with each plan request (this process cannot
read its model table):

  library = {
    "may_write": bool,                 # may the user save assistants (else upgrades / new ones are
                                       # for this run only)
    "assistants": [{ref: "model:<id>", name, emoji, domain, description, editable, version, prompt}],
    "templates":  [{ref: "builtin:<id>", name, emoji, description, prompt}],   # beyond 「协作」
    "preferred":  ["model:<id>" | "builtin:<id>"],   # 「用于协作」: at least one member uses each
    "max_create": 2, "max_update": 2,
  }

(``prompt`` is an excerpt.) Per member the lead may use a library assistant or a template, ask
for an upgrade of an editable assistant (a complete new system prompt + one line on what changed),
or design a new reusable one. The plan only RECORDS these — nothing is written here:

  member["assistant"] = {ref, id, name, emoji, kind?, description, domain?, version?,
                         action: use | template | update | create | temporary,
                         reason?, note?, proposal?}         # proposal: key in the list below
  plan["assistant_proposals"] = [{key, action: update | create | temporary, ref?, name, emoji,
                                  domain, description, system_prompt, change, from?, version?}]
  plan["assistant_library"] = {"may_write": bool}

HaloWebUI carries them out once, when the user approves the plan, and sends each member's
assistant back as a snapshot (``teams.create_team(member_assistants=...)``).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import assistants as templates_mod
from .common import redact

MAX_CREATE = 2
MAX_UPDATE = 2
NAME_MAX = 24
DOMAIN_MAX = 24
DESCRIPTION_MAX = 160
SYSTEM_MAX = 8000
SYSTEM_MIN = 40
REASON_MAX = 200
ACTIONS = ("use", "template", "update", "create", "temporary")
PROPOSAL_ACTIONS = ("update", "create", "temporary")
_EMOJI_STRIP = re.compile(r"[<>&\"'\s]")


def _text(value: Any, limit: int, *, one_line: bool = True) -> str:
    return redact(value, limit, one_line=one_line) if value not in (None, "") else ""


def _system(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:SYSTEM_MAX]


def _emoji(value: Any) -> str:
    return _EMOJI_STRIP.sub("", str(value or ""))[:4]


def _excerpt(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def usable(library: Any) -> Optional[dict]:
    """The library HaloWebUI sent, cleaned; None when there is none (an older HaloWebUI)."""
    if not isinstance(library, dict):
        return None
    out_assistants = []
    for entry in library.get("assistants") or []:
        if not isinstance(entry, dict):
            continue
        ref = str(entry.get("ref") or "").strip()
        if not ref.startswith("model:") or len(ref) > 220:
            continue
        out_assistants.append({
            "ref": ref, "id": ref[len("model:"):],
            "name": _text(entry.get("name"), 60) or ref, "emoji": _emoji(entry.get("emoji")),
            "domain": _text(entry.get("domain"), DOMAIN_MAX), "description": _text(entry.get("description"), DESCRIPTION_MAX),
            "editable": bool(entry.get("editable")), "version": entry.get("version") if isinstance(entry.get("version"), int) else None,
            "prompt": _excerpt(entry.get("prompt"), 400),
        })
    out_templates = []
    for entry in library.get("templates") or []:
        if not isinstance(entry, dict):
            continue
        ref = str(entry.get("ref") or "").strip()
        if not ref.startswith("builtin:"):
            continue
        out_templates.append({"ref": ref, "id": ref[len("builtin:"):], "name": _text(entry.get("name"), 60),
                              "emoji": _emoji(entry.get("emoji")), "description": _text(entry.get("description"), DESCRIPTION_MAX),
                              "prompt": _excerpt(entry.get("prompt"), 400)})
    preferred = [str(r).strip() for r in library.get("preferred") or [] if str(r or "").strip().startswith(("model:", "builtin:"))]

    def cap(key: str, default: int) -> int:
        try:
            return max(0, min(default, int(library.get(key))))
        except (TypeError, ValueError):
            return default

    return {"may_write": bool(library.get("may_write")), "assistants": out_assistants[:40], "templates": out_templates[:30],
            "preferred": list(dict.fromkeys(preferred))[:3], "max_create": cap("max_create", MAX_CREATE),
            "max_update": cap("max_update", MAX_UPDATE)}


# --- the lead's prompt ------------------------------------------------------------------------------

RULES = """- assistant：成员的「助手」给它一套专业设定（只提供设定；执行来源和模型照旧按 kind 和 model 决定）。按这个顺序考虑：
  1. 「你的助手库」里有专业对口的：填它的 ref（model:…）。同一个助手可以给多个成员。
  2. 「助手模板」里有贴切的：填它的编号或 ref（builtin:…）。
  3. 库里的助手领域对口、但缺少这类工作需要的通用能力（方法、检查步骤、输出格式、质量标准），而且它标了「可升级」：成员照常填它的 ref，再在 assistant_upgrades 里写一条它完整的新设定——保留它原有的全部能力，补上缺的部分。几位成员要同一个升级，只写一条。
  4. 都不合适，而这类工作以后还会遇到：在 new_assistants 里设计一个可复用的新助手，成员的 assistant 填 "new:<它的 key>"。新建前先看库里和模板里有没有领域重叠的，能选用或升级就不要新建。
  5. 只是这次的一个普通角色：填 null，在 role / focus 里写清楚它做什么。
- 这个目标的具体要求（题目细节、这次的分工、立场、文件名）只写进成员的 role / focus 和任务 description，绝不写进助手设定；助手设定只写以后同类工作也用得上的能力。
- 一个计划最多升级 {max_update} 个助手、新建 {max_create} 个。
- 新设定和升级后的设定（中文）写清：角色和专长；做事的方法（澄清目标、步骤、自查）；输出格式；质量标准（准确、具体、不知道就说不知道、不写空话）。150 到 500 字。新助手的 name 2 到 8 个汉字，点明专长；domain 是领域，2 到 6 个字。
- assistant_reason：一句话说明为什么这个助手适合这位成员（用了助手才写）。{no_write}{preferred}"""

NO_WRITE = "\n- 这位用户没有保存助手的权限：升级和新建只在这次协作里用，不会保存。仍然优先选用已有的。"

JSON_MEMBER = '"assistant": "model:… / builtin:… / 模板编号 / new:A1 / null", "assistant_reason": "一句话"'
JSON_TOP = ''',
  "assistant_upgrades": [{"ref": "model:…", "change": "一句话：升级后多了什么能力", "description": "可选：新的一句话说明", "system_prompt": "完整的新设定"}],
  "new_assistants": [{"key": "A1", "name": "名称", "emoji": "一个 emoji", "domain": "领域", "description": "一句话说明", "system_prompt": "完整设定", "from": "可选：参考的 builtin:… 模板"}]'''


def prompt_parts(library: dict) -> dict:
    """What system_prompt() puts in for a plan with the user's library."""
    preferred = ""
    if library["preferred"]:
        names = []
        for ref in library["preferred"]:
            entry = _library_entry(library, ref) or _template_entry(library, ref)
            names.append(f"{ref}（{entry['name']}）" if entry else ref)
        preferred = "\n- 用户点名要用这些助手，至少安排一位成员用它：" + "、".join(names)
    rules = (RULES.replace("{max_update}", str(library["max_update"])).replace("{max_create}", str(library["max_create"]))
             .replace("{no_write}", "" if library["may_write"] else NO_WRITE).replace("{preferred}", preferred))
    lines = []
    for a in library["assistants"]:
        head = f"- {a['ref']}：{a['emoji'] + ' ' if a['emoji'] else ''}{a['name']}" + (f"（{a['domain']}）" if a["domain"] else "")
        head += (f" — {a['description']}" if a["description"] else "") + ("｜可升级" if a["editable"] else "")
        lines.append(head + (f"\n  设定摘要：{a['prompt']}" if a["prompt"] else ""))
    collab = {t["id"] for t in templates_mod.catalog()}
    extra = [t for t in library["templates"] if t["id"] not in collab]
    template_lines = [f"- {t['ref']}：{t['name']} — {t['description']}" for t in extra]
    return {
        "rules": rules,
        "member_json": JSON_MEMBER,
        "top_json": JSON_TOP,
        "library": "\n".join(lines) or "（库里还没有助手）",
        "templates": "\n".join(template_lines),
    }


# --- reading the lead's answer -------------------------------------------------------------------

def _library_entry(library: dict, value: Any) -> Optional[dict]:
    key = str(value or "").strip()
    if not key:
        return None
    bare = key[len("model:"):] if key.startswith("model:") else key
    hit = next((a for a in library["assistants"] if a["ref"] == key or a["id"] == bare), None)
    return hit or next((a for a in library["assistants"] if a["name"].strip().lower() == key.lower()), None)


def _template_entry(library: Optional[dict], value: Any) -> Optional[dict]:
    """A template the lead named: the 「协作」 catalog, any built-in template, or one HaloWebUI sent."""
    found = templates_mod.resolve(value)
    if found:
        return found
    key = str(value or "").strip()
    if library and key.startswith("builtin:"):
        sent = next((t for t in library["templates"] if t["ref"] == key), None)
        if sent:
            return {"id": sent["id"], "name": sent["name"], "emoji": sent["emoji"], "kind": "",
                    "description": sent["description"], "prompt": ""}
    return None


def _template_choice(template: dict, reason: str = "", note: str = "") -> dict:
    out = {**(templates_mod.public(template) or {}), "action": "template"}
    if reason:
        out["reason"] = reason
    if note:
        out["note"] = note
    return out


class Choices:
    """One plan's assistant decisions while the validator reads the members."""

    def __init__(self, raw: dict, library: dict):
        self.library = library
        self.may_write = library["may_write"]
        self.proposals: dict[str, dict] = {}
        self.notes: dict[str, str] = {}  # proposal key → why it is not what the lead asked for
        self.counts = {"update": 0, "create": 0}
        self._upgrades(raw.get("assistant_upgrades"))
        self._new(raw.get("new_assistants"))

    def _upgrades(self, items: Any) -> None:
        for entry in items if isinstance(items, list) else []:
            if not isinstance(entry, dict):
                continue
            target = _library_entry(self.library, entry.get("ref") or entry.get("id") or entry.get("name"))
            system = _system(entry.get("system_prompt") or entry.get("system"))
            if target is None or len(system) < SYSTEM_MIN or target["ref"] in self.proposals:
                continue
            self.proposals[target["ref"]] = {
                "key": target["ref"], "ref": target["ref"], "name": target["name"], "emoji": target["emoji"],
                "domain": target["domain"], "description": _text(entry.get("description"), DESCRIPTION_MAX),
                "system_prompt": system, "change": _text(entry.get("change"), 300), "version": target["version"],
                "editable": target["editable"],
            }

    def _new(self, items: Any) -> None:
        names: set[str] = set()
        for index, entry in enumerate(items if isinstance(items, list) else [], 1):
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or f"A{index}").strip()[:12] or f"A{index}"
            name = _text(entry.get("name"), NAME_MAX)
            system = _system(entry.get("system_prompt") or entry.get("system"))
            if not name or len(system) < SYSTEM_MIN or f"new:{key}" in self.proposals or name.lower() in names:
                continue
            names.add(name.lower())
            source = str(entry.get("from") or "").strip()
            self.proposals[f"new:{key}"] = {
                "key": f"new:{key}", "name": name, "emoji": _emoji(entry.get("emoji")) or "✦",
                "domain": _text(entry.get("domain"), DOMAIN_MAX), "description": _text(entry.get("description"), DESCRIPTION_MAX),
                "system_prompt": system, "change": _text(entry.get("change"), 300),
                **({"from": source} if source.startswith("builtin:") and templates_mod.template(source) else {}),
            }

    def _activate(self, proposal: dict) -> bool:
        """Decide what a proposal becomes when a member first uses it (in member order, so the
        per-plan limits count only what members use). False: an upgrade over the limit (the member
        uses the assistant as it is)."""
        if proposal.get("action"):
            return True
        if proposal.get("ref"):  # an upgrade
            if not proposal.get("editable") or not self.may_write:
                proposal["action"] = "temporary"
                self.notes[proposal["key"]] = (f"没有修改「{proposal['name']}」的权限，本次临时补充设定" if not proposal.get("editable")
                                               else "没有保存助手的权限，升级只在这次协作里用")
            elif self.counts["update"] >= self.library["max_update"]:
                return False
            else:
                proposal["action"] = "update"
                self.counts["update"] += 1
            return True
        if not self.may_write:
            proposal["action"] = "temporary"
            self.notes[proposal["key"]] = "没有保存助手的权限，新助手只在这次协作里用"
        elif self.counts["create"] >= self.library["max_create"]:
            proposal["action"] = "temporary"
            self.notes[proposal["key"]] = f"这个计划已新建 {self.library['max_create']} 个助手，这个只在本次使用"
        else:
            proposal["action"] = "create"
            self.counts["create"] += 1
        return True

    def member(self, value: Any, reason: Any = None) -> tuple[Optional[dict], Optional[dict]]:
        """(the member's assistant, the template behind it — for its kind) from what the lead wrote."""
        reason_text = _text(reason, REASON_MAX)
        if isinstance(value, dict):
            value = value.get("ref") or value.get("id") or value.get("name")
        key = str(value or "").strip()
        if not key or key.lower() in ("null", "none"):
            return None, None
        if key.startswith("new:") or f"new:{key}" in self.proposals:
            proposal = self.proposals.get(key if key.startswith("new:") else f"new:{key}")
            if proposal is None:
                return None, None
            same = _library_entry(self.library, proposal["name"])
            if same is not None:  # the library already has one by that name: use it
                return self._use(same, reason_text, f"已有同名助手「{same['name']}」，直接用它"), None
            self._activate(proposal)
            return self._proposed(proposal, reason_text), None
        target = None if key.startswith("builtin:") else _library_entry(self.library, key)
        if target is not None:
            proposal = self.proposals.get(target["ref"])
            if proposal is not None and self._activate(proposal):
                return self._proposed(proposal, reason_text, target), None
            note = f"这个计划已升级 {self.library['max_update']} 个助手，这个直接使用" if proposal is not None else ""
            return self._use(target, reason_text, note), None
        template = _template_entry(self.library, key)
        if template is not None:
            return _template_choice(template, reason_text), template
        return None, None

    def _use(self, target: dict, reason: str, note: str = "") -> dict:
        out = {"ref": target["ref"], "id": target["id"], "name": target["name"], "emoji": target["emoji"],
               "description": target["description"], "domain": target["domain"], "version": target["version"],
               "action": "use"}
        if reason:
            out["reason"] = reason
        if note:
            out["note"] = note
        return out

    def _proposed(self, proposal: dict, reason: str, target: Optional[dict] = None) -> dict:
        out = {"ref": proposal.get("ref") or "", "id": target["id"] if target else "", "name": proposal["name"],
               "emoji": proposal["emoji"], "description": proposal["description"] or (target or {}).get("description") or "",
               "domain": proposal["domain"], "action": proposal["action"], "proposal": proposal["key"]}
        if target is not None:
            out["version"] = target["version"]
        if reason:
            out["reason"] = reason
        if self.notes.get(proposal["key"]):
            out["note"] = self.notes[proposal["key"]]
        return out

    def finish(self, members: list[dict], tasks: list[dict]) -> list[dict]:
        """Give each preferred assistant to a member if the lead left it out, and return the
        proposals some member still uses."""
        for ref in self.library["preferred"]:
            if any((m.get("assistant") or {}).get("ref") == ref for m in members):
                continue
            target = _library_entry(self.library, ref) if ref.startswith("model:") else None
            template = None if target else _template_entry(self.library, ref)
            if target is None and template is None:
                continue
            entry = target or template
            member = best_member(members, tasks, f"{entry['name']} {entry.get('domain') or ''} {entry.get('description') or ''}")
            if member is None:
                continue
            reason = "你指定这个助手参加协作"
            member["assistant"] = self._use(target, reason) if target else _template_choice(template, reason)
            member["assistant_preferred"] = True
        return stored_proposals([p for p in self.proposals.values() if p.get("action")], members)


# --- the preferred assistant's member ------------------------------------------------------------

_CJK = re.compile(r"[㐀-鿿]+")
_WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]{1,}")


def _grams(text: str) -> set[str]:
    text = str(text or "").lower()
    grams = set(_WORD.findall(text))
    for run in _CJK.findall(text):
        if len(run) == 1:
            grams.add(run)
        grams.update(run[i:i + 2] for i in range(len(run) - 1))
    return grams


def best_member(members: list[dict], tasks: list[dict], about: str) -> Optional[dict]:
    """The member whose work is closest to ``about``; one without an assistant (or with a plain
    template) before one whose assistant the lead designed; never an image member when another
    can take it."""
    query = _grams(about)
    best, best_score = None, None
    for m in members:
        if m.get("assistant_preferred"):
            continue
        work = " ".join([m.get("role") or "", m.get("focus") or ""] + [t["title"] for t in tasks if t["member"] == m["name"]])
        action = (m.get("assistant") or {}).get("action")
        score = 2 * len(query & _grams(work))
        score += 3 if not m.get("assistant") else (1 if action == "template" else 0)
        score -= 2 if action in PROPOSAL_ACTIONS else 0
        score -= 6 if m.get("kind") == "image" else 0
        if best_score is None or score > best_score:
            best, best_score = m, score
    return best


# --- a stored plan (validated again before it starts, or when its runners are re-resolved) ---------

def stored_member(value: Any) -> Optional[dict]:
    """A member's recorded assistant as it is (already decided by an earlier validation)."""
    if not isinstance(value, dict) or value.get("action") not in ACTIONS:
        return None
    out = {
        "ref": str(value.get("ref") or "")[:220], "id": str(value.get("id") or "")[:200],
        "name": _text(value.get("name"), 60), "emoji": _emoji(value.get("emoji")),
        "description": _text(value.get("description"), DESCRIPTION_MAX), "action": value["action"],
    }
    for key, limit in (("domain", DOMAIN_MAX), ("reason", REASON_MAX), ("note", 200), ("proposal", 230), ("kind", 20)):
        if value.get(key):
            out[key] = _text(value.get(key), limit)
    if isinstance(value.get("version"), int):
        out["version"] = value["version"]
    return out


def stored_proposals(raw: Any, members: list[dict]) -> list[dict]:
    used = {(m.get("assistant") or {}).get("proposal") for m in members}
    out = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or entry.get("key") not in used or entry.get("action") not in PROPOSAL_ACTIONS:
            continue
        clean = {k: entry.get(k) for k in ("key", "action", "ref", "name", "emoji", "domain", "description",
                                           "change", "from", "version") if entry.get(k) not in (None, "")}
        clean["system_prompt"] = _system(entry.get("system_prompt"))
        out.append(clean)
    return out


def for_lead(plan: dict) -> dict:
    """A previous plan's assistant decisions the way the lead writes them (a re-plan keeps them)."""
    upgrades, new = [], []
    for p in plan.get("assistant_proposals") or []:
        if not isinstance(p, dict):
            continue
        if p.get("ref"):
            upgrades.append({"ref": p["ref"], "change": p.get("change") or "", "system_prompt": p.get("system_prompt") or ""})
        elif str(p.get("key") or "").startswith("new:"):
            new.append({"key": p["key"][4:], "name": p.get("name"), "emoji": p.get("emoji"), "domain": p.get("domain"),
                        "description": p.get("description"), "system_prompt": p.get("system_prompt") or ""})
    return {**({"assistant_upgrades": upgrades} if upgrades else {}), **({"new_assistants": new} if new else {})}


def lead_value(assistant: Any) -> Any:
    """How the lead refers to a member's recorded assistant."""
    if not isinstance(assistant, dict):
        return assistant
    proposal = str(assistant.get("proposal") or "")
    if proposal.startswith("new:"):
        return proposal
    return assistant.get("ref") or assistant.get("id")

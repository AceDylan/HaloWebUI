"""协作 with a 辅助决策模型 (utils/decision_model.py).

The lead (Hermes) writes the plan: members with roles, tasks, new or upgraded assistants — the
text. The user's decision model then picks, for what is still automatic, each member's executor
(from the runners available now), model (from Hermes' models) and assistant (the lead's pick, or
one of the library shortlist sent with the plan request). Hermes applies the picks and validates
the plan again (``POST /plan/decide``), so the runner chains, the user's own choices and the
approval step stay as they are. Any failure keeps the lead's plan.
"""

from __future__ import annotations

from typing import Any, Optional

from open_webui.utils import decision_model as dm

MEMBER_ASSISTANTS = 6
MEMBER_TEMPLATES = 3


def _text(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def decision_request(goal: str, plan: dict, options: dict, library: Optional[dict]) -> tuple[dict, dict, dict]:
    """(state, questions, keys) — keys[question id] = (member name, field, {option key: value})."""
    executors = [e for e in options.get("executors") or [] if isinstance(e, dict) and e.get("available")]
    models = [m for m in options.get("models") or [] if isinstance(m, dict) and m.get("model")]
    shelf = []
    if library:
        shelf += [("a", a) for a in (library.get("assistants") or [])[:MEMBER_ASSISTANTS]]
        shelf += [("t", t) for t in (library.get("templates") or [])[:MEMBER_TEMPLATES]]
    questions: dict = {}
    keys: dict = {}
    members_state = []
    tasks = [t for t in plan.get("tasks") or [] if isinstance(t, dict)]
    for index, member in enumerate([m for m in plan.get("members") or [] if isinstance(m, dict)], 1):
        name = member.get("name") or f"member{index}"
        about = f"member {index} «{_text(member.get('role'), 40)}»"
        members_state.append({
            "member": index, "role": member.get("role"), "focus": member.get("focus"), "kind": member.get("kind"),
            "tasks": [_text(t.get("title"), 80) for t in tasks if t.get("member") == name],
        })
        if member.get("kind") != "image" and member.get("executor_source") not in ("goal", "user") and len(executors) >= 2:
            values = {f"e{i}": e["name"] for i, e in enumerate(executors, 1)}
            questions[f"exec_{index}"] = dm.choice(
                f"Which executor should run the tasks of {about}?",
                {k: _text(f"{e['label']}: {e.get('note') or ''}" + (" (the usual one for this kind of task)" if e["name"] == member.get("recommended") else ""), 300)
                 for k, e in zip(values, executors)},
            )
            keys[f"exec_{index}"] = (name, "executor", values)
        if member.get("model_source") != "user" and len(models) >= 2:
            values = {f"o{i}": m["model"] for i, m in enumerate(models[: dm.MAX_OPTIONS], 1)}
            questions[f"model_{index}"] = dm.choice(
                f"Which model should {about} run on when Hermes executes it?",
                {k: _text(f"{m['model']}" + (f": {m['hint']}" if m.get("hint") else "") + (" (default)" if m.get("default") else ""), 300)
                 for k, m in zip(values, models)},
            )
            keys[f"model_{index}"] = (name, "model", values)
        if shelf and not member.get("assistant_preferred"):
            current = member.get("assistant") if isinstance(member.get("assistant"), dict) else None
            keep = (f"Keep the lead's pick: {current.get('name') or current.get('ref')} ({current.get('action')})"
                    if current else "Keep the lead's plan: no assistant, the role as written")
            values = {"keep": ""}
            texts = {"keep": _text(keep, 300)}
            for i, (prefix, entry) in enumerate(shelf, 1):
                values[f"{prefix}{i}"] = entry.get("ref") or ""
                texts[f"{prefix}{i}"] = _text(f"{entry.get('name')} — {entry.get('description') or entry.get('domain') or ''}"
                                              + (" (template)" if prefix == "t" else ""), 300)
            questions[f"assistant_{index}"] = dm.choice(f"Which assistant profile fits {about} best?", texts)
            keys[f"assistant_{index}"] = (name, "assistant", values)
    state = {"goal": _text(goal, 4000), "plan": _text(plan.get("summary"), 400), "members": members_state}
    return state, questions, keys


def picks_from_answers(answers: dict, keys: dict, plan: dict, reason: str) -> dict:
    """{member: {executor?, model?, assistant?, reason}} — only what differs from the plan."""
    members = {m.get("name"): m for m in plan.get("members") or [] if isinstance(m, dict)}
    picks: dict = {}
    for qid, (name, field, values) in keys.items():
        value = values[answers[qid]["choice"]]
        member = members.get(name) or {}
        current = (member.get("assistant") or {}).get("ref") if field == "assistant" else member.get(field)
        if not value or value == current:
            continue
        picks.setdefault(name, {"reason": reason})[field] = value
    return picks


async def assist(request, user, target, team, plan: dict, options: Optional[dict], library: Optional[dict]) -> dict:
    """The plan after the decision model's picks (validated again by Hermes); the lead's plan
    when no model is set or anything fails. The plan carries the trace as ``decider``."""
    from open_webui.utils.agent_teams import CALL_TIMEOUT_SECONDS, TeamsError, hermes_call

    async def run(decider):
        if not isinstance(options, dict):
            raise dm.DecisionError("Hermes 没有给出可选的执行器和模型")
        state, questions, keys = decision_request(team.goal, plan, options, library)
        if not questions:
            return plan, {"picks": {}, "note": "成员的执行器、模型和助手都已指定"}
        answers, reason = await decider.judge(state, questions)
        picks = picks_from_answers(answers, keys, plan, reason or f"{decider.name} 的判断")
        if not picks:
            return plan, {"picks": {}}
        try:
            body = await hermes_call(target, "POST", "/plan/decide", json_body={"plan": plan, "picks": picks, "library": library},
                                     timeout=CALL_TIMEOUT_SECONDS)
        except TeamsError as exc:
            raise dm.DecisionError(f"Hermes 没有接受决策后的计划：{str(exc.detail)[:120]}")
        if not isinstance(body, dict) or not body.get("ok") or not isinstance(body.get("plan"), dict):
            raise dm.DecisionError("Hermes 没有接受决策后的计划")
        return body["plan"], {"picks": {m: {k: v for k, v in p.items() if k != "reason"} for m, p in picks.items()}}

    decided, trace = await dm.decide(request, user, "team", run)
    out = decided if decided is not None else plan
    if trace:
        out = {**out, "decider": trace}
    return out

"""Bounded, connection-scoped model facts for the discussion planner.

Never infer a concrete version or capabilities from a chat alias. Operators maintain
``info.meta.discussion_profile`` on the actual model record; the existing model
description is also included, so it remains editable in Workspace → Models.
"""


def _text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def planning_profile(model: dict) -> dict:
    info = model.get("info") if isinstance(model.get("info"), dict) else {}
    meta = info.get("meta") if isinstance(info.get("meta"), dict) else {}
    raw = meta.get("discussion_profile")
    raw = raw if isinstance(raw, dict) else {}
    profile = {"version": _text(raw.get("version"), 120) or "unknown"}
    for key, limit in (("family", 60), ("version_source", 240), ("verified_at", 32),
                       ("capability_source", 240)):
        value = _text(raw.get(key), limit)
        if value:
            profile[key] = value
    description = _text(meta.get("description"), 600)
    if description:
        profile["description"] = description
    for key in ("strengths", "suggested_roles", "limitations"):
        values = raw.get(key)
        if isinstance(values, list):
            cleaned = [_text(v, 160) for v in values[:6]]
            if any(cleaned):
                profile[key] = [v for v in cleaned if v]
    context = raw.get("context_window")
    if type(context) is int and 0 < context <= 10_000_000:
        profile["context_window"] = context
    # A profile cannot override operational flags or expose arbitrary metadata.
    return profile

"""Merge a client's changes against its last server snapshot.

Unchanged fields never overwrite newer server state. Conflicting edits to the
same scalar keep the server value; independent messages/fields are merged.
"""

from copy import deepcopy

_MISSING = object()


def merge_chat_snapshot(current, incoming, base, key=""):
    if incoming == base:
        return deepcopy(current) if current is not _MISSING else _MISSING
    if current == base:
        return deepcopy(incoming) if incoming is not _MISSING else _MISSING
    if isinstance(current, dict) and isinstance(incoming, dict):
        base = base if isinstance(base, dict) else {}
        result = deepcopy(current)
        for field in incoming.keys() | base.keys():
            value = merge_chat_snapshot(
                current.get(field, _MISSING),
                incoming.get(field, _MISSING),
                base.get(field, _MISSING),
                field,
            )
            if value is _MISSING:
                result.pop(field, None)
            else:
                result[field] = value
        return result
    if (
        key == "childrenIds"
        and isinstance(current, list)
        and isinstance(incoming, list)
    ):
        base = base if isinstance(base, list) else []
        # Preserve both concurrent branches, including deliberate removals.
        return list(
            dict.fromkeys(
                [item for item in current if item not in base or item in incoming]
                + [item for item in incoming if item not in base]
            )
        )
    if key == "files" and isinstance(current, list) and isinstance(incoming, list):

        def file_map(files):
            return {
                str(item.get("id") or item.get("url") or item): item
                for item in files
                if isinstance(item, dict)
            }

        return list(
            merge_chat_snapshot(
                file_map(current),
                file_map(incoming),
                file_map(base) if isinstance(base, list) else {},
            ).values()
        )
    return deepcopy(current) if current is not _MISSING else _MISSING

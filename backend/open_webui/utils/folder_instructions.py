"""A folder's instructions (分组指令) ride along with every chat filed in it.

The person writes them once on the folder (sidebar folder menu → 分组指令);
each completion of a chat in that folder, or in a folder below it, starts with
them. Outer folders come first, so a sub-folder narrows its parent's context
instead of replacing it. They sit after the assistant's own setting and before
the person's personal system prompt (`add_or_update_system_message` prepends,
and the provider routers prepend the assistant's setting afterwards).

Only the chat's `folder_id` column is read, never the chat JSON: this runs on
every completion and long chats are megabytes.
"""

import logging
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.chats import Chat
from open_webui.models.folders import Folder
from open_webui.utils.misc import add_or_update_system_message
from open_webui.utils.task import prompt_variables_template

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

# Folders nest a few levels at most; the cap only guards a parent cycle.
MAX_FOLDER_DEPTH = 8
MAX_INSTRUCTIONS_CHARS = 20_000


def folder_instructions_for_chat(chat_id: Optional[str], user_id: str) -> Optional[str]:
    if not chat_id or not user_id or chat_id.startswith("local:"):
        return None
    try:
        with get_db() as db:
            folder_id = (
                db.query(Chat.folder_id)
                .filter(Chat.id == chat_id, Chat.user_id == user_id)
                .scalar()
            )
            parts: list[str] = []
            seen: set[str] = set()
            while folder_id and folder_id not in seen and len(seen) < MAX_FOLDER_DEPTH:
                seen.add(folder_id)
                row = (
                    db.query(Folder.parent_id, Folder.system_prompt)
                    .filter(Folder.id == folder_id, Folder.user_id == user_id)
                    .first()
                )
                if row is None:
                    break
                text = (row.system_prompt or "").strip()
                if text:
                    parts.append(text)
                folder_id = row.parent_id
    except Exception as e:
        log.warning(f"folder instructions lookup failed for chat {chat_id}: {e}")
        return None

    if not parts:
        return None
    return "\n\n".join(reversed(parts))[:MAX_INSTRUCTIONS_CHARS]


# inplace function: form_data is modified
def apply_folder_instructions_to_body(
    form_data: dict, metadata: Optional[dict], user_id: str
) -> dict:
    instructions = folder_instructions_for_chat((metadata or {}).get("chat_id"), user_id)
    if not instructions:
        return form_data

    variables = (metadata or {}).get("variables") or {}
    if variables:
        instructions = prompt_variables_template(instructions, variables)

    form_data["messages"] = add_or_update_system_message(
        instructions, form_data.get("messages") or []
    )
    return form_data

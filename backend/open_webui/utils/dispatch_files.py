"""Attachments handed from the active chat request to answer, discussion or team."""

from open_webui.utils.chat_image_refs import extract_chat_image_file_id


def message_file_ids(metadata: dict) -> list[str]:
    out = []
    for item in (metadata or {}).get("files") or []:
        if not isinstance(item, dict) or item.get("type") not in (None, "file", "image"):
            continue
        nested = item.get("file") if isinstance(item.get("file"), dict) else {}
        file_id = str(item.get("id") or nested.get("id") or "").strip()
        file_id = file_id or extract_chat_image_file_id(item.get("url"))
        if file_id and file_id not in out:
            out.append(file_id)
    return out


def conversation_file_ids(metadata: dict, messages) -> list[str]:
    # The composer already sends the current document selection in metadata. Do
    # not revive removed documents or scan other branches in the stored chat.
    out = message_file_ids(metadata)
    # Pictures instead travel in user message content, including earlier turns.
    for message in messages or []:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            ref = part.get("image_url")
            url = ref.get("url") if isinstance(ref, dict) else ref
            file_id = extract_chat_image_file_id(url)
            if file_id and file_id not in out:
                out.append(file_id)
    return out

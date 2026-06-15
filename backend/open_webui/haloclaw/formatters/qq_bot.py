"""Convert markdown-formatted LLM output to QQ Bot text format.

QQ official bot group / C2C text messages (msg_type=0) support plain text only
(rich markdown needs templates and extra permissions). We convert markdown to a
readable plain-text representation, mirroring the WeChat Work formatter.
"""

import re

# QQ Bot single text message content limit (conservative; passive replies are
# also rate-limited per received msg_id, so we keep chunks reasonably large to
# minimise the number of outbound messages).
MAX_MESSAGE_LENGTH = 1000


def markdown_to_qq_text(text: str) -> str:
    """Convert markdown to readable plain text for QQ Bot."""
    # Code blocks: drop the language hint but keep the fenced body readable.
    text = re.sub(
        r"```\w*\n(.*?)```",
        lambda m: f"```\n{m.group(1)}```",
        text,
        flags=re.DOTALL,
    )

    # Bold → Chinese emphasis markers
    text = re.sub(r"\*\*(.+?)\*\*", r"【\1】", text)
    text = re.sub(r"__(.+?)__", r"【\1】", text)

    # Italic → strip markers
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)

    # Strikethrough → strip markers
    text = re.sub(r"~~(.+?)~~", r"\1", text)

    # Links: [text](url) → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Headers → emphasis markers
    text = re.sub(r"^#{1,6}\s+(.+)$", r"【\1】", text, flags=re.MULTILINE)

    # Bullet lists → bullet char
    text = re.sub(r"^[\-\*]\s+", "• ", text, flags=re.MULTILINE)

    return text


def split_message(text: str) -> list[str]:
    """Split a message into chunks fitting QQ Bot's content limit."""
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    chunks = []
    while text:
        if len(text) <= MAX_MESSAGE_LENGTH:
            chunks.append(text)
            break

        # Try splitting at paragraph boundary
        cut = text.rfind("\n\n", 0, MAX_MESSAGE_LENGTH)
        if cut == -1:
            cut = text.rfind("\n", 0, MAX_MESSAGE_LENGTH)
        if cut == -1:
            cut = MAX_MESSAGE_LENGTH

        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")

    return chunks

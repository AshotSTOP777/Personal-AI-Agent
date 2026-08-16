from __future__ import annotations

import re

TELEGRAM_MESSAGE_LIMIT = 4096

_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_CODE_RE = re.compile(r"`+")
_BOLD_ITALIC_RE = re.compile(r"[*_]{1,3}")


def strip_markdown(text: str) -> str:
    """Убирает базовую markdown-разметку (**bold**, `code`, ## heading), чтобы ответы
    в Telegram оставались обычным текстом без декоративных символов."""
    text = _HEADING_RE.sub("", text)
    text = _CODE_RE.sub("", text)
    text = _BOLD_ITALIC_RE.sub("", text)
    return text


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Разбивает длинный текст на части, не превышающие лимит Telegram, по границам строк."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
        current += line
    if current:
        chunks.append(current)
    return chunks

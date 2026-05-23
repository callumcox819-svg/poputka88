"""Разбивка длинных HTML-сообщений под лимит Telegram (~4096)."""

from __future__ import annotations


def chunk_html_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            parts.append(rest)
            break
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 3:
            cut = limit
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return parts

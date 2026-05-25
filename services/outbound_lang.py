"""Проверка языка исходящих писем продавцам."""

from __future__ import annotations

import re

_CYRILLIC = re.compile(r"[\u0400-\u04FF]")

SELLER_RUSSIAN_FORBIDDEN = (
    "Продавцам нельзя писать на русском. Используйте DE/EN, пресет или HTML."
)


def seller_outbound_text_error(text: str) -> str | None:
    """None — можно отправлять; иначе текст ошибки."""
    if not (text or "").strip():
        return None
    if _CYRILLIC.search(text):
        return SELLER_RUSSIAN_FORBIDDEN
    return None

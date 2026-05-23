"""Очистка секретов из текста сообщений."""

from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")


def clean_secret(value: str | None) -> str:
    s = (value or "").strip()
    s = _WS_RE.sub("", s)
    return s.strip()

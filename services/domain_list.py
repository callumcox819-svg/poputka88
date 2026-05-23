"""Домены для валидации (приоритет из настроек)."""

from __future__ import annotations

import json
import re

from services.user_settings import get_setting

DOMAIN_PRIORITY_KEY = "domain_priority"


async def get_validation_domains(user_id: int) -> list[str]:
    raw = await get_setting(user_id, DOMAIN_PRIORITY_KEY)
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        d = re.sub(r"^https?://", "", str(x).strip().lower())
        d = d.split("/")[0].strip()
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out

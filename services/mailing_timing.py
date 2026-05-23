"""Тайминги рассылки MIN/MAX/пачка — как в happy88."""

from __future__ import annotations

import json

from services.user_settings import get_setting, set_setting

_TIMING_KEY = "mailing_timing"


async def load_timing(user_id: int, default_delay: float = 2.0) -> dict:
    raw = await get_setting(user_id, _TIMING_KEY)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {
                    "min": float(data.get("min", default_delay)),
                    "max": float(data.get("max", default_delay)),
                    "batch_size": int(data.get("batch_size", 3)),
                }
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return {"min": default_delay, "max": default_delay, "batch_size": 3}


async def save_timing(user_id: int, mn: float, mx: float, batch_size: int) -> None:
    await set_setting(
        user_id,
        _TIMING_KEY,
        json.dumps({"min": mn, "max": mx, "batch_size": batch_size}),
    )

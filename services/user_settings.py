"""Настройки пользователя key-value (per Telegram user_id)."""

from __future__ import annotations

from services.db_backend import db_connect

TOGGLE_KEYS = frozenset({"smart_mode", "spoofing", "block_control"})
SPOOF_SUBJECT_KEY = "spoof_subject"
SPOOF_FROM_NAME_KEY = "spoof_from_name"


async def get_setting(user_id: int, key: str) -> str | None:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, key),
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def set_setting(user_id: int, key: str, value: str) -> None:
    async with db_connect() as db:
        await db.execute(
            """
            INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
            """,
            (user_id, key, value),
        )
        await db.commit()


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


async def get_bool(user_id: int, key: str, default: bool = False) -> bool:
    return parse_bool(await get_setting(user_id, key), default)


async def toggle_bool(user_id: int, key: str) -> bool:
    cur = await get_bool(user_id, key, False)
    new = not cur
    await set_setting(user_id, key, "1" if new else "0")
    return new


async def get_toggle_flags(user_id: int) -> dict[str, bool]:
    return {
        "smart_mode": await get_bool(user_id, "smart_mode", False),
        "spoofing": await get_bool(user_id, "spoofing", False),
        "block_control": await get_bool(user_id, "block_control", False),
    }

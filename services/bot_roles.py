"""Роли: ADMIN_IDS из config + is_admin в bot_users."""

from __future__ import annotations

from config import Settings, load_settings
from services.bot_users import get_or_create_bot_user, set_bot_user_flags


def config_admin_ids(settings: Settings | None = None) -> frozenset[int]:
    s = settings or load_settings()
    return s.admin_ids


async def user_is_admin(telegram_id: int, settings: Settings | None = None) -> bool:
    tg_id = int(telegram_id)
    if tg_id in config_admin_ids(settings):
        return True
    u = await get_or_create_bot_user(tg_id)
    if bool(int(u.get("is_banned") or 0)):
        return False
    if bool(int(u.get("is_admin") or 0)):
        if not bool(int(u.get("access_granted") or 0)):
            await set_bot_user_flags(tg_id, access_granted=True)
        return True
    return False

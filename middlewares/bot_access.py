"""Доступ к боту: access_granted в БД или ADMIN_IDS (как happy88)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, TelegramObject

from config import Settings
from keyboards.main_menu import is_main_menu_text
from services.bot_roles import config_admin_ids
from services.bot_users import get_or_create_bot_user, set_bot_user_flags

logger = logging.getLogger(__name__)

_ACCESS_CACHE: dict[int, tuple[bool, bool, float]] = {}
_ACCESS_CACHE_TTL_SEC = 25.0
_ACCESS_DB_TIMEOUT_SEC = 8.0

ACCESS_DENIED_TEXT = (
    "⛔ У тебя нет доступа к этому боту.\n"
    "Напиши администратору — он выдаст доступ через админ-панель."
)


def invalidate_access_cache(telegram_id: int | None = None) -> None:
    if telegram_id is None:
        _ACCESS_CACHE.clear()
        return
    _ACCESS_CACHE.pop(int(telegram_id), None)


def _is_start_message(event: TelegramObject) -> bool:
    if not isinstance(event, Message):
        return False
    return (event.text or "").strip().startswith("/start")


def _is_admin_panel_message(event: TelegramObject) -> bool:
    if not isinstance(event, Message):
        return False
    t = (event.text or "").strip()
    return t in {"👑 Админ-панель", "🔥 Админ-панель", "/admin"}


async def _resolve_access(telegram_id: int, settings: Settings) -> tuple[bool, bool]:
    tg_id = int(telegram_id)
    if tg_id in config_admin_ids(settings):
        return True, True

    now = time.monotonic()
    cached = _ACCESS_CACHE.get(tg_id)
    if cached and (now - cached[2]) < _ACCESS_CACHE_TTL_SEC:
        return cached[0], cached[1]

    u = await get_or_create_bot_user(tg_id)
    if bool(int(u.get("is_banned") or 0)):
        is_admin, has_access = False, False
    else:
        is_admin = bool(int(u.get("is_admin") or 0))
        if is_admin and not bool(int(u.get("access_granted") or 0)):
            await set_bot_user_flags(tg_id, access_granted=True)
        has_access = is_admin or bool(int(u.get("access_granted") or 0))

    _ACCESS_CACHE[tg_id] = (is_admin, has_access, now)
    return is_admin, has_access


async def deny_access_message(message: Message) -> None:
    await message.answer(ACCESS_DENIED_TEXT, reply_markup=ReplyKeyboardRemove())


class BotAccessMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        if isinstance(event, Message):
            if getattr(user, "is_bot", False):
                return await handler(event, data)
            if _is_start_message(event) or _is_admin_panel_message(event):
                return await handler(event, data)

        try:
            is_admin, has_access = await asyncio.wait_for(
                _resolve_access(int(user.id), self._settings),
                timeout=_ACCESS_DB_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.error("BotAccessMiddleware DB timeout tg=%s", user.id)
            if isinstance(event, Message) and (
                _is_start_message(event) or is_main_menu_text(event.text)
            ):
                return await handler(event, data)
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(
                        "⏳ База занята, попробуйте через 5 сек.", show_alert=True
                    )
                except Exception:
                    pass
            return None

        data["is_admin"] = is_admin
        data["has_bot_access"] = has_access

        if is_admin or has_access:
            return await handler(event, data)

        if isinstance(event, Message):
            await deny_access_message(event)
            return None

        if isinstance(event, CallbackQuery):
            try:
                await event.answer(ACCESS_DENIED_TEXT, show_alert=True)
            except Exception:
                pass
            return None

        return None

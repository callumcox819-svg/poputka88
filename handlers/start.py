from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from keyboards.main_menu import main_menu_kb_for
from middlewares.bot_access import deny_access_message
from services.bot_commands import BOTFATHER_COMMANDS_TEXT
from services.bot_roles import config_admin_ids
from services.bot_users import get_or_create_bot_user, set_bot_user_flags

router = Router()
logger = logging.getLogger(__name__)

_START_DB_TIMEOUT_SEC = float(os.getenv("START_DB_TIMEOUT_SEC", "12"))

WELCOME = (
    "👋 Привет! Это бот для массовой рассылки по email.\n\n"
    "Основные команды:\n"
    "/send — запустить рассылку\n"
    "/stop — остановить рассылку\n"
    "/stat — статус рассылки\n"
    "/imap_check — входящие по IMAP\n"
    "Перешлите или отправьте <b>JSON</b> void-parser — проверка начнётся сразу.\n"
    "/stopcheck — остановить проверку\n"
    "/test_mail — тест отправки и симуляция входящего\n\n"
    "⚙️ Настройки — аккаунты, задержка.\n"
    "⚡ Быстрое добавление — имя отправителя и почты <code>email:пароль</code>."
)


async def _start_load_user(tg_id: int) -> tuple[bool, bool, bool]:
    """(is_banned, is_admin, has_access)."""
    u = await get_or_create_bot_user(tg_id)
    if bool(int(u.get("is_banned") or 0)):
        return True, False, False
    is_admin = bool(int(u.get("is_admin") or 0))
    if is_admin and not bool(int(u.get("access_granted") or 0)):
        await set_bot_user_flags(tg_id, access_granted=True)
    has_access = is_admin or bool(int(u.get("access_granted") or 0))
    return False, is_admin, has_access


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    tg_id = int(message.from_user.id)

    if tg_id in config_admin_ids():
        await message.answer(WELCOME, reply_markup=await main_menu_kb_for(tg_id), parse_mode="HTML")
        return

    try:
        is_banned, is_admin, has_access = await asyncio.wait_for(
            _start_load_user(tg_id),
            timeout=_START_DB_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.error("/start DB timeout tg=%s", tg_id)
        await message.answer(
            "⏳ База не отвечает. Подожди 15 сек и снова /start.",
            parse_mode="HTML",
        )
        return
    except Exception:
        logger.exception("/start failed tg=%s", tg_id)
        await message.answer("❌ Ошибка БД. Попробуй /start через 10 сек.")
        return

    if is_banned:
        await message.answer(
            "⛔ Вы заблокированы администратором.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if not has_access:
        await deny_access_message(message)
        return

    await message.answer(
        WELCOME,
        reply_markup=await main_menu_kb_for(tg_id),
        parse_mode="HTML",
    )


@router.message(Command("commands_help"))
async def cmd_commands_help(message: Message) -> None:
    await message.answer(
        "Вставьте в @BotFather → Edit Commands:\n\n"
        f"<pre>{BOTFATHER_COMMANDS_TEXT}</pre>",
        parse_mode="HTML",
    )

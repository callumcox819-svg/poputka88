"""Регистрация слэш-команд в меню Telegram."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BotCommand, MenuButtonCommands

logger = logging.getLogger(__name__)

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Запуск бота и меню"),
    BotCommand(command="send", description="Запустить рассылку"),
    BotCommand(command="stop", description="Остановить рассылку"),
    BotCommand(command="validate", description="Валидация JSON / email"),
    BotCommand(command="stopcheck", description="Остановить проверку"),
    BotCommand(command="imap_check", description="Проверка входящих IMAP"),
    BotCommand(command="stat", description="Статус рассылки"),
]


async def register_bot_commands(bot: Bot, *, chat_id: int | None = None) -> None:
    """
    Один запрос setMyCommands (без десятков языков) — иначе Telegram flood limit.
    """
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        if chat_id is not None:
            await bot.set_chat_menu_button(
                chat_id=chat_id,
                menu_button=MenuButtonCommands(),
            )
        current = await bot.get_my_commands()
        logger.info(
            "Commands OK: %s",
            ", ".join(f"/{c.command}" for c in current) or "(empty)",
        )
    except TelegramRetryAfter as exc:
        wait = int(getattr(exc, "retry_after", 60) or 60)
        logger.warning(
            "Пропуск setMyCommands (flood %s сек). Бот работает; команды — в @BotFather.",
            wait,
        )


# Текст для ручной вставки в @BotFather → /setcommands
BOTFATHER_COMMANDS_TEXT = """start - Запуск бота и меню
send - Запустить рассылку
stop - Остановить рассылку
validate - Валидация JSON / email
stopcheck - Остановить проверку
imap_check - Проверка входящих IMAP
stat - Статус рассылки"""

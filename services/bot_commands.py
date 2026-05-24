"""Регистрация слэш-команд в меню Telegram."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BotCommand, MenuButtonCommands

logger = logging.getLogger(__name__)

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Запуск бота и меню"),
    BotCommand(command="send", description="Рассылка (после /reset — только новые)"),
    BotCommand(command="sendall", description="Рассылка по всей БД"),
    BotCommand(command="stop", description="Остановить рассылку"),
    BotCommand(command="stopcheck", description="Остановить проверку JSON"),
    BotCommand(command="imap_check", description="Проверка входящих IMAP"),
    BotCommand(command="stat", description="Статус рассылки"),
    BotCommand(command="reset", description="Очистить очередь рассылки"),
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
send - Рассылка (после /reset — только новые)
sendall - Рассылка по всей БД
stop - Остановить рассылку
stopcheck - Остановить проверку JSON
imap_check - Проверка входящих IMAP
stat - Статус рассылки
reset - Очистить очередь рассылки"""

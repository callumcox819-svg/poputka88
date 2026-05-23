"""Регистрация слэш-команд в меню Telegram."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

logger = logging.getLogger(__name__)

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Запуск бота и меню"),
    BotCommand(command="send", description="Запустить рассылку"),
    BotCommand(command="stop", description="Остановить рассылку"),
    BotCommand(command="stopcheck", description="Остановить проверку почт"),
    BotCommand(command="imap_check", description="Проверка входящих IMAP"),
]

# Языки, которые могли быть заданы в BotFather
_LANGS = ("ru", "en", "uk", "de", "fr", "es", "it", "pt", "tr")

_SCOPES = (
    BotCommandScopeDefault(),
    BotCommandScopeAllPrivateChats(),
)


async def _clear_commands(bot: Bot, scope) -> None:
    try:
        await bot.delete_my_commands(scope=scope)
    except Exception as exc:
        logger.debug("delete scope %s: %s", scope, exc)
    for lang in _LANGS:
        try:
            await bot.delete_my_commands(scope=scope, language_code=lang)
        except Exception as exc:
            logger.debug("delete scope %s lang %s: %s", scope, lang, exc)


async def _set_commands(bot: Bot, scope) -> None:
    await bot.set_my_commands(BOT_COMMANDS, scope=scope)
    for lang in _LANGS:
        await bot.set_my_commands(BOT_COMMANDS, scope=scope, language_code=lang)


async def register_bot_commands(bot: Bot, *, chat_id: int | None = None) -> None:
    """
    1. Удалить старые команды (в т.ч. из BotFather).
    2. Записать новые для default / private / чата.
    3. Кнопка меню = список команд (не Mini App).
    """
    for scope in _SCOPES:
        await _clear_commands(bot, scope)
        await _set_commands(bot, scope)

    if chat_id is not None:
        scope = BotCommandScopeChat(chat_id=chat_id)
        await _clear_commands(bot, scope)
        await _set_commands(bot, scope)
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=MenuButtonCommands(),
        )

    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    current = await bot.get_my_commands(language_code="ru")
    if not current:
        current = await bot.get_my_commands()
    logger.info(
        "Commands OK: %s",
        ", ".join(f"/{c.command}" for c in current) or "(empty)",
    )


# Текст для ручной вставки в @BotFather → /setcommands
BOTFATHER_COMMANDS_TEXT = """start - Запуск бота и меню
send - Запустить рассылку
stop - Остановить рассылку
stopcheck - Остановить проверку почт
imap_check - Проверка входящих IMAP"""

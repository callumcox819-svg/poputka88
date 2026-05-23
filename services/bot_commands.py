"""Регистрация слэш-команд в меню Telegram (кнопка / слева от поля ввода)."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)

logger = logging.getLogger(__name__)

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Запуск бота и меню"),
    BotCommand(command="send", description="Запустить рассылку"),
    BotCommand(command="stop", description="Остановить рассылку"),
    BotCommand(command="stopcheck", description="Остановить проверку почт"),
    BotCommand(command="imap_check", description="Проверка входящих IMAP"),
]

# Языки, для которых в BotFather могли остаться старые команды
_LANGUAGES = (None, "ru", "en")

_SCOPES = (
    BotCommandScopeDefault(),
    BotCommandScopeAllPrivateChats(),
)


async def register_bot_commands(bot: Bot) -> None:
    """Сбросить старые команды и записать актуальный список во все scope/языки."""
    for scope in _SCOPES:
        for lang in _LANGUAGES:
            try:
                await bot.delete_my_commands(scope=scope, language_code=lang)
            except Exception as exc:
                logger.debug("delete_my_commands %s %s: %s", scope, lang, exc)

        for lang in _LANGUAGES:
            await bot.set_my_commands(
                BOT_COMMANDS,
                scope=scope,
                language_code=lang,
            )

    current = await bot.get_my_commands()
    logger.info(
        "Bot commands registered (%d): %s",
        len(current),
        ", ".join(f"/{c.command}" for c in current),
    )

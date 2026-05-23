"""Однократно обновить слэш-команды без запуска бота: python scripts/set_commands.py"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot

from config import load_settings
from services.bot_commands import register_bot_commands


async def main() -> None:
    settings = load_settings()
    bot = Bot(token=settings.bot_token)
    try:
        await register_bot_commands(bot)
        print("OK: команды + MenuButtonCommands зарегистрированы.")
        print("Если в Telegram всё ещё старое меню — вставьте BOTFATHER_COMMANDS.txt в @BotFather.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

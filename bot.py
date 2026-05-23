import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import load_settings
from database import init_db
from handlers import setup_routers
from middlewares.admin_only import AdminOnlyMiddleware
from middlewares.settings import SettingsMiddleware
from services.bot_commands import register_bot_commands

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    await init_db()

    bot = Bot(token=settings.bot_token)
    try:
        await register_bot_commands(bot)
        logger.info("Slash commands + MenuButtonCommands registered")
    except Exception:
        logger.exception("Failed to register bot commands — use /commands_help")

    dp = Dispatcher(storage=MemoryStorage())
    dp["settings"] = settings

    root = setup_routers()
    for mw in (SettingsMiddleware(settings), AdminOnlyMiddleware(settings)):
        root.message.middleware(mw)
        root.callback_query.middleware(mw)
    dp.include_router(root)

    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

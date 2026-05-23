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
from services.incoming_worker import start_incoming_mail_worker

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    logger.info(
        "Config OK: admin_ids=%s, validemail_keys=%d",
        len(settings.admin_ids),
        len(settings.validemail_api_keys),
    )
    await init_db()

    bot = Bot(token=settings.bot_token)

    async def _register_commands_bg() -> None:
        try:
            await register_bot_commands(bot)
        except Exception:
            logger.exception("Failed to register bot commands — use /commands_help")

    asyncio.create_task(_register_commands_bg())

    dp = Dispatcher(storage=MemoryStorage())
    dp["settings"] = settings

    root = setup_routers()
    for mw in (SettingsMiddleware(settings), AdminOnlyMiddleware(settings)):
        root.message.middleware(mw)
        root.callback_query.middleware(mw)
    dp.include_router(root)

    start_incoming_mail_worker(bot)
    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import load_settings
from database import init_db
from handlers import setup_routers
from middlewares.admin_only import AdminOnlyMiddleware
from middlewares.settings import SettingsMiddleware

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Запуск бота и меню"),
    BotCommand(command="send", description="Запустить рассылку"),
    BotCommand(command="stop", description="Остановить рассылку"),
    BotCommand(command="stopcheck", description="Остановить проверку почт"),
    BotCommand(command="imap_check", description="Проверка входящих IMAP"),
]


async def main() -> None:
    settings = load_settings()
    await init_db()

    bot = Bot(token=settings.bot_token)
    await bot.set_my_commands(BOT_COMMANDS)

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

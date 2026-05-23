import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError
from aiogram.fsm.storage.memory import MemoryStorage
from config import load_settings
from database import init_db, list_imap_poll_accounts
from handlers import setup_routers
from middlewares.admin_only import AdminOnlyMiddleware
from middlewares.settings import SettingsMiddleware
from services.bot_commands import register_bot_commands
from services.incoming_worker import POLL_SEC, start_incoming_mail_worker

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

_ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "callback_query",
    "my_chat_member",
]


async def _on_startup(bot: Bot) -> None:
    wh = await bot.get_webhook_info()
    if wh.url:
        logger.warning("Активен webhook %s — удаляю, работаем только через polling", wh.url)
    await bot.delete_webhook(drop_pending_updates=False)

    try:
        await register_bot_commands(bot)
    except Exception:
        logger.exception("Failed to register bot commands on startup")

    imap_accs = await list_imap_poll_accounts()
    logger.info(
        "IMAP: %s ящик(ов) в фоновом опросе каждые %ss",
        len(imap_accs),
        POLL_SEC,
    )
    if not imap_accs:
        logger.warning(
            "IMAP: нет ящиков для опроса — добавьте SMTP с паролем в ⚡ Быстрое добавление"
        )


async def _on_error(event) -> None:
    exc = event.exception
    if isinstance(exc, TelegramConflictError):
        logger.critical(
            "TelegramConflictError: второй getUpdates на этом BOT_TOKEN. "
            "Чаще всего — редеплой Railway (старый и новый контейнер ~30–90 с) "
            "или webhook не был снят. Сейчас webhook снимается при старте."
        )
    logger.exception("Update error: %s", exc)


async def main() -> None:
    settings = load_settings()
    logger.info(
        "Config OK: admin_ids=%s, validemail_keys=%d",
        len(settings.admin_ids),
        len(settings.validemail_api_keys),
    )
    await init_db()

    bot = Bot(token=settings.bot_token)

    dp = Dispatcher(storage=MemoryStorage())
    dp.startup.register(_on_startup)
    dp.errors.register(_on_error)
    dp["settings"] = settings

    root = setup_routers()
    for mw in (SettingsMiddleware(settings), AdminOnlyMiddleware(settings)):
        root.message.middleware(mw)
        root.callback_query.middleware(mw)
    dp.include_router(root)

    start_incoming_mail_worker(bot)
    logger.info("Bot started")
    await dp.start_polling(bot, allowed_updates=_ALLOWED_UPDATES)


if __name__ == "__main__":
    asyncio.run(main())

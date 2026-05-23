import asyncio

import logging

import os

import sys



from aiogram import Bot, Dispatcher

from aiogram.exceptions import TelegramConflictError

from aiogram.fsm.storage.memory import MemoryStorage

from config import load_settings

from database import init_db, list_imap_poll_accounts

from handlers import setup_routers

from middlewares.bot_access import BotAccessMiddleware
from services.bot_users import seed_config_admins

from middlewares.settings import SettingsMiddleware

from services.bot_commands import register_bot_commands

from services.incoming_worker import POLL_SEC, start_incoming_mail_worker


def _env_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}



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
    if not imap_accs:
        logger.warning(
            "IMAP: нет ящиков для опроса — добавьте SMTP с паролем в ⚡ Быстрое добавление"
        )
    await _start_imap_on_bot_if_needed(bot, mailbox_count=len(imap_accs))


async def _start_imap_on_bot_if_needed(bot: Bot, *, mailbox_count: int = 0) -> None:
    """IMAP на боте только если нет отдельного imap-worker (см. RAILWAY_IMAP_WORKER.txt)."""
    if not _env_truthy("ENABLE_INCOMING_MAIL"):
        logger.warning(
            "Авто-входящие ВЫКЛ на bot.py (%s ящ. в БД). Без /imap_check письма не придут, "
            "пока не запущен imap-worker: python imap_worker.py + ENABLE_INCOMING_MAIL=1 "
            "(опрос ~%ss, см. RAILWAY_IMAP_WORKER.txt)",
            mailbox_count,
            POLL_SEC,
        )
        return
    if _env_truthy("IMAP_DEDICATED_WORKER"):
        logger.warning(
            "Авто-входящие на bot.py выключены (IMAP_DEDICATED_WORKER=1). "
            "Должен работать сервис imap-worker — %s ящ., опрос ~%ss. "
            "Иначе только /imap_check.",
            mailbox_count,
            POLL_SEC,
        )
        return

    logger.info(
        "IMAP: %s ящик(ов) в фоновом опросе на боте каждые %ss",
        mailbox_count,
        POLL_SEC,
    )
    delay = int(os.getenv("INCOMING_MAIL_START_DELAY_SEC", "30"))

    async def _delayed() -> None:
        if delay > 0:
            logger.info("IMAP worker на боте стартует через %ss", delay)
            await asyncio.sleep(delay)
        start_incoming_mail_worker(bot)
        logger.info("Incoming IMAP worker on bot (poll=%ss)", POLL_SEC)

    asyncio.create_task(_delayed())


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
    await seed_config_admins(settings.admin_ids)

    bot = Bot(token=settings.bot_token)



    dp = Dispatcher(storage=MemoryStorage())

    dp.startup.register(_on_startup)

    dp.errors.register(_on_error)

    dp["settings"] = settings



    root = setup_routers()

    for mw in (SettingsMiddleware(settings), BotAccessMiddleware(settings)):

        root.message.middleware(mw)

        root.callback_query.middleware(mw)

    dp.include_router(root)

    logger.info("Bot started")

    await dp.start_polling(bot, allowed_updates=_ALLOWED_UPDATES)





if __name__ == "__main__":

    asyncio.run(main())


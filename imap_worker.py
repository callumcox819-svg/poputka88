"""
Отдельный процесс только для входящей почты (IMAP).

Railway: второй сервис из того же репозитория poputka88:
  python imap_worker.py

Общее с ботом: DATABASE_URL, BOT_TOKEN (только send_message, без polling).
На сервисе poputka88: IMAP_DEDICATED_WORKER=1 — IMAP не дублируется в bot.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import load_settings
from database import count_imap_poll_accounts_raw, init_db, list_imap_poll_accounts
from services.bot_users import seed_config_admins
from services.db_backend import DB_PATH, database_env_diag, is_postgres
from services.incoming_worker import POLL_SEC, start_incoming_mail_worker

logger = logging.getLogger(__name__)


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


async def _worker_heartbeat() -> None:
    n = 0
    while True:
        await asyncio.sleep(60)
        n += 1
        try:
            accs = await list_imap_poll_accounts()
            n_acc = len(accs)
            n_users = len({int(a.get("user_id") or 0) for a in accs})
        except Exception:
            n_acc, n_users = "?", "?"
        logger.info(
            "💓 IMAP worker alive #%s mailboxes=%s users=%s poll=%ss max_concurrent=%s",
            n,
            n_acc,
            n_users,
            POLL_SEC,
            os.getenv("MAX_IMAP_CONCURRENT", "8"),
        )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )

    if not _truthy("ENABLE_INCOMING_MAIL"):
        logger.error(
            "ENABLE_INCOMING_MAIL не задан. На сервисе imap-worker → Variables: ENABLE_INCOMING_MAIL=1"
        )
        sys.exit(1)

    settings = load_settings()
    await init_db()
    await seed_config_admins(settings.admin_ids)

    if not is_postgres():
        logger.critical(
            "PostgreSQL не виден в процессе (%s). Переменные в контейнере: %s. "
            "Откройте Variables именно у сервиса imap-worker (inspiring-beauty), "
            "добавьте DATABASE_URL → Reference → Postgres (как у poputka88), "
            "нажмите Deploy. Не вставляйте ${{Postgres...}} текстом — только Reference.",
            DB_PATH,
            database_env_diag(),
        )
        sys.exit(1)

    stats = await count_imap_poll_accounts_raw()
    logger.info(
        "IMAP DB (Postgres): smtp total=%s enabled=%s with_password=%s pollable=%s",
        stats["total"],
        stats["enabled"],
        stats["with_password"],
        stats["pollable"],
    )
    if stats["pollable"] == 0:
        if stats["enabled"] > 0:
            logger.critical(
                "0 ящиков для опроса при %s enabled SMTP — нет паролей или IMAP host. "
                "Проверьте ⚡ Быстрое добавление на основном боте.",
                stats["enabled"],
            )
        else:
            logger.critical(
                "0 SMTP в этой БД. DATABASE_URL на imap-worker должен быть Reference "
                "на тот же Postgres, что у poputka88 (сейчас другая/пустая база)."
            )
        sys.exit(1)

    os.environ.setdefault("MAX_IMAP_CONCURRENT", "12")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    me = await bot.get_me()
    logger.info(
        "IMAP worker: @%s (id=%s) — polling Telegram НЕ запускается",
        me.username,
        me.id,
    )

    delay = int(os.getenv("INCOMING_MAIL_START_DELAY_SEC", "10"))
    if delay > 0:
        logger.info("Старт опроса ящиков через %ss", delay)
        await asyncio.sleep(delay)

    start_incoming_mail_worker(bot)
    asyncio.create_task(_worker_heartbeat())

    try:
        await asyncio.Event().wait()
    finally:
        await bot.session.close()
        logger.info("IMAP worker stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

import asyncio
import logging

from aiogram import Bot

from config import Settings
from database import (
    get_campaign,
    mark_failed,
    mark_sent,
    pending_recipients,
    set_campaign_status,
)
from services.encoding import TransferEncoding
from services.smtp_sender import send_one

logger = logging.getLogger(__name__)

_active: set[int] = set()


async def run_campaign(
    bot: Bot,
    settings: Settings,
    campaign_id: int,
    chat_id: int,
) -> None:
    if campaign_id in _active:
        return
    _active.add(campaign_id)

    try:
        camp = await get_campaign(campaign_id)
        if not camp:
            await bot.send_message(chat_id, "Кампания не найдена.")
            return

        await set_campaign_status(campaign_id, "running")
        transfer = TransferEncoding(camp["encoding"])

        while True:
            camp = await get_campaign(campaign_id)
            if not camp or camp["status"] == "paused":
                break

            batch = await pending_recipients(campaign_id, limit=1)
            if not batch:
                await set_campaign_status(campaign_id, "done")
                await bot.send_message(
                    chat_id,
                    f"Готово. Отправлено: {camp['sent']}, ошибок: {camp['failed']}.",
                )
                break

            email = batch[0]
            try:
                used = await send_one(
                    settings,
                    to_addr=email,
                    subject=camp["subject"],
                    body=camp["body"],
                    is_html=bool(camp["is_html"]),
                    transfer=transfer,
                )
                await mark_sent(campaign_id, email)
                logger.info("sent %s enc=%s", email, used)
            except Exception as exc:
                await mark_failed(campaign_id, email, str(exc))
                logger.warning("fail %s: %s", email, exc)

            await asyncio.sleep(settings.send_delay_sec)

    finally:
        _active.discard(campaign_id)

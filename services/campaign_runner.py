import asyncio
import logging

from aiogram import Bot

from config import Settings
from database import (
    get_campaign,
    list_smtp_accounts,
    mark_failed,
    mark_sent,
    pending_recipients,
    set_campaign_status,
)
from services.encoding import TransferEncoding
from services.mailing_timing import load_timing
from services.presets import pick_random_smart_preset
from services.user_settings import get_bool
from database import count_proxies
from services.mail_outbound import NoLiveProxyError, live_proxy_count, send_mail
from services.task_control import (
    clear_stop_campaign,
    request_stop_campaign,
    should_stop_campaign,
)

logger = logging.getLogger(__name__)

_active: set[int] = set()
_account_index: dict[int, int] = {}


def stop_campaign(campaign_id: int) -> None:
    request_stop_campaign(campaign_id)


async def stop_user_mailings(user_id: int) -> list[int]:
    from database import get_running_campaign, pause_running_campaigns

    camp = await get_running_campaign(user_id)
    if camp:
        stop_campaign(camp["id"])
    return await pause_running_campaigns(user_id)


async def run_campaign(
    bot: Bot,
    settings: Settings,
    campaign_id: int,
    chat_id: int,
    user_id: int,
) -> None:
    if campaign_id in _active:
        return
    _active.add(campaign_id)
    clear_stop_campaign(campaign_id)

    try:
        camp = await get_campaign(campaign_id)
        if not camp:
            await bot.send_message(chat_id, "Кампания не найдена.")
            return

        accounts = await list_smtp_accounts(user_id, with_secrets=True)
        await set_campaign_status(campaign_id, "running")
        transfer = TransferEncoding(camp["encoding"])
        timing = await load_timing(user_id, settings.send_delay_sec)
        delay = float(timing.get("min", settings.send_delay_sec))

        proxy_total = await count_proxies(user_id)
        proxy_live = await live_proxy_count(user_id) if proxy_total else 0
        if proxy_total and proxy_live == 0:
            await set_campaign_status(campaign_id, "paused")
            await bot.send_message(
                chat_id,
                "❌ В настройках есть прокси, но нет живых.\n"
                "Проверьте прокси (🌐 Прокси → 🔍 Проверить) и запустите снова.",
            )
            return

        proxy_line = ""
        if proxy_total:
            proxy_line = f"\nПрокси SOCKS5: {proxy_live}/{proxy_total} (все живые по очереди)"
        await bot.send_message(
            chat_id,
            f"Рассылка #{campaign_id} запущена.\n"
            f"SMTP-аккаунтов: {len(accounts) or 'из .env (1)'}{proxy_line}",
        )

        while True:
            if should_stop_campaign(campaign_id):
                await set_campaign_status(campaign_id, "paused")
                camp = await get_campaign(campaign_id)
                await bot.send_message(
                    chat_id,
                    f"Рассылка #{campaign_id} остановлена.\n"
                    f"Отправлено: {camp['sent']}, ошибок: {camp['failed']}.",
                )
                break

            camp = await get_campaign(campaign_id)
            if not camp or camp["status"] == "paused":
                break

            batch = await pending_recipients(campaign_id, limit=1)
            if not batch:
                await set_campaign_status(campaign_id, "done")
                camp = await get_campaign(campaign_id)
                await bot.send_message(
                    chat_id,
                    f"Готово. Отправлено: {camp['sent']}, ошибок: {camp['failed']}.",
                )
                break

            email = batch[0]
            account = None
            if accounts:
                idx = _account_index.get(user_id, 0) % len(accounts)
                account = accounts[idx]
                _account_index[user_id] = idx + 1

            body = camp["body"]
            if await get_bool(user_id, "smart_mode"):
                smart_body = await pick_random_smart_preset(
                    user_id, camp["subject"]
                )
                if smart_body:
                    body = smart_body

            try:
                used = await send_mail(
                    settings,
                    user_id,
                    to_addr=email,
                    subject=camp["subject"],
                    body=body,
                    is_html=bool(camp["is_html"]),
                    transfer=transfer,
                    account=account,
                )
                await mark_sent(campaign_id, email)
                logger.info("sent %s enc=%s", email, used)
            except NoLiveProxyError as exc:
                await set_campaign_status(campaign_id, "paused")
                await bot.send_message(chat_id, f"❌ {exc}")
                break
            except Exception as exc:
                await mark_failed(campaign_id, email, str(exc))
                logger.warning("fail %s: %s", email, exc)

            await asyncio.sleep(delay)

    finally:
        _active.discard(campaign_id)
        clear_stop_campaign(campaign_id)

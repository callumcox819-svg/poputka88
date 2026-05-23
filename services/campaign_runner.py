import asyncio
import logging

from aiogram import Bot

from config import Settings
from database import (
    count_proxies,
    get_campaign,
    list_smtp_mailing_accounts,
    mark_failed,
    mark_sent,
    pending_recipients,
    set_campaign_status,
)
from services.offer_text import apply_offer_to_text
from services.subject_offer import mailing_subject_for_recipient, offer_title_for_recipient
from services.encoding import TransferEncoding
from services.mailing_timing import load_timing
from services.html_spoof import HtmlOutboundError
from services.mail_outbound import NoLiveProxyError, live_proxy_count, send_mail
from services.presets import pick_random_smart_preset
from services.smtp_block_control import handle_campaign_send_error
from services.task_control import (
    clear_stop_campaign,
    request_stop_campaign,
    should_stop_campaign,
)
from services.html_mailing import render_campaign_html
from services.user_settings import get_bool

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
        camp = await get_campaign(campaign_id, user_id)
        if not camp:
            await bot.send_message(chat_id, "Кампания не найдена.")
            return

        accounts = await list_smtp_mailing_accounts(user_id, with_secrets=True)
        await set_campaign_status(campaign_id, "running")
        transfer = TransferEncoding(camp["encoding"])
        timing = await load_timing(user_id, settings.send_delay_sec)
        delay = float(timing.get("min", settings.send_delay_sec))
        is_html = bool(camp["is_html"])

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
        smart_on = await get_bool(user_id, "smart_mode")
        smart_line = "\n🟢 Умный режим: подставляются умные пресеты." if smart_on else ""
        html_line = ""
        if is_html:
            if not proxy_total:
                await set_campaign_status(campaign_id, "paused")
                await bot.send_message(
                    chat_id,
                    "❌ HTML-рассылка требует SOCKS5-прокси. Добавьте в 🌐 Прокси.",
                )
                return
            html_line = (
                "\n📄 HTML: шаблон, GAG-ссылка, прокси; тема/имя — 👤 Имя для спуфинга."
            )
        await bot.send_message(
            chat_id,
            f"Рассылка #{campaign_id} запущена.\n"
            f"SMTP-аккаунтов: {len(accounts) or 'из .env (1)'}{proxy_line}{smart_line}{html_line}",
        )

        while True:
            if should_stop_campaign(campaign_id):
                await set_campaign_status(campaign_id, "paused")
                camp = await get_campaign(campaign_id, user_id)
                await bot.send_message(
                    chat_id,
                    f"Рассылка #{campaign_id} остановлена.\n"
                    f"Отправлено: {camp['sent']}, ошибок: {camp['failed']}.",
                )
                break

            camp = await get_campaign(campaign_id, user_id)
            if not camp or camp["status"] == "paused":
                break

            batch = await pending_recipients(campaign_id, limit=1)
            if not batch:
                await set_campaign_status(campaign_id, "done")
                camp = await get_campaign(campaign_id, user_id)
                await bot.send_message(
                    chat_id,
                    f"Готово. Отправлено: {camp['sent']}, ошибок: {camp['failed']}.",
                )
                break

            accounts = await list_smtp_mailing_accounts(user_id, with_secrets=True)
            if not accounts and not (
                settings.smtp_host and settings.smtp_user
            ):
                await set_campaign_status(campaign_id, "paused")
                await bot.send_message(
                    chat_id,
                    "❌ Нет доступных SMTP-аккаунтов для рассылки.\n"
                    "Добавьте почты или отключите блокировки и проверьте аккаунты.",
                )
                break

            email = batch[0]
            account = None
            if accounts:
                idx = _account_index.get(user_id, 0) % len(accounts)
                account = accounts[idx]
                _account_index[user_id] = idx + 1

            body = camp["body"]
            offer_title = await offer_title_for_recipient(user_id, email)
            subject = await mailing_subject_for_recipient(user_id, email)

            if is_html:
                body, html_err = await render_campaign_html(
                    user_id, camp_body=body, to_email=email
                )
                if html_err:
                    await mark_failed(campaign_id, email, html_err)
                    continue
            else:
                if smart_on:
                    smart_body = await pick_random_smart_preset(
                        user_id, offer_title
                    )
                    if smart_body:
                        body = smart_body
                else:
                    body = apply_offer_to_text(body, offer_title)

            try:
                used = await send_mail(
                    settings,
                    user_id,
                    to_addr=email,
                    subject=subject,
                    body=body,
                    is_html=is_html,
                    transfer=transfer,
                    account=account,
                )
                await mark_sent(campaign_id, email)
                logger.info("sent %s enc=%s", email, used)
            except (NoLiveProxyError, HtmlOutboundError) as exc:
                await set_campaign_status(campaign_id, "paused")
                await bot.send_message(chat_id, f"❌ {exc}")
                break
            except Exception as exc:
                await mark_failed(campaign_id, email, str(exc))
                logger.warning("fail %s: %s", email, exc)
                if account:
                    action = await handle_campaign_send_error(
                        user_id,
                        int(account["id"]),
                        str(exc),
                        bot=bot,
                        chat_id=chat_id,
                    )
                    if action in {"removed_mailing", "disabled_full"}:
                        accounts = await list_smtp_mailing_accounts(
                            user_id, with_secrets=True
                        )
                        if not accounts and not (
                            settings.smtp_host and settings.smtp_user
                        ):
                            await set_campaign_status(campaign_id, "paused")
                            await bot.send_message(
                                chat_id,
                                "❌ Все SMTP-аккаунты отключены. Рассылка остановлена.",
                            )
                            break

            await asyncio.sleep(delay)

    finally:
        _active.discard(campaign_id)
        clear_stop_campaign(campaign_id)

import asyncio
import logging
import random
import time

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


def campaign_task_active(campaign_id: int) -> bool:
    return int(campaign_id) in _active


def campaign_task_stuck(campaign_id: int, status: str | None) -> bool:
    """В БД running, но фоновой задачи нет — рассылка «зависла» без уведомления."""
    st = (status or "").strip()
    return st == "running" and not campaign_task_active(int(campaign_id))


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

    crashed = False
    try:
        camp = await get_campaign(campaign_id, user_id)
        if not camp:
            await bot.send_message(chat_id, "Кампания не найдена.")
            return

        accounts = await list_smtp_mailing_accounts(user_id, with_secrets=True)
        await set_campaign_status(campaign_id, "running")
        transfer = TransferEncoding(camp["encoding"])
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

            timing = await load_timing(user_id, settings.send_delay_sec)
            min_delay = float(timing.get("min", settings.send_delay_sec))
            max_delay = float(timing.get("max", min_delay))
            if max_delay < min_delay:
                max_delay = min_delay
            burst_size = max(1, min(8, int(timing.get("batch_size", 3))))

            iter_started = time.monotonic()
            batch = await pending_recipients(campaign_id, limit=burst_size)
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

            account = None
            if accounts:
                idx = _account_index.get(user_id, 0) % len(accounts)
                account = accounts[idx]
                _account_index[user_id] = idx + 1

            base_body = camp["body"]
            burst_stopped = False

            for email in batch:
                if should_stop_campaign(campaign_id):
                    burst_stopped = True
                    break

                body = base_body
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
                    burst_stopped = True
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
                                burst_stopped = True
                                break

            if burst_stopped:
                if should_stop_campaign(campaign_id):
                    await set_campaign_status(campaign_id, "paused")
                    camp = await get_campaign(campaign_id, user_id)
                    await bot.send_message(
                        chat_id,
                        f"Рассылка #{campaign_id} остановлена.\n"
                        f"Отправлено: {camp['sent']}, ошибок: {camp['failed']}.",
                    )
                break

            # Пауза на пачку: случайно MIN–MAX сек (как happy88), не фикс MIN на каждое письмо.
            pace = random.uniform(min_delay, max_delay)
            wait_more = pace - (time.monotonic() - iter_started)
            if wait_more > 0:
                await asyncio.sleep(wait_more)

    except Exception as exc:
        crashed = True
        logger.exception("campaign %s crashed: %s", campaign_id, exc)
        try:
            await set_campaign_status(campaign_id, "paused")
            camp = await get_campaign(campaign_id, user_id)
            sent = int((camp or {}).get("sent") or 0)
            failed = int((camp or {}).get("failed") or 0)
            await bot.send_message(
                chat_id,
                f"❌ Рассылка #{campaign_id} остановлена (ошибка в фоне).\n"
                f"Отправлено: {sent}, ошибок: {failed}.\n"
                f"<code>{type(exc).__name__}</code>: {str(exc)[:400]}\n\n"
                f"/send — продолжить с того же места.",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("failed to notify campaign crash %s", campaign_id)

    finally:
        try:
            camp = await get_campaign(campaign_id, user_id)
            if (
                not crashed
                and camp
                and (camp.get("status") or "").strip() == "running"
            ):
                await set_campaign_status(campaign_id, "paused")
                sent = int(camp.get("sent") or 0)
                failed = int(camp.get("failed") or 0)
                await bot.send_message(
                    chat_id,
                    f"⚠️ Рассылка #{campaign_id} прервалась без завершения "
                    f"(фоновая задача остановилась).\n"
                    f"Отправлено: {sent}, ошибок: {failed}.\n"
                    f"/send — продолжить.",
                )
        except Exception:
            logger.exception("failed to mark orphan campaign %s paused", campaign_id)
        _active.discard(campaign_id)
        clear_stop_campaign(campaign_id)

"""Фоновый опрос IMAP и уведомления в Telegram."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from database import (
    count_incoming_from_sender,
    get_imap_last_uid,
    get_incoming_thread_reply_message_id,
    incoming_mail_exists,
    insert_incoming_mail,
    list_imap_poll_accounts,
    set_imap_last_uid,
    set_incoming_mail_tg_message,
)
from services.imap_accounts import imap_mailbox_for_account, is_gmail_account
from services.imap_fetch import (
    fetch_new_mails_sync,
    is_google_system_mail,
    is_own_outgoing_copy,
    service_label_from_body,
    service_label_from_link,
)
from services.incoming_card import build_card_from_mail_row
from services.lead_resolve import resolve_validated_lead

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
POLL_SEC = float(os.getenv("INCOMING_POLL_SEC", "20"))


def _format_price(price: str, currency: str = "") -> str:
    p = (price or "").strip()
    if not p:
        return ""
    cur = (currency or "").strip()
    if cur and cur.upper() not in p.upper():
        return f"{p} {cur}".strip()
    return p


async def _lead_meta(user_id: int, from_email: str, body: str) -> dict:
    resolved = await resolve_validated_lead(user_id, contact_email=from_email)
    if not resolved:
        svc = service_label_from_body(body)
        return {
            "lead_id": None,
            "product_title": "",
            "service_label": svc,
            "photo_url": "",
            "offer_price": "",
        }
    lead = resolved.lead
    link = (lead.get("item_link") or "").strip()
    svc = service_label_from_link(link) or service_label_from_body(body)
    price = _format_price(
        str(lead.get("item_price") or ""),
        str(lead.get("item_currency") or lead.get("currency") or ""),
    )
    return {
        "lead_id": int(lead["id"]),
        "product_title": (lead.get("item_title") or "").strip(),
        "service_label": svc,
        "photo_url": (lead.get("item_photo") or "").strip(),
        "offer_price": price,
    }


async def _notify_incoming(
    bot: Bot,
    *,
    chat_id: int,
    user_id: int,
    account_id: int,
    inbox_label: str,
    mail_id: int,
    is_first_from_sender: bool,
    meta: dict,
) -> None:
    from database import get_incoming_mail

    mail = await get_incoming_mail(mail_id, user_id)
    if not mail:
        return

    reply_to = await get_incoming_thread_reply_message_id(
        account_id, mail.get("from_email") or ""
    )
    text, kb = build_card_from_mail_row(mail, inbox_label=inbox_label or None)
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
            reply_to_message_id=reply_to,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    await set_incoming_mail_tg_message(
        mail_id, user_id, chat_id=chat_id, message_id=msg.message_id
    )

    try:
        await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
    except Exception:
        pass

    photo_url = (meta.get("photo_url") or "").strip()
    if is_first_from_sender and photo_url:
        cap = "📷 Фото товара (первый ответ)"
        if meta.get("offer_price"):
            cap += f"\n💰 Цена: {meta['offer_price']} 💰"
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=cap,
                reply_to_message_id=msg.message_id,
            )
        except Exception:
            logger.warning("send_photo failed mail_id=%s url=%s", mail_id, photo_url[:80])


async def _process_account(
    bot: Bot, acc: dict, *, catch_up_recent: int = 0
) -> int:
    """Опрос INBOX одного ящика. Возвращает число новых карточек в Telegram."""
    acc_id = int(acc["id"])
    user_id = int(acc["user_id"])
    host = (acc.get("imap_host") or "").strip()
    port = int(acc.get("imap_port") or 993)
    email_addr = (acc.get("email") or "").strip()
    password = acc.get("password") or ""
    if not host or not email_addr or not password:
        return 0

    mailbox = imap_mailbox_for_account(acc)
    recent = catch_up_recent
    if recent <= 0 and is_gmail_account(acc):
        recent = 25

    last_uid = await get_imap_last_uid(acc_id)
    try:
        mails, new_last = await asyncio.to_thread(
            fetch_new_mails_sync,
            host=host,
            port=port,
            email_addr=email_addr,
            password=password,
            last_uid=last_uid,
            catch_up_recent=recent,
            mailbox=mailbox,
        )
    except Exception as exc:
        logger.error("IMAP acc_id=%s %s: %s", acc_id, email_addr, exc)
        return 0

    if new_last is not None:
        await set_imap_last_uid(acc_id, int(new_last))

    if not mails:
        return 0

    inbox_label = (acc.get("sender_name") or "").strip()
    chat_id = user_id
    notified = 0
    skipped_exists = 0
    skipped_system = 0
    skipped_empty = 0
    skipped_own = 0

    for row in mails:
        uid, from_email, from_name, subject, _date, body, message_id = row
        if not from_email:
            skipped_empty += 1
            continue
        if is_own_outgoing_copy(from_email, email_addr, subject):
            skipped_own += 1
            continue
        if is_google_system_mail(from_email, from_name, subject):
            skipped_system += 1
            continue
        if await incoming_mail_exists(acc_id, uid):
            skipped_exists += 1
            continue

        prior = await count_incoming_from_sender(acc_id, from_email)
        is_first = prior == 0

        meta = await _lead_meta(user_id, from_email, body)
        mail_id = await insert_incoming_mail(
            user_id,
            acc_id,
            imap_uid=uid,
            message_id=message_id,
            account_email=email_addr,
            from_email=from_email,
            from_name=from_name,
            subject=subject,
            body=body,
            lead_id=meta.get("lead_id"),
            product_title=meta.get("product_title", ""),
            service_label=meta.get("service_label", ""),
            photo_url=meta.get("photo_url", ""),
            offer_price=meta.get("offer_price", ""),
        )
        if not mail_id:
            continue

        try:
            await _notify_incoming(
                bot,
                chat_id=chat_id,
                user_id=user_id,
                account_id=acc_id,
                inbox_label=inbox_label,
                mail_id=mail_id,
                is_first_from_sender=is_first,
                meta=meta,
            )
            notified += 1
            logger.info(
                "IMAP new mail user_id=%s acc=%s from=%s mail_id=%s",
                user_id,
                email_addr,
                from_email,
                mail_id,
            )
        except Exception:
            logger.exception("notify incoming mail_id=%s", mail_id)

    if mails and not notified:
        logger.info(
            "IMAP acc=%s [%s] fetched=%s notified=0 "
            "(exists=%s own=%s system=%s empty=%s)",
            email_addr,
            mailbox,
            len(mails),
            skipped_exists,
            skipped_own,
            skipped_system,
            skipped_empty,
        )

    return notified


async def poll_incoming_for_user(
    bot: Bot, user_id: int, *, catch_up: bool = False
) -> tuple[int, int]:
    """Немедленный опрос INBOX для ящиков user_id. (accounts, new_cards)."""
    uid = int(user_id)
    accounts = [
        a for a in await list_imap_poll_accounts() if int(a.get("user_id") or 0) == uid
    ]
    recent = 40 if catch_up else 0
    total = 0
    for acc in accounts:
        total += await _process_account(bot, acc, catch_up_recent=recent)
    if accounts:
        logger.info(
            "IMAP manual poll user_id=%s: %s account(s), %s new card(s), catch_up=%s",
            uid,
            len(accounts),
            total,
            catch_up,
        )
    return len(accounts), total


async def _poll_loop(bot: Bot) -> None:
    while True:
        try:
            accounts = await list_imap_poll_accounts()
            new_cards = 0
            for acc in accounts:
                new_cards += await _process_account(bot, acc)
            if accounts and new_cards:
                logger.info(
                    "IMAP poll: %s account(s), %s new card(s)",
                    len(accounts),
                    new_cards,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("incoming mail poll")
        await asyncio.sleep(POLL_SEC)


def start_incoming_mail_worker(bot: Bot) -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_poll_loop(bot))

    async def _log_accounts() -> None:
        try:
            n = len(await list_imap_poll_accounts())
            logger.info("Incoming IMAP worker started (poll=%ss, accounts=%s)", POLL_SEC, n)
        except Exception:
            logger.info("Incoming IMAP worker started (poll=%ss)", POLL_SEC)

    asyncio.create_task(_log_accounts())


def stop_incoming_mail_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None

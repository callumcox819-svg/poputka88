"""Фоновый опрос IMAP и уведомления в Telegram."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from database import (
    count_incoming_from_sender,
    incoming_is_first_from_sender,
    get_imap_last_uid,
    get_incoming_mail,
    get_incoming_mail_id_by_uid,
    get_incoming_thread_reply_message_id,
    insert_incoming_mail,
    list_imap_poll_accounts,
    list_incoming_pending_notify,
    set_imap_last_uid,
    inherit_incoming_gag_link,
    set_incoming_mail_tg_message,
    update_incoming_mail_lead_snapshot,
)
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
POLL_SEC = float(os.getenv("INCOMING_POLL_SEC", os.getenv("INCOMING_MAIL_POLL_SECONDS", "60")))
MAX_IMAP_CONCURRENT = max(1, int(os.getenv("MAX_IMAP_CONCURRENT", "8")))


def _format_price(price: str, currency: str = "") -> str:
    p = (price or "").strip()
    if not p:
        return ""
    cur = (currency or "").strip()
    if cur and cur.upper() not in p.upper():
        return f"{p} {cur}".strip()
    return p


async def _lead_link(lead: dict) -> str:
    link = (lead.get("item_link") or "").strip()
    if link:
        return link
    raw = (lead.get("raw_json") or "").strip()
    if not raw:
        return ""
    try:
        import json

        data = json.loads(raw)
        if isinstance(data, dict):
            return str(
                data.get("item_link") or data.get("link") or data.get("url") or ""
            ).strip()
    except json.JSONDecodeError:
        pass
    return ""


async def _lead_meta(
    user_id: int,
    from_email: str,
    body: str,
    *,
    subject: str = "",
    account_id: int = 0,
    from_name: str = "",
) -> dict:
    resolved = await resolve_validated_lead(
        user_id,
        contact_email=from_email,
        subject=subject,
        account_id=account_id or None,
        from_name=from_name,
    )
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
    link = await _lead_link(lead)
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


async def _sync_incoming_lead_snapshot(
    user_id: int, mail_id: int, meta: dict
) -> None:
    if not mail_id or not meta.get("lead_id"):
        return
    await update_incoming_mail_lead_snapshot(
        mail_id,
        user_id,
        lead_id=int(meta["lead_id"]),
        product_title=meta.get("product_title", ""),
        service_label=meta.get("service_label", ""),
        photo_url=meta.get("photo_url", ""),
        offer_price=meta.get("offer_price", ""),
    )


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

    if meta.get("lead_id") and not (mail.get("product_title") or "").strip():
        await _sync_incoming_lead_snapshot(user_id, mail_id, meta)
        mail = await get_incoming_mail(mail_id, user_id) or mail
    elif not meta.get("lead_id") and mail.get("lead_id"):
        from database import get_validated_lead_by_id

        lead = await get_validated_lead_by_id(user_id, int(mail["lead_id"]))
        if lead:
            link = await _lead_link(lead)
            meta = {
                "lead_id": int(lead["id"]),
                "product_title": (lead.get("item_title") or "").strip(),
                "service_label": service_label_from_link(link)
                or (mail.get("service_label") or ""),
                "photo_url": (lead.get("item_photo") or "").strip(),
                "offer_price": _format_price(
                    str(lead.get("item_price") or ""),
                    str(lead.get("item_currency") or lead.get("currency") or ""),
                ),
            }

    reply_to = await get_incoming_thread_reply_message_id(
        account_id, mail.get("from_email") or ""
    )
    text, kb = build_card_from_mail_row(
        mail,
        inbox_label=inbox_label or None,
        include_product_extras=is_first_from_sender,
    )
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

    if is_first_from_sender:
        photo_url = (meta.get("photo_url") or "").strip()
        if photo_url:
            title = (meta.get("product_title") or "").strip()
            cap = "📷 Фото товара"
            if title:
                cap = f"📌 {title}\n{cap}"
            price = (meta.get("offer_price") or "").strip()
            if price:
                cap += f"\n💰 Цена: {price} 💰"
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url,
                    caption=cap,
                    reply_to_message_id=msg.message_id,
                )
            except Exception:
                logger.warning(
                    "send_photo failed mail_id=%s url=%s", mail_id, photo_url[:80]
                )


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

    last_uid = await get_imap_last_uid(acc_id)
    try:
        mails, new_last = await asyncio.to_thread(
            fetch_new_mails_sync,
            host=host,
            port=port,
            email_addr=email_addr,
            password=password,
            last_uid=last_uid,
            catch_up_recent=max(0, int(catch_up_recent or 0)),
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

        is_first = (await count_incoming_from_sender(acc_id, from_email)) == 0
        meta = await _lead_meta(
            user_id,
            from_email,
            body,
            subject=subject,
            account_id=acc_id,
            from_name=from_name,
        )

        mail_id = await get_incoming_mail_id_by_uid(acc_id, uid) or 0
        if mail_id:
            existing = await get_incoming_mail(mail_id, user_id)
            if existing and existing.get("tg_message_id"):
                skipped_exists += 1
                continue
            await _sync_incoming_lead_snapshot(user_id, mail_id, meta)
        else:
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
                mail_id = await get_incoming_mail_id_by_uid(acc_id, uid) or 0
            if not mail_id:
                continue

        if not meta.get("lead_id"):
            logger.info(
                "IMAP no lead match user_id=%s from=%s subj=%r",
                user_id,
                from_email,
                (subject or "")[:80],
            )

        await inherit_incoming_gag_link(mail_id, user_id, from_email)

        logger.info(
            "IMAP incoming → TG user_id=%s inbox=%s FROM %s subj=%r",
            user_id,
            email_addr,
            from_email,
            (subject or "")[:80],
        )
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
                "IMAP card ok mail_id=%s user_id=%s inbox=%s from=%s",
                mail_id,
                user_id,
                email_addr,
                from_email,
            )
        except Exception:
            logger.exception("notify incoming mail_id=%s", mail_id)

    if mails and not notified:
        logger.info(
            "IMAP acc=%s INBOX fetched=%s notified=0 "
            "(exists=%s own=%s system=%s empty=%s)",
            email_addr,
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
    if accounts:
        sem = asyncio.Semaphore(MAX_IMAP_CONCURRENT)

        async def _one(acc: dict) -> int:
            async with sem:
                return await _process_account(bot, acc, catch_up_recent=recent)

        results = await asyncio.gather(
            *[_one(acc) for acc in accounts],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, int):
                total += r
            elif isinstance(r, BaseException):
                logger.warning("IMAP manual poll account failed: %s", r)
    if accounts:
        logger.info(
            "IMAP manual poll user_id=%s: %s account(s), %s new card(s), catch_up=%s",
            uid,
            len(accounts),
            total,
            catch_up,
        )
    return len(accounts), total


async def _flush_pending_notifications(bot: Bot) -> int:
    """Карточки, которые попали в БД, но не ушли в Telegram."""
    pending = await list_incoming_pending_notify(limit=80)
    sent = 0
    for row in pending:
        uid = int(row["user_id"])
        acc_id = int(row["account_id"])
        mail_id = int(row["id"])
        from_email = (row.get("from_email") or "").strip()
        is_first = await incoming_is_first_from_sender(
            int(row["account_id"]), from_email, int(mail_id)
        )
        meta = {
            "lead_id": row.get("lead_id"),
            "product_title": row.get("product_title") or "",
            "photo_url": row.get("photo_url") or "",
            "offer_price": row.get("offer_price") or "",
            "service_label": row.get("service_label") or "",
        }
        try:
            await _notify_incoming(
                bot,
                chat_id=uid,
                user_id=uid,
                account_id=acc_id,
                inbox_label="",
                mail_id=mail_id,
                is_first_from_sender=is_first,
                meta=meta,
            )
            sent += 1
        except Exception:
            logger.exception("retry notify mail_id=%s", mail_id)
    if sent:
        logger.info("IMAP retry notify: %s card(s)", sent)
    return sent


async def _poll_loop(bot: Bot) -> None:
    sem = asyncio.Semaphore(MAX_IMAP_CONCURRENT)

    async def _one(acc: dict) -> int:
        async with sem:
            return await _process_account(bot, acc)

    while True:
        try:
            accounts = await list_imap_poll_accounts()
            new_cards = 0
            if accounts:
                results = await asyncio.gather(
                    *[_one(acc) for acc in accounts],
                    return_exceptions=True,
                )
                for r in results:
                    if isinstance(r, Exception):
                        logger.error("IMAP account poll error: %s", r)
                    else:
                        new_cards += int(r)
            new_cards += await _flush_pending_notifications(bot)
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
            accs = await list_imap_poll_accounts()
            by_user: dict[int, int] = {}
            for a in accs:
                uid = int(a.get("user_id") or 0)
                by_user[uid] = by_user.get(uid, 0) + 1
            logger.info(
                "Incoming IMAP worker started (poll=%ss, total_mailboxes=%s, users=%s)",
                POLL_SEC,
                len(accs),
                len(by_user),
            )
            for uid, cnt in sorted(by_user.items()):
                logger.info("IMAP user_id=%s: %s active mailbox(es)", uid, cnt)
        except Exception:
            logger.info("Incoming IMAP worker started (poll=%ss)", POLL_SEC)

    asyncio.create_task(_log_accounts())


def stop_incoming_mail_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None

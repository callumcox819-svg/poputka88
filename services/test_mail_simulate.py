"""Симуляция входящего ответа продавца (карточка + фото на первое письмо)."""

from __future__ import annotations

import json
import time
from typing import Any

from aiogram import Bot

from database import (
    count_incoming_from_sender,
    get_validated_lead_by_email,
    insert_incoming_mail,
    list_smtp_mailing_accounts,
    save_validated_lead,
)
from services.imap_fetch import service_label_from_link
from services.incoming_worker import _notify_incoming
from services.lead_keys import email_norm_key, seller_match_key, title_match_key


async def _ensure_fixture_lead(user_id: int, fx: dict[str, Any]) -> int | None:
    email = (fx.get("seller_email") or "").strip().lower()
    if not email:
        return None
    person = (fx.get("person_name") or "").strip()
    local, _, domain = email.partition("@")
    raw = json.dumps(fx, ensure_ascii=False)
    created, _ = await save_validated_lead(
        user_id,
        email=email,
        person_name=person,
        email_local=local,
        email_domain=domain,
        item_title=(fx.get("item_title") or "").strip(),
        item_price=(fx.get("item_price") or "").strip(),
        item_link=(fx.get("item_link") or "").strip(),
        person_link="",
        location=(fx.get("location") or "").strip(),
        item_photo=(fx.get("item_photo") or "").strip(),
        raw_json=raw,
        email_norm=email_norm_key(email),
        seller_key=seller_match_key(person),
        title_key=title_match_key(fx.get("item_title") or ""),
    )
    lead = await get_validated_lead_by_email(user_id, email)
    return int(lead["id"]) if lead else None


async def simulate_seller_reply(
    bot: Bot,
    user_id: int,
    fixture: dict[str, Any],
) -> tuple[bool, str]:
    """
    Вставить тестовое входящее от продавца (как IMAP).
    На первое письмо от этого email — фото товара под карточкой.
    """
    accounts = await list_smtp_mailing_accounts(user_id, with_secrets=False)
    if not accounts:
        return False, "Нет SMTP-аккаунтов. Добавьте в ⚡ Быстрое добавление."

    acc = accounts[0]
    acc_id = int(acc["id"])
    account_email = (acc.get("email") or "").strip()
    from_email = (fixture.get("seller_email") or "").strip().lower()
    from_name = (fixture.get("person_name") or "").strip()
    if not from_email:
        return False, "Нет test seller email в фикстуре"

    lead_id = await _ensure_fixture_lead(user_id, fixture)
    prior = await count_incoming_from_sender(acc_id, from_email)
    is_first = prior == 0

    title = (fixture.get("item_title") or "").strip()
    subject = f"Re: {title}" if title else "Re: Ihre Anzeige"
    body = (fixture.get("reply_body") or "Hallo, ist der Artikel noch verfügbar?").strip()
    link = (fixture.get("item_link") or "").strip()
    svc = service_label_from_link(link) or "Marketplace"

    imap_uid = f"test{int(time.time() * 1000)}"
    mail_id = await insert_incoming_mail(
        user_id,
        acc_id,
        imap_uid=imap_uid,
        message_id=f"test-{imap_uid}",
        account_email=account_email,
        from_email=from_email,
        from_name=from_name,
        subject=subject,
        body=body,
        lead_id=lead_id,
        product_title=title,
        service_label=svc,
        photo_url=(fixture.get("item_photo") or "").strip(),
        offer_price=(fixture.get("item_price") or "").strip(),
    )
    if not mail_id:
        return False, "Не удалось сохранить письмо в БД"

    meta = {
        "lead_id": lead_id,
        "product_title": title,
        "photo_url": (fixture.get("item_photo") or "").strip(),
        "offer_price": (fixture.get("item_price") or "").strip(),
        "service_label": svc,
    }
    inbox_label = (acc.get("sender_name") or "").strip()
    try:
        await _notify_incoming(
            bot,
            chat_id=user_id,
            user_id=user_id,
            account_id=acc_id,
            inbox_label=inbox_label,
            mail_id=mail_id,
            is_first_from_sender=is_first,
            meta=meta,
        )
    except Exception as exc:
        return False, str(exc)[:300]

    photo_hint = " + 📷 фото товара" if is_first and meta.get("photo_url") else ""
    repeat_hint = " (повтор — без фото)" if not is_first else ""
    return (
        True,
        f"Карточка #{mail_id} от <code>{from_email}</code>{photo_hint}{repeat_hint}. "
        f"Дальше: «Создать ссылку» → HTML.",
    )

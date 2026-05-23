"""Рассылка: тема письма = OFFER → название товара (item_title) продавца."""

from __future__ import annotations

import re

from database import get_validated_lead_by_email

# Маркер в кампании: при отправке заменяется на item_title лида.
MAILING_SUBJECT_OFFER = "OFFER"


def sanitize_email_subject(text: str) -> str:
    s = (text or "").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()


async def offer_title_for_recipient(user_id: int, recipient_email: str) -> str:
    lead = await get_validated_lead_by_email(user_id, recipient_email)
    if not lead:
        return ""
    return (lead.get("item_title") or "").strip()


async def mailing_subject_for_recipient(user_id: int, recipient_email: str) -> str:
    """Тема plain-рассылки: только название товара из валидации."""
    title = sanitize_email_subject(await offer_title_for_recipient(user_id, recipient_email))
    if not title:
        return MAILING_SUBJECT_OFFER
    if len(title) > 140:
        return title[:137] + "…"
    return title

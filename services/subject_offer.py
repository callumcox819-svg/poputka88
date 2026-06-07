"""Рассылка: тема письма = OFFER → название товара (item_title) продавца."""

from __future__ import annotations

import re

from database import get_validated_lead_by_email, get_validated_leads_by_emails

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


def _subject_from_title(title: str) -> str:
    t = sanitize_email_subject(title)
    if not t:
        return MAILING_SUBJECT_OFFER
    if len(t) > 140:
        return t[:137] + "…"
    return t


async def batch_offer_titles_for_recipients(
    user_id: int, recipient_emails: list[str]
) -> dict[str, str]:
    leads = await get_validated_leads_by_emails(user_id, recipient_emails)
    out: dict[str, str] = {}
    for em in recipient_emails:
        key = (em or "").strip().lower()
        if not key:
            continue
        out[key] = (leads.get(key) or {}).get("item_title") or ""
        out[key] = str(out[key]).strip()
    return out


async def batch_mailing_subjects_for_recipients(
    user_id: int, recipient_emails: list[str]
) -> dict[str, str]:
    titles = await batch_offer_titles_for_recipients(user_id, recipient_emails)
    return {em: _subject_from_title(titles.get(em, "")) for em in titles}


async def batch_recipient_mailing_meta(
    user_id: int, recipient_emails: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Один SELECT: (offer_title по email, subject по email)."""
    titles = await batch_offer_titles_for_recipients(user_id, recipient_emails)
    subjects = {em: _subject_from_title(t) for em, t in titles.items()}
    return titles, subjects

"""
Поиск лида для «Создать ссылку» — только тот товар, что в validated_leads.

Чёрный список продавцов = один лид на продавца. Генерация не ищет по названию/имени
(чтобы не подтянуть чужой товар), только:
  lead_id → рассылка (recipients.lead_id) → email → тот же email без точек.
"""

from __future__ import annotations

from dataclasses import dataclass

from database import (
    find_lead_by_incoming_subject,
    find_lead_by_recent_mailing,
    get_lead_for_mailing_recipient,
    get_validated_lead_by_email,
    get_validated_lead_by_id,
    get_validated_lead_by_reply_email,
)
from services.test_mail_lead import resolve_lead_for_test_reply


@dataclass(frozen=True)
class LeadResolveResult:
    lead: dict
    matched_by: str


async def resolve_validated_lead(
    user_id: int,
    *,
    lead_id: int | None = None,
    contact_email: str = "",
    campaign_id: int | None = None,
    subject: str = "",
) -> LeadResolveResult | None:
    uid = int(user_id)

    if lead_id and int(lead_id) > 0:
        lead = await get_validated_lead_by_id(uid, int(lead_id))
        if lead:
            return LeadResolveResult(lead=lead, matched_by="lead_id")

    email = (contact_email or "").strip().lower()
    if not email:
        return None

    lead = await get_lead_for_mailing_recipient(
        uid, email, campaign_id=campaign_id
    )
    if lead:
        return LeadResolveResult(lead=lead, matched_by="mailing")

    lead = await get_validated_lead_by_email(uid, email)
    if lead:
        return LeadResolveResult(lead=lead, matched_by="email")

    lead = await get_validated_lead_by_reply_email(uid, email)
    if lead:
        return LeadResolveResult(lead=lead, matched_by="email_fuzzy")

    lead = await find_lead_by_recent_mailing(
        uid, contact_email=email, subject=subject
    )
    if lead:
        return LeadResolveResult(lead=lead, matched_by="mailing_subject")

    if (subject or "").strip():
        lead = await find_lead_by_incoming_subject(uid, subject)
        if lead:
            return LeadResolveResult(lead=lead, matched_by="subject")

    lead = await resolve_lead_for_test_reply(
        uid, contact_email=email, subject=subject
    )
    if lead:
        return LeadResolveResult(lead=lead, matched_by="test_mail")

    return None

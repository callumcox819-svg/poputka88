"""
Создание GAG-ссылки по кнопке «Создать ссылку».

Только строка validated_leads из рассылки / ответа (без поиска по названию товара).
"""

from __future__ import annotations

from dataclasses import dataclass

from database import get_validated_lead_by_id, save_incoming_gag_link, update_incoming_mail_lead_snapshot
from services.imap_fetch import service_label_from_link
from services.gag_network import GAGError
from services.gag_user import (
    GagNotConfiguredError,
    ad_id_from_url,
    generate_link_for_lead,
)
from services.lead_resolve import resolve_validated_lead


@dataclass(frozen=True)
class GagLinkResult:
    url: str
    ad_id: str | None
    lead_id: int
    contact_email: str
    item_title: str
    matched_by: str


async def create_gag_link_for_incoming(
    user_id: int,
    *,
    contact_email: str = "",
    campaign_id: int | None = None,
    lead_id: int | None = None,
    incoming_mail_id: int | None = None,
    subject: str = "",
) -> GagLinkResult:
    """
    Генерация строго по лиду из БД (товар при валидации + рассылка).
    contact_email — From входящего или email из рассылки.
    """
    resolved = await resolve_validated_lead(
        user_id,
        lead_id=lead_id,
        contact_email=contact_email,
        campaign_id=campaign_id,
        subject=subject,
    )
    if not resolved:
        em = (contact_email or "").strip().lower() or "—"
        raise GagNotConfiguredError(
            f"Нет валидированного лида для <code>{em}</code>.\n"
            "Нужна валидация этого продавца (или ответ с почты из рассылки)."
        )

    lead = resolved.lead
    if incoming_mail_id:
        link = (lead.get("item_link") or "").strip()
        svc = service_label_from_link(link) or ""
        await update_incoming_mail_lead_snapshot(
            incoming_mail_id,
            user_id,
            lead_id=int(lead["id"]),
            product_title=(lead.get("item_title") or "").strip(),
            service_label=svc,
            photo_url=(lead.get("item_photo") or "").strip(),
            offer_price=(lead.get("item_price") or "").strip(),
        )
    try:
        url = await generate_link_for_lead(user_id, lead)
    except GAGError as exc:
        raise GagNotConfiguredError(str(exc)) from exc

    ad_id = ad_id_from_url(url)
    if incoming_mail_id:
        await save_incoming_gag_link(
            incoming_mail_id,
            user_id,
            url=url,
            gag_ad_id=ad_id or "",
        )

    canonical_email = str(lead.get("email") or "").strip().lower()
    return GagLinkResult(
        url=url,
        ad_id=ad_id,
        lead_id=int(lead["id"]),
        contact_email=canonical_email or contact_email.strip().lower(),
        item_title=(lead.get("item_title") or "").strip(),
        matched_by=resolved.matched_by,
    )


async def create_gag_link_for_contact(
    user_id: int,
    contact_email: str,
    *,
    campaign_id: int | None = None,
    lead_id: int | None = None,
    incoming_mail_id: int | None = None,
) -> GagLinkResult:
    return await create_gag_link_for_incoming(
        user_id,
        contact_email=contact_email,
        campaign_id=campaign_id,
        lead_id=lead_id,
        incoming_mail_id=incoming_mail_id,
    )


async def create_gag_link_for_lead_id(
    user_id: int,
    lead_id: int,
    *,
    incoming_mail_id: int | None = None,
) -> GagLinkResult:
    return await create_gag_link_for_incoming(
        user_id,
        lead_id=lead_id,
        incoming_mail_id=incoming_mail_id,
    )

"""
Создание GAG-ссылки по кнопке «Создать ссылку».

Только строка validated_leads из рассылки / ответа (без поиска по названию товара).
"""

from __future__ import annotations

from dataclasses import dataclass

from database import (
    get_validated_lead_by_id,
    propagate_gag_link_for_lead,
    save_incoming_gag_link,
    update_incoming_mail_lead_snapshot,
)
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
    canonical_email = str(lead.get("email") or "").strip().lower()
    await propagate_gag_link_for_lead(
        user_id,
        lead_id=int(lead["id"]),
        seller_email=canonical_email,
        url=url,
        gag_ad_id=ad_id or "",
        offer_price=(lead.get("item_price") or "").strip(),
    )
    if incoming_mail_id:
        await save_incoming_gag_link(
            incoming_mail_id,
            user_id,
            url=url,
            gag_ad_id=ad_id or "",
        )

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


async def regenerate_gag_link_for_lead(
    user_id: int,
    lead_id: int,
    *,
    offer_price: str | None = None,
) -> GagLinkResult:
    """
    Новая GAG-ссылка с актуальной ценой из validated_leads
    и запись во все incoming_mails этого продавца (HTML берёт ссылку оттуда).
    """
    lead = await get_validated_lead_by_id(user_id, int(lead_id))
    if not lead:
        raise GagNotConfiguredError("Лид не найден.")

    try:
        url = await generate_link_for_lead(user_id, lead)
    except GAGError as exc:
        raise GagNotConfiguredError(str(exc)) from exc

    ad_id = ad_id_from_url(url)
    price = (offer_price if offer_price is not None else lead.get("item_price") or "")
    price = str(price).strip()
    seller = str(lead.get("email") or "").strip().lower()

    await propagate_gag_link_for_lead(
        user_id,
        lead_id=int(lead_id),
        seller_email=seller,
        url=url,
        gag_ad_id=ad_id or "",
        offer_price=price,
    )

    return GagLinkResult(
        url=url,
        ad_id=ad_id,
        lead_id=int(lead_id),
        contact_email=seller,
        item_title=(lead.get("item_title") or "").strip(),
        matched_by="regenerate_price",
    )

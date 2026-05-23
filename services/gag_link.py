"""
Создание GAG-ссылки по кнопке «Создать ссылку» (без автогенерации).

Поиск лида: offer_id → email → email без точек → название → имя продавца.
"""

from __future__ import annotations

from dataclasses import dataclass

from database import get_validated_lead_by_id, save_incoming_gag_link
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
    matched_by: str


async def create_gag_link_for_incoming(
    user_id: int,
    *,
    contact_email: str = "",
    subject: str = "",
    from_name: str = "",
    item_title: str = "",
    offer_id: int | None = None,
    incoming_mail_id: int | None = None,
) -> GagLinkResult:
    """
    Ссылка строго по данным validated_leads.
    Письмо сопоставляется по email / fuzzy email / title / seller / offer_id.
    """
    resolved = await resolve_validated_lead(
        user_id,
        contact_email=contact_email,
        subject=subject,
        from_name=from_name,
        item_title=item_title,
        offer_id=offer_id,
    )
    if not resolved:
        hints = []
        if contact_email:
            hints.append(f"email: {contact_email.strip().lower()}")
        if item_title:
            hints.append(f"товар: {item_title[:80]}")
        if from_name:
            hints.append(f"имя: {from_name[:80]}")
        if offer_id:
            hints.append(f"offer_id: {offer_id}")
        extra = (" (" + ", ".join(hints) + ")") if hints else ""
        raise GagNotConfiguredError(
            "Не найден лид в БД для этого письма" + extra + ". "
            "Нужна валидация JSON с этим продавцом/товаром."
        )

    lead = resolved.lead
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

    return GagLinkResult(
        url=url,
        ad_id=ad_id,
        lead_id=int(lead["id"]),
        contact_email=str(lead.get("email") or contact_email.strip().lower()),
        matched_by=resolved.matched_by,
    )


async def create_gag_link_for_contact(
    user_id: int,
    contact_email: str,
    *,
    incoming_mail_id: int | None = None,
    subject: str = "",
    from_name: str = "",
    item_title: str = "",
    offer_id: int | None = None,
) -> GagLinkResult:
    """Обёртка: только email + опциональные подсказки с карточки письма."""
    return await create_gag_link_for_incoming(
        user_id,
        contact_email=contact_email,
        subject=subject,
        from_name=from_name,
        item_title=item_title,
        offer_id=offer_id,
        incoming_mail_id=incoming_mail_id,
    )


async def create_gag_link_for_lead_id(
    user_id: int,
    lead_id: int,
    *,
    incoming_mail_id: int | None = None,
) -> GagLinkResult:
    lead = await get_validated_lead_by_id(user_id, lead_id)
    if not lead:
        raise GagNotConfiguredError("Лид не найден в БД.")

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

    return GagLinkResult(
        url=url,
        ad_id=ad_id,
        lead_id=int(lead["id"]),
        contact_email=str(lead.get("email") or ""),
        matched_by="lead_id",
    )

"""Поиск validated_leads для кнопки «Создать ссылку»."""

from __future__ import annotations

from dataclasses import dataclass

from database import (
    find_lead_by_email_norm,
    find_lead_by_exact_email,
    find_lead_by_offer_id,
    find_lead_by_seller_key,
    find_lead_by_title,
)
from services.lead_keys import (
    email_norm_key,
    offer_id_from_item,
    seller_match_key,
    title_match_key,
)


@dataclass(frozen=True)
class LeadResolveResult:
    lead: dict
    matched_by: str


async def resolve_validated_lead(
    user_id: int,
    *,
    contact_email: str = "",
    subject: str = "",
    from_name: str = "",
    item_title: str = "",
    offer_id: int | None = None,
) -> LeadResolveResult | None:
    """
    Порядок (как в happy88 — надёжные ключи первыми):
    1) offer_id
    2) email точный
    3) email «мягкий» (без точек в local-part)
    4) название товара (item_title / тема)
    5) имя продавца (From / item_person_name в БД)
    """
    uid = int(user_id)

    if offer_id and int(offer_id) > 0:
        lead = await find_lead_by_offer_id(uid, int(offer_id))
        if lead:
            return LeadResolveResult(lead=lead, matched_by="offer_id")

    email = (contact_email or "").strip().lower()
    if email:
        lead = await find_lead_by_exact_email(uid, email)
        if lead:
            return LeadResolveResult(lead=lead, matched_by="email")

        norm = email_norm_key(email)
        if norm:
            lead = await find_lead_by_email_norm(uid, norm)
            if lead:
                return LeadResolveResult(lead=lead, matched_by="email_fuzzy")

    for title_src in (item_title, subject):
        tkey = title_match_key(title_src)
        if not tkey:
            continue
        lead = await find_lead_by_title(uid, tkey)
        if lead:
            return LeadResolveResult(lead=lead, matched_by="item_title")

    for name_src in (from_name,):
        skey = seller_match_key(name_src)
        if not skey:
            continue
        lead = await find_lead_by_seller_key(uid, skey)
        if lead:
            return LeadResolveResult(lead=lead, matched_by="seller_name")

    return None


def offer_id_from_mail_meta(
    *,
    offer_id: int | None = None,
    item: dict | None = None,
) -> int | None:
    if offer_id and int(offer_id) > 0:
        return int(offer_id)
    if item:
        return offer_id_from_item(item)
    return None

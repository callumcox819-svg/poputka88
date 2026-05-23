"""Тема, имя и контекст для HTML-ответов на входящие (как happy88)."""

from __future__ import annotations

from database import get_validated_lead_by_email, get_validated_lead_by_id
from services.gag_keys import GAG_PROFILE_ADDRESS_KEY, GAG_PROFILE_NAME_KEY
from services.html_spoof import _resolve_spoof_from_name
from services.user_settings import SPOOF_SUBJECT_KEY, get_setting


async def get_mandatory_html_subject(user_id: int) -> str | None:
    subj = (await get_setting(user_id, SPOOF_SUBJECT_KEY) or "").strip()
    return subj[:140] if subj else None


async def get_mandatory_html_sender_name(user_id: int) -> str | None:
    name = await _resolve_spoof_from_name(user_id)
    return name or None


async def build_incoming_html_ctx(
    user_id: int,
    mail: dict,
    *,
    gag_link: str,
) -> dict[str, str]:
    buyer = (await get_setting(user_id, GAG_PROFILE_NAME_KEY) or "").strip()
    address = (await get_setting(user_id, GAG_PROFILE_ADDRESS_KEY) or "").strip()
    seller = (mail.get("from_email") or "").strip().lower()

    title = (mail.get("product_title") or "").strip()
    price = (mail.get("offer_price") or "").strip()
    photo = (mail.get("photo_url") or "").strip()

    lead_id = mail.get("lead_id")
    lead = None
    if lead_id:
        lead = await get_validated_lead_by_id(user_id, int(lead_id))
    if not lead and seller:
        lead = await get_validated_lead_by_email(user_id, seller)
    if lead:
        if not title:
            title = (lead.get("item_title") or "").strip()
        if not price:
            price = _format_chf_price(str(lead.get("item_price") or ""))
        if not photo:
            photo = (lead.get("item_photo") or "").strip()

    return {
        "ITEM_TITLE": title,
        "PRICE": price,
        "IMAGE_URL": photo,
        "SELLER_EMAIL": seller,
        "BUYER_NAME": buyer,
        "ADDRESS": address,
        "LINK": (gag_link or "").strip(),
    }


def _format_chf_price(price: str) -> str:
    p = (price or "").strip()
    if not p:
        return ""
    if p.upper().startswith("CHF"):
        return p
    return f"CHF {p}"

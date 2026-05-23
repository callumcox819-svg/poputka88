"""Профиль и вызовы GAG для пользователя (SQLite user_settings)."""

from __future__ import annotations

from dataclasses import dataclass

from services.gag_keys import (
    GAG_API_KEY,
    GAG_DOMAIN_SLOT_KEY,
    GAG_PROFILE_ADDRESS_KEY,
    GAG_PROFILE_NAME_KEY,
    GAG_PROFILE_TITLE_KEY,
    GAG_SERVICE_KEY,
    gag_api_domain_param,
    gag_default_version,
    gag_generate_endpoint,
    gag_send_email_endpoint,
    gag_service_for_api,
    get_user_gag_api_key,
    is_valid_gag_service,
    parse_gag_domain_slot,
    resolve_gag_service,
)
from services.gag_network import GAGError, generate_gag_url, send_gag_email
from services.link_id import link_id_from_generated_url
from services.user_settings import get_setting


@dataclass(frozen=True)
class GagProfile:
    title: str
    name: str
    address: str
    service: str | None
    service_label: str
    domain_slot: int | None
    api_key_set: bool


class GagNotConfiguredError(Exception):
    pass


async def load_gag_profile(user_id: int) -> GagProfile:
    from services.gag_keys import gag_service_label

    title = (await get_setting(user_id, GAG_PROFILE_TITLE_KEY) or "").strip()
    name = (await get_setting(user_id, GAG_PROFILE_NAME_KEY) or "").strip()
    addr = (await get_setting(user_id, GAG_PROFILE_ADDRESS_KEY) or "").strip()
    svc = (await get_setting(user_id, GAG_SERVICE_KEY) or "").strip() or None
    slot_raw = await get_setting(user_id, GAG_DOMAIN_SLOT_KEY)
    slot = parse_gag_domain_slot(slot_raw)
    key = await get_user_gag_api_key(user_id)

    return GagProfile(
        title=title,
        name=name,
        address=addr,
        service=svc,
        service_label=gag_service_label(svc) if svc else "—",
        domain_slot=slot,
        api_key_set=bool(key),
    )


def profile_ready(profile: GagProfile) -> bool:
    return bool(profile.title and profile.name and profile.address)


def _gag_fields_from_lead_row(lead: dict) -> dict[str, str | None]:
    """Только колонки validated_leads (+ raw_json этого же лида при пустых полях)."""
    import json

    title = (lead.get("item_title") or "").strip()
    price = (lead.get("item_price") or "").strip()
    link = (lead.get("item_link") or "").strip()
    photo = (lead.get("item_photo") or "").strip()

    if not title or not price:
        raw = (lead.get("raw_json") or "").strip()
        if raw:
            try:
                item = json.loads(raw)
                if isinstance(item, dict):
                    if not title:
                        title = str(
                            item.get("item_title")
                            or item.get("title")
                            or item.get("product_title")
                            or ""
                        ).strip()
                    if not price:
                        price = str(
                            item.get("item_price")
                            or item.get("price")
                            or item.get("offer_price")
                            or ""
                        ).strip()
                    if not link:
                        link = str(
                            item.get("item_link")
                            or item.get("link")
                            or item.get("url")
                            or ""
                        ).strip()
                    if not photo:
                        photo = str(
                            item.get("item_photo")
                            or item.get("photo")
                            or item.get("image")
                            or ""
                        ).strip()
            except json.JSONDecodeError:
                pass

    return {
        "title": title,
        "price": price or "0",
        "offer_link": link,
        "image": photo or None,
    }


async def generate_link_for_lead(user_id: int, lead: dict) -> str:
    """
    GAG /generate строго по сохранённому лиду (товар при валидации).
    name/address — из профиля GAG в настройках.
    """
    fields = _gag_fields_from_lead_row(lead)
    title = fields["title"] or ""
    if not title:
        raise GagNotConfiguredError(
            "У лида нет названия объявления. Прогоните валидацию JSON заново."
        )
    return await generate_link_for_user(
        user_id,
        title=title,
        price=str(fields["price"] or "0"),
        offer_link=str(fields["offer_link"] or ""),
        image=fields["image"],
    )


async def generate_link_for_user(
    user_id: int,
    *,
    title: str,
    price: str,
    offer_link: str = "",
    image: str | None = None,
    balance_checker: int | None = None,
) -> str:
    apikey = await get_user_gag_api_key(user_id)
    if not apikey:
        raise GagNotConfiguredError("API-ключ GAG не установлен (⚙️ → 🔑 Ключ).")

    profile = await load_gag_profile(user_id)
    if not profile_ready(profile):
        raise GagNotConfiguredError(
            "Профиль GAG не заполнен (⚙️ → 🧾 Профиль → Создать профиль)."
        )

    service = resolve_gag_service(
        offer_link=offer_link, user_setting=profile.service
    )
    if not service or not is_valid_gag_service(service):
        raise GagNotConfiguredError(
            "Не выбран сервис GAG (🧾 Профиль → 🧭 Выбор сервиса)."
        )

    url = await generate_gag_url(
        endpoint=gag_generate_endpoint(),
        apikey=apikey,
        title=title.strip(),
        price=(price or "").strip() or "0",
        service=gag_service_for_api(service),
        name=profile.name,
        address=profile.address,
        image=(image or "").strip() or None,
        balanceChecker=balance_checker,
        domain=gag_api_domain_param(profile.domain_slot),
        version=gag_default_version(),
    )
    return url


async def send_email_for_user(
    user_id: int,
    *,
    ad_id: str,
    email: str,
    mailer: str,
    status: str,
    domain: str | None = None,
    lang: str | None = None,
    subject_type: str | None = None,
) -> dict:
    apikey = await get_user_gag_api_key(user_id)
    if not apikey:
        raise GagNotConfiguredError("API-ключ GAG не установлен.")

    return await send_gag_email(
        endpoint=gag_send_email_endpoint(),
        apikey=apikey,
        ad_id=str(ad_id).strip(),
        email=email.strip(),
        mailer=mailer.strip(),
        status=status.strip(),
        domain=domain,
        lang=lang,
        subject_type=subject_type,
    )


def ad_id_from_url(url: str) -> str | None:
    return link_id_from_generated_url(url)


__all__ = [
    "GAGError",
    "GagNotConfiguredError",
    "GagProfile",
    "ad_id_from_url",
    "generate_link_for_lead",
    "generate_link_for_user",
    "load_gag_profile",
    "profile_ready",
    "send_email_for_user",
]

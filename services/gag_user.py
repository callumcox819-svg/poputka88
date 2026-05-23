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
    "generate_link_for_user",
    "load_gag_profile",
    "profile_ready",
    "send_email_for_user",
]

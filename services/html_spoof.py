"""HTML: обязательные имя/тема из спуфинга + {{NICK}}."""

from __future__ import annotations

from database import get_user_sender_name, list_smtp_mailing_accounts
from services.user_settings import (
    SPOOF_FROM_NAME_KEY,
    SPOOF_SUBJECT_KEY,
    get_setting,
    set_setting,
)

SPOOFING_KEY = "spoofing"


class HtmlOutboundError(ValueError):
    """HTML нельзя отправить (нет прокси, спуфинга или GAG-ссылки)."""


def apply_nick_to_html(html: str, nick: str | None) -> str:
    if not nick:
        return html
    return html.replace("{{NICK}}", nick)


async def _resolve_spoof_from_name(user_id: int) -> str:
    name = (await get_setting(user_id, SPOOF_FROM_NAME_KEY) or "").strip()
    if name:
        return name
    legacy = (await get_user_sender_name(user_id) or "").strip()
    if not legacy:
        return ""
    accounts = await list_smtp_mailing_accounts(user_id)
    account_names = {
        (a.get("sender_name") or "").strip()
        for a in accounts
        if (a.get("sender_name") or "").strip()
    }
    if account_names and legacy in account_names:
        return ""
    await set_setting(user_id, SPOOF_FROM_NAME_KEY, legacy)
    return legacy


async def get_mandatory_spoof_name(user_id: int) -> str:
    name = await _resolve_spoof_from_name(user_id)
    if not name:
        raise HtmlOutboundError(
            "Для HTML задайте имя в ⚙️ Настройки → 👤 Имя для спуфинга (минимум 2 слова)."
        )
    return name


async def get_mandatory_spoof_subject(user_id: int) -> str:
    """Тема HTML — только из «Установить тему», не из входящего / Re:."""
    subj = (await get_setting(user_id, SPOOF_SUBJECT_KEY) or "").strip()
    if not subj:
        raise HtmlOutboundError(
            "Для HTML задайте тему в ⚙️ Настройки → 👤 Имя для спуфинга → ✅ Установить тему."
        )
    return subj[:140]


async def prepare_html_outbound(
    user_id: int,
    *,
    subject: str,
    body: str,
    is_html: bool,
) -> tuple[str, str, str | None]:
    """
    HTML: всегда тема и From из спуфинга, в теле — {{NICK}}.
    """
    if not is_html:
        return subject, body, None

    name = await get_mandatory_spoof_name(user_id)
    out_subject = await get_mandatory_spoof_subject(user_id)
    out_body = apply_nick_to_html(body, name)
    return out_subject, out_body, name

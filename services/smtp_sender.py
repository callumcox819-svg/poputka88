"""SMTP send with correct MIME encoding.

Для бота используйте services.mail_outbound.send_mail — там политика прокси.
"""

from __future__ import annotations

import ssl
from email.message import EmailMessage
from email.policy import SMTP
from typing import Any, Literal

import aiosmtplib

from config import Settings
from services.encoding import TransferEncoding, resolve_encoding
from services.proxy_smtp import send_via_proxy

EncodingName = Literal["7bit", "quoted-printable", "base64"]


def build_message(
    *,
    mail_from: str,
    to_addr: str,
    subject: str,
    body: str,
    is_html: bool,
    encoding: EncodingName,
    reply_to: str | None = None,
) -> EmailMessage:
    msg = EmailMessage(policy=SMTP)
    msg["From"] = mail_from
    msg["To"] = to_addr
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to

    subtype = "html" if is_html else "plain"
    charset = "us-ascii" if encoding == "7bit" else "utf-8"

    if encoding == "7bit":
        msg.set_content(body, subtype=subtype, charset=charset, cte="7bit")
    elif encoding == "quoted-printable":
        msg.set_content(body, subtype=subtype, charset=charset, cte="quoted-printable")
    else:
        msg.set_content(body, subtype=subtype, charset=charset, cte="base64")

    return msg


def format_from_header(account: dict[str, Any]) -> str:
    name = (account.get("sender_name") or "").strip()
    email = account["email"]
    if name:
        return f'"{name}" <{email}>'
    return email


def format_from_with_name(email: str, display_name: str | None) -> str:
    name = (display_name or "").strip()
    if name:
        return f'"{name}" <{email}>'
    return email


async def send_one(
    settings: Settings,
    *,
    to_addr: str,
    subject: str,
    body: str,
    is_html: bool,
    transfer: TransferEncoding = TransferEncoding.AUTO,
    reply_to: str | None = None,
    account: dict[str, Any] | None = None,
    from_display_name: str | None = None,
    use_tls: bool | None = None,
    proxy: dict[str, Any] | None = None,
) -> EncodingName:
    enc = resolve_encoding(transfer, body, is_html=is_html)

    if account:
        if from_display_name:
            mail_from = format_from_with_name(account["email"], from_display_name)
        else:
            mail_from = format_from_header(account)
        host = account["smtp_host"]
        port = int(account["smtp_port"])
        user = account["email"]
        password = account["password"]
        tls_default = port != 25
    else:
        mail_from = settings.smtp_from
        host = settings.smtp_host
        port = settings.smtp_port
        user = settings.smtp_user
        password = settings.smtp_password
        tls_default = settings.smtp_use_tls

    message = build_message(
        mail_from=mail_from,
        to_addr=to_addr,
        subject=subject,
        body=body,
        is_html=is_html,
        encoding=enc,
        reply_to=reply_to,
    )

    if proxy:
        await send_via_proxy(
            proxy,
            smtp_host=host,
            smtp_port=port,
            login=user or "",
            password=password or "",
            mail_from=mail_from,
            to_addr=to_addr,
            message=message,
        )
        return enc

    tls_on = tls_default if use_tls is None else use_tls
    tls_ctx = ssl.create_default_context()
    use_ssl = tls_on and port == 465

    await aiosmtplib.send(
        message,
        hostname=host,
        port=port,
        username=user or None,
        password=password or None,
        start_tls=tls_on and not use_ssl,
        use_tls=use_ssl,
        tls_context=tls_ctx,
    )
    return enc

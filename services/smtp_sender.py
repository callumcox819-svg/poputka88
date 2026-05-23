"""SMTP send with correct MIME encoding."""

from __future__ import annotations

import ssl
from email.message import EmailMessage
from email.policy import SMTP
from typing import Literal

import aiosmtplib

from config import Settings
from services.encoding import TransferEncoding, resolve_encoding

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


async def send_one(
    settings: Settings,
    *,
    to_addr: str,
    subject: str,
    body: str,
    is_html: bool,
    transfer: TransferEncoding = TransferEncoding.AUTO,
    reply_to: str | None = None,
) -> EncodingName:
    enc = resolve_encoding(transfer, body, is_html=is_html)
    message = build_message(
        mail_from=settings.smtp_from,
        to_addr=to_addr,
        subject=subject,
        body=body,
        is_html=is_html,
        encoding=enc,
        reply_to=reply_to,
    )

    tls_ctx = ssl.create_default_context()
    use_tls = settings.smtp_use_tls and settings.smtp_port == 465

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=settings.smtp_use_tls and not use_tls,
        use_tls=use_tls,
        tls_context=tls_ctx,
    )
    return enc

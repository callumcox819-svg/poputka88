"""Уведомления в Telegram после ответа на входящее (как happy88)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import BufferedInputFile

from utils.text_html import e

logger = logging.getLogger(__name__)


@dataclass
class ReplyNotifyCtx:
    anchor_message_id: int
    to_email: str
    account_email: str
    is_html: bool = False
    html_attachment: str | None = None
    html_filename: str | None = None
    cleanup_message_ids: list[int] = field(default_factory=list)


def html_attachment_filename(subject: str) -> str:
    base = re.sub(r"[^\w\-]+", "_", (subject or "reply")[:60]).strip("_") or "reply"
    return f"{base}.html"


async def _delete_message_safe(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
    except Exception:
        pass


async def _try_pin(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.pin_chat_message(
            chat_id=chat_id, message_id=message_id, disable_notification=True
        )
    except Exception:
        pass


async def notify_reply_sent(bot: Bot, chat_id: int, ctx: ReplyNotifyCtx) -> None:
    """
    После успешной отправки HTML:
    — ответ в цепочке к карточке входящего;
    — файл .html;
    — «✅ HTML отправлен» (закрепляется).
    """
    for mid in ctx.cleanup_message_ids:
        await _delete_message_safe(bot, chat_id, mid)

    anchor = int(ctx.anchor_message_id)
    to_addr = e(ctx.to_email or "—")
    from_acc = e(ctx.account_email or "—")

    if ctx.is_html:
        body_part = "<b>[HTML]</b>"
    else:
        body_part = "<b>—</b>"

    main = (
        f"⚡️ Ответ {body_part} успешно отправлен на <code>{to_addr}</code> "
        f"с аккаунта <code>{from_acc}</code> ⚡️"
    )

    try:
        await bot.send_message(
            int(chat_id),
            main,
            parse_mode="HTML",
            reply_to_message_id=anchor,
        )
    except Exception:
        await bot.send_message(int(chat_id), main, parse_mode="HTML")

    if ctx.is_html and ctx.html_attachment:
        fname = (ctx.html_filename or "reply.html").strip() or "reply.html"
        try:
            doc = BufferedInputFile(
                ctx.html_attachment.encode("utf-8"),
                filename=fname,
            )
            await bot.send_document(
                int(chat_id),
                doc,
                caption="📄 HTML, который был отправлен",
                reply_to_message_id=anchor,
            )
        except Exception:
            logger.exception("send html document failed")

    footer = "✅ HTML отправлен" if ctx.is_html else None
    if footer:
        footer_msg = None
        try:
            footer_msg = await bot.send_message(
                int(chat_id),
                footer,
                parse_mode="HTML",
                reply_to_message_id=anchor,
            )
        except Exception:
            footer_msg = await bot.send_message(int(chat_id), footer, parse_mode="HTML")
        if footer_msg:
            await _try_pin(bot, int(chat_id), footer_msg.message_id)

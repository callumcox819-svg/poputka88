"""Контроль SMTP-блокировок: ящик остаётся для IMAP, с рассылки снимается."""

from __future__ import annotations

import html
import logging
import re

from aiogram import Bot

from database import (
    disable_account_fully,
    get_smtp_account,
    mark_account_smtp_blocked,
)
from services.user_settings import get_bool

logger = logging.getLogger(__name__)

_RECIPIENT_ONLY = (
    "could not be delivered to one or more recipients",
    "your email could not be delivered",
    "no such user",
    "user unknown",
    "mailbox unavailable",
    "recipient address rejected",
    "address rejected",
    "undeliverable",
    "delivery status notification",
    "mail delivery subsystem",
    "5.1.1",
    "5.1.0",
    "5.2.1",
    "5.4.4",
    "host 127.0.0.1",
    "550 5.1",
    "554 5.1",
)

_INVALID_CREDENTIALS = (
    "invalid credentials",
    "authentication failed",
    "authenticationfailure",
    "username and password not accepted",
    "username and password",
    "login failed",
    "bad credentials",
    "auth failed",
    "not accepted",
    "535 ",
    "535-",
    "534 ",
    "534-",
    "account_invalid_credentials",
)

_SMTP_BLOCK = (
    "daily user sending limit",
    "sending limit exceeded",
    "user sending limit",
    "too many messages",
    "mailbox full",
    "account has been disabled",
    "web login required",
    "5.4.5",
    "5.7.1",
    "message blocked",
    "rate limit",
    "account_blocked",
    "account_rate_limit",
    "account_web_login_required",
    "temporarily blocked",
    "suspicious activity",
    "exceeded the maximum",
)


def _norm(err: str | None) -> str:
    return re.sub(r"\s+", " ", (err or "").strip().lower())


def is_recipient_error(err: str | None) -> bool:
    s = _norm(err)
    return any(p in s for p in _RECIPIENT_ONLY)


def is_invalid_credentials_error(err: str | None) -> bool:
    s = _norm(err)
    if is_recipient_error(err):
        return False
    return any(p in s for p in _INVALID_CREDENTIALS)


def is_smtp_account_block_error(err: str | None) -> bool:
    """Ошибка ящика (лимит, блок) — не ошибка одного получателя."""
    if is_recipient_error(err):
        return False
    if is_invalid_credentials_error(err):
        return True
    s = _norm(err)
    return any(p in s for p in _SMTP_BLOCK)


def short_block_reason(err: str | None) -> str:
    return (err or "").strip()[:220]


async def handle_campaign_send_error(
    user_id: int,
    account_id: int,
    err: str,
    *,
    bot: Bot | None,
    chat_id: int | None,
) -> str | None:
    """
    При включённом block_control обрабатывает ошибку SMTP.
    Возвращает: removed_mailing | disabled_full | None.
    """
    if not await get_bool(user_id, "block_control"):
        return None

    acc = await get_smtp_account(account_id, user_id)
    if not acc:
        return None

    email = acc.get("email") or ""

    if is_invalid_credentials_error(err):
        await disable_account_fully(user_id, account_id, err)
        logger.warning("account disabled (bad creds): %s", email)
        if bot and chat_id:
            em = html.escape(email)
            await bot.send_message(
                int(chat_id),
                f"🔴 <b>{em}</b> удалён из списка (неверные данные).\n"
                f"<code>{html.escape(short_block_reason(err))}</code>",
                parse_mode="HTML",
            )
        return "disabled_full"

    if not is_smtp_account_block_error(err):
        return None

    changed = await mark_account_smtp_blocked(user_id, account_id, err)
    if not changed:
        return None

    logger.warning("smtp blocked (imap kept): %s", email)
    if bot and chat_id:
        em = html.escape(email)
        await bot.send_message(
            int(chat_id),
            f"⚡️ SMTP для <code>{em}</code> остановлен — ящик остаётся для IMAP.\n"
            f"<code>{html.escape(short_block_reason(err))}</code>",
            parse_mode="HTML",
        )
    return "removed_mailing"

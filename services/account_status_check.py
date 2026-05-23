"""Проверка статуса почт: SMTP login + IMAP."""

from __future__ import annotations

import asyncio
import ssl
from typing import Any

import aiosmtplib

from database import disable_account_fully, mark_account_smtp_blocked
from services.imap_check import check_account_imap
from services.smtp_block_control import (
    is_invalid_credentials_error,
    is_smtp_account_block_error,
    short_block_reason,
)


async def _check_smtp_login(account: dict) -> tuple[str, str | None]:
    """
    Возвращает (status, error).
    status: active | smtp_blocked | invalid | error
    """
    host = (account.get("smtp_host") or "").strip()
    port = int(account.get("smtp_port") or 587)
    user = (account.get("email") or "").strip()
    password = account.get("password") or ""
    if not host:
        return "error", "SMTP host пустой"

    tls_on = port != 25
    use_ssl = tls_on and port == 465
    try:
        smtp = aiosmtplib.SMTP(
            hostname=host,
            port=port,
            timeout=25,
            use_tls=use_ssl,
            start_tls=tls_on and not use_ssl,
            tls_context=ssl.create_default_context(),
        )
        await smtp.connect()
        if user:
            await smtp.login(user, password)
        await smtp.quit()
        return "active", None
    except Exception as exc:
        err = str(exc)
        if is_invalid_credentials_error(err):
            return "invalid", err
        if is_smtp_account_block_error(err):
            return "smtp_blocked", err
        return "error", err


async def check_one_account_full(
    account: dict,
    *,
    user_id: int,
    update_db: bool = True,
) -> dict[str, Any]:
    email = account.get("email") or ""
    aid = int(account.get("id") or 0)

    smtp_st, smtp_err = await _check_smtp_login(account)
    imap_r = await check_account_imap(account)

    if update_db and aid:
        if smtp_st == "invalid":
            await disable_account_fully(
                user_id, aid, short_block_reason(smtp_err) or "invalid credentials"
            )
        elif smtp_st == "smtp_blocked":
            await mark_account_smtp_blocked(
                user_id, aid, short_block_reason(smtp_err) or "smtp blocked"
            )

    imap_ok = bool(imap_r.get("ok"))
    smtp_icon = {
        "active": "🟢",
        "smtp_blocked": "🟡",
        "invalid": "🔴",
        "error": "⏭",
    }.get(smtp_st, "⏭")

    line = f"{smtp_icon} SMTP · {'✅' if imap_ok else '❌'} IMAP — <code>{email}</code>"
    details: list[str] = []
    if smtp_err:
        details.append(f"SMTP: <i>{short_block_reason(smtp_err)[:120]}</i>")
    if not imap_ok:
        details.append(f"IMAP: <i>{(imap_r.get('error') or '')[:120]}</i>")
    elif imap_r.get("pending_new"):
        details.append(f"IMAP: <b>{imap_r['pending_new']}</b> новых UID")

    return {
        "email": email,
        "account_id": aid,
        "smtp_status": smtp_st,
        "imap_ok": imap_ok,
        "line": line,
        "details": details,
        "imap": imap_r,
    }


async def check_accounts_status_parallel(
    user_id: int,
    accounts: list[dict],
    *,
    on_progress: Any | None = None,
    update_db: bool = True,
    concurrency: int = 4,
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    results: list[dict | None] = [None] * len(accounts)
    done = 0

    async def _one(idx: int, acc: dict) -> None:
        nonlocal done
        async with sem:
            results[idx] = await check_one_account_full(
                acc, user_id=user_id, update_db=update_db
            )
        done += 1
        if on_progress:
            await on_progress(done, len(accounts), acc.get("email"))

    await asyncio.gather(*[_one(i, a) for i, a in enumerate(accounts)])
    return [r for r in results if r]

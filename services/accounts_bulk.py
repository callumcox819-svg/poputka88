"""Массовое добавление аккаунтов с IMAP-проверкой (логика happy88)."""

from __future__ import annotations

import asyncio
import imaplib
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from database import set_user_sender_name, upsert_smtp_account
from services.mail_providers import detect_imap_server, imap_host_port, smtp_host_port
from utils.text_html import e

logger = logging.getLogger(__name__)


@dataclass
class _AccountLineWork:
    line: str
    email: str
    password: str


@dataclass
class _AccountCheckResult:
    work: _AccountLineWork | None
    fail_detail: str | None = None
    ok: bool = False
    provider: Optional[str] = None
    err: Optional[str] = None


def check_imap_credentials(email: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    try:
        host, provider = detect_imap_server(email)
    except ValueError as err:
        return False, None, str(err)

    try:
        with imaplib.IMAP4_SSL(host) as imap:
            imap.login(email, password)
            typ, _ = imap.select("INBOX")
            if typ != "OK":
                return False, provider, "IMAP select INBOX failed"
        return True, provider, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("IMAP login failed for %s: %s", email, exc)
        return False, provider, str(exc)


async def imap_check_async(email: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    return await asyncio.to_thread(check_imap_credentials, email, password)


async def _edit_add_progress(
    status_msg: Message,
    *,
    current: int,
    total: int,
    ok: int,
    fail: int,
    workers: int = 1,
    elapsed_sec: float | None = None,
) -> None:
    speed = ""
    if elapsed_sec and elapsed_sec > 0 and current > 0:
        per_min = current / elapsed_sec * 60.0
        speed = f"\n⚡ ~<b>{per_min:.1f}</b> акк./мин ({workers} потоков)"
    try:
        await status_msg.edit_text(
            "⏳ <b>Добавление аккаунтов</b>\n\n"
            f"Проверка IMAP: <b>{current}/{total}</b>\n"
            f"✅ успешно: <b>{ok}</b> · ❌ ошибки: <b>{fail}</b>"
            f"{speed}",
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass


def trim_details(details: List[str], limit: int = 35) -> str:
    if len(details) <= limit:
        return "\n".join(details)
    hidden = len(details) - limit
    return "\n".join(details[:limit]) + f"\n… и ещё {hidden} строк(и)"


async def bulk_add_accounts(
    message: Message,
    user_id: int,
    sender_name: str,
    lines: List[str],
) -> Tuple[int, int, List[str]]:
    total = len(lines)
    workers = max(1, min(8, int(os.getenv("ACCOUNTS_IMAP_CONCURRENCY", "4"))))
    status_msg = await message.answer(
        "⏳ <b>Добавление аккаунтов</b>\n\n"
        f"Проверка IMAP: <b>0/{total}</b>\n"
        f"Параллельно: <b>{workers}</b> потоков",
        parse_mode="HTML",
    )

    ok_count = 0
    fail_count = 0
    details: List[str] = []
    to_check: List[_AccountLineWork] = []

    for line in lines:
        if ":" not in line:
            fail_count += 1
            details.append(f"❌ <code>{e(line)}</code> — нет разделителя <code>:</code>")
            continue

        email, password = line.split(":", 1)
        email = email.strip().lower()
        password = password.strip()

        if not email or not password:
            fail_count += 1
            details.append(f"❌ <code>{e(line)}</code> — пустой email или пароль")
            continue

        to_check.append(_AccountLineWork(line=line, email=email, password=password))

    check_total = len(to_check)
    if not check_total:
        try:
            await status_msg.delete()
        except Exception:
            pass
        return ok_count, fail_count, details

    await set_user_sender_name(user_id, sender_name)

    sem = asyncio.Semaphore(workers)
    done_checks = 0
    t0 = asyncio.get_running_loop().time()

    async def _run_imap(work: _AccountLineWork) -> _AccountCheckResult:
        async with sem:
            ok, provider, err = await imap_check_async(work.email, work.password)
        return _AccountCheckResult(work=work, ok=ok, provider=provider, err=err)

    tasks = [asyncio.create_task(_run_imap(w)) for w in to_check]
    for fut in asyncio.as_completed(tasks):
        res = await fut
        done_checks += 1
        elapsed = asyncio.get_running_loop().time() - t0

        if not res.ok or not res.work:
            fail_count += 1
            err_txt = e(res.err or "ошибка IMAP")
            if (res.provider or "") == "gmx":
                err_txt += " · проверьте пароль и IMAP в GMX"
            email_show = res.work.email if res.work else "?"
            details.append(f"❌ <code>{e(email_show)}</code> — {err_txt}")
        else:
            work = res.work
            prov = res.provider or "gmail"
            smtp_host, smtp_port = smtp_host_port(work.email, prov)
            imap_host, imap_port = imap_host_port(work.email, prov)
            await upsert_smtp_account(
                user_id,
                sender_name=sender_name,
                email=work.email,
                password=work.password,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                imap_host=imap_host,
                imap_port=imap_port,
                provider=prov,
            )
            ok_count += 1
            details.append(f"✅ <code>{e(work.email)}</code> — {prov}")

        await _edit_add_progress(
            status_msg,
            current=done_checks,
            total=check_total,
            ok=ok_count,
            fail=fail_count,
            workers=workers,
            elapsed_sec=elapsed,
        )

    try:
        await status_msg.delete()
    except Exception:
        pass

    return ok_count, fail_count, details

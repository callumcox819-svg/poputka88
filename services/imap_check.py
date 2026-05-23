"""Диагностика IMAP: входящие, UID, сравнение с last_uid бота."""

from __future__ import annotations

import asyncio
import imaplib
import logging
import os
from typing import Any

from database import get_imap_last_uid

logger = logging.getLogger(__name__)
from services.imap_accounts import resolve_imap_account
from services.imap_fetch import imap_uid_search


def _imap_connect(host: str, port: int, email: str, password: str) -> imaplib.IMAP4:
    if int(port) == 993:
        conn = imaplib.IMAP4_SSL(host, int(port), timeout=45)
    else:
        conn = imaplib.IMAP4(host, int(port), timeout=45)
    conn.login(email, password)
    typ, _ = conn.select("INBOX")
    if typ != "OK":
        raise RuntimeError("IMAP select INBOX failed")
    return conn


def check_inbox_detailed_sync(
    *,
    account_id: int,
    email: str,
    password: str,
    imap_host: str,
    imap_port: int,
) -> dict[str, Any]:
    if not (imap_host or "").strip():
        return {
            "email": email,
            "ok": False,
            "error": "IMAP host не задан",
        }
    try:
        conn = _imap_connect(
            imap_host.strip(), int(imap_port or 993), email, password
        )
        uids = imap_uid_search(conn, "ALL")
        unseen_uids = imap_uid_search(conn, "UNSEEN")
        max_uid = max(uids) if uids else 0
        unseen = len(unseen_uids)

        conn.logout()

        return {
            "email": email,
            "account_id": account_id,
            "ok": True,
            "total": len(uids),
            "unseen": unseen,
            "max_uid": max_uid,
            "imap_host": imap_host,
        }
    except Exception as exc:
        return {
            "email": email,
            "account_id": account_id,
            "ok": False,
            "error": str(exc)[:220],
        }


async def check_account_imap(acc: dict) -> dict[str, Any]:
    """Полная проверка одного ящика + last_uid из БД."""
    aid = int(acc.get("id") or 0)
    resolved = resolve_imap_account(acc)
    if not resolved:
        return {
            "email": acc.get("email") or "?",
            "account_id": aid,
            "ok": False,
            "error": "нет email/пароля или IMAP host",
        }
    result = await asyncio.to_thread(
        check_inbox_detailed_sync,
        account_id=aid,
        email=resolved["email"],
        password=resolved.get("password") or "",
        imap_host=resolved.get("imap_host") or "",
        imap_port=int(resolved.get("imap_port") or 993),
    )
    if result.get("ok"):
        last_seen = await get_imap_last_uid(aid)
        max_uid = int(result.get("max_uid") or 0)
        unseen = int(result.get("unseen") or 0)
        result["last_seen_uid"] = last_seen
        if last_seen is None:
            result["pending_new"] = unseen
            result["baseline_note"] = (
                "первый опрос: в бот пойдут непрочитанные (UNSEEN)"
                if unseen
                else "нет непрочитанных в INBOX"
            )
        else:
            pending = max(0, max_uid - int(last_seen))
            result["pending_new"] = pending
            result["baseline_note"] = ""
    return result


async def check_accounts_imap(accounts: list[dict]) -> list[dict]:
    """Проверка ящиков с ограниченным параллелизмом (не бьём Postgres 25 conn сразу)."""
    if not accounts:
        return []
    limit = max(1, int(os.getenv("IMAP_CHECK_CONCURRENT", "3")))
    sem = asyncio.Semaphore(limit)

    async def _one(acc: dict) -> dict:
        async with sem:
            return await check_account_imap(acc)

    raw = await asyncio.gather(
        *[_one(acc) for acc in accounts],
        return_exceptions=True,
    )
    out: list[dict] = []
    for acc, item in zip(accounts, raw):
        if isinstance(item, Exception):
            logger.warning("imap_check %s: %s", acc.get("email"), item)
            out.append(
                {
                    "email": acc.get("email") or "?",
                    "account_id": int(acc.get("id") or 0),
                    "ok": False,
                    "error": str(item)[:220],
                }
            )
        else:
            out.append(item)
    return out


def format_imap_report(results: list[dict]) -> str:
    lines = ["📥 <b>Проверка IMAP (входящие)</b>\n"]
    ok_n = 0
    for r in results:
        em = r.get("email") or "?"
        if not r.get("ok"):
            lines.append(f"❌ <code>{em}</code>\n   {r.get('error', 'ошибка')}")
            continue
        ok_n += 1
        unseen = int(r.get("unseen") or 0)
        total = int(r.get("total") or 0)
        max_uid = int(r.get("max_uid") or 0)
        last = r.get("last_seen_uid")
        pending = int(r.get("pending_new") or 0)
        note = (r.get("baseline_note") or "").strip()

        extra = ""
        if last is None:
            extra = " · бот: baseline не задан"
        elif pending > 0:
            extra = f" · <b>{pending}</b> UID новее last_uid бота"
        else:
            extra = " · бот синхронизирован"

        if unseen > 0 and last is None:
            hint = " ⚠️ непрочитанные — бот заберёт при опросе /imap_check"
        elif unseen > 0 and pending > 0:
            hint = " ⚠️ есть непрочитанные — бот должен прислать в TG"
        elif unseen > 0 and last is not None and pending == 0:
            hint = " ℹ️ UNSEEN есть, но UID уже учтены (возможно прочитаны вручную)"
        else:
            hint = ""

        lines.append(
            f"✅ <code>{em}</code>\n"
            f"   непр. {unseen} · всего {total} · max UID {max_uid}{extra}{hint}"
        )
        if note:
            lines.append(f"   <i>{note}</i>")

    lines.append(f"\nПроверено: <b>{ok_n}/{len(results)}</b>")
    poll = int(float(os.getenv("INCOMING_POLL_SEC", "60") or 60))
    lines.append(
        f"\n<i>Авто-канал: imap-worker опрашивает ящики каждые ~{poll} с "
        f"(INCOMING_POLL_SEC). /imap_check — ручной догон, если авто не сработало.</i>"
    )
    return "\n".join(lines)

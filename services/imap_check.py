"""Диагностика IMAP: входящие, UID, сравнение с last_uid бота."""

from __future__ import annotations

import asyncio
import imaplib
from typing import Any

from database import get_imap_last_uid


def _imap_connect(host: str, port: int, email: str, password: str) -> imaplib.IMAP4:
    if int(port) == 993:
        conn = imaplib.IMAP4_SSL(host, int(port), timeout=45)
    else:
        conn = imaplib.IMAP4(host, int(port), timeout=45)
    conn.login(email, password)
    typ, _ = conn.select("INBOX", readonly=True)
    if typ != "OK":
        raise RuntimeError("IMAP select INBOX failed")
    return conn


def _uid_list(conn: imaplib.IMAP4) -> list[int]:
    typ, data = conn.uid("search", None, "ALL")
    if typ != "OK" or not data or not data[0]:
        return []
    return [int(x) for x in data[0].split() if str(x).isdigit()]


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
        uids = _uid_list(conn)
        max_uid = max(uids) if uids else 0

        typ, data = conn.search(None, "UNSEEN")
        unseen_legacy = (
            len(data[0].split()) if typ == "OK" and data and data[0] else 0
        )

        typ2, data2 = conn.uid("search", None, "UNSEEN")
        unseen_uid = 0
        if typ2 == "OK" and data2 and data2[0]:
            unseen_uid = len([x for x in data2[0].split() if x])

        conn.logout()

        return {
            "email": email,
            "account_id": account_id,
            "ok": True,
            "total": len(uids),
            "unseen": max(unseen_legacy, unseen_uid),
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
    result = await asyncio.to_thread(
        check_inbox_detailed_sync,
        account_id=aid,
        email=acc["email"],
        password=acc.get("password") or "",
        imap_host=acc.get("imap_host") or "",
        imap_port=int(acc.get("imap_port") or 993),
    )
    if result.get("ok"):
        last_seen = await get_imap_last_uid(aid)
        max_uid = int(result.get("max_uid") or 0)
        result["last_seen_uid"] = last_seen
        if last_seen is None:
            result["pending_new"] = 0
            result["baseline_note"] = "бот ещё не опрашивал (первый цикл без старых писем)"
        else:
            pending = max(0, max_uid - int(last_seen))
            result["pending_new"] = pending
            result["baseline_note"] = ""
    return result


async def check_accounts_imap(accounts: list[dict]) -> list[dict]:
    if not accounts:
        return []
    tasks = [check_account_imap(acc) for acc in accounts]
    return list(await asyncio.gather(*tasks))


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

        if unseen > 0 and pending > 0:
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
    lines.append(
        "\n<i>Фоновый опрос каждые ~25 с. Если pending&gt;0 и в TG пусто — /stopcheck не нужен, смотрите логи Railway.</i>"
    )
    return "\n".join(lines)

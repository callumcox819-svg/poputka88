"""Проверка входящих по IMAP для сохранённых аккаунтов."""

from __future__ import annotations

import asyncio
import imaplib
from typing import Any


def _check_inbox_sync(
    *,
    email: str,
    password: str,
    imap_host: str,
    imap_port: int,
) -> dict[str, Any]:
    if not imap_host:
        return {"email": email, "ok": False, "error": "IMAP host не задан"}
    try:
        if imap_port == 993:
            conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
        else:
            conn = imaplib.IMAP4(imap_host, imap_port, timeout=30)
        conn.login(email, password)
        conn.select("INBOX", readonly=True)
        _status, data = conn.search(None, "UNSEEN")
        unseen = len(data[0].split()) if data and data[0] else 0
        _status, data = conn.search(None, "ALL")
        total = len(data[0].split()) if data and data[0] else 0
        conn.logout()
        return {
            "email": email,
            "ok": True,
            "unseen": unseen,
            "total": total,
        }
    except Exception as exc:
        return {"email": email, "ok": False, "error": str(exc)[:200]}


async def check_accounts(accounts: list[dict]) -> list[dict]:
    tasks = [
        asyncio.to_thread(
            _check_inbox_sync,
            email=acc["email"],
            password=acc["password"],
            imap_host=acc.get("imap_host") or "",
            imap_port=int(acc.get("imap_port") or 993),
        )
        for acc in accounts
    ]
    return list(await asyncio.gather(*tasks))

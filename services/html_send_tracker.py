"""Недавние HTML-отправки — чтобы DSN «Message blocked» не спамил plain-рассылкой."""

from __future__ import annotations

import time

from services.user_json_store import load_json_blob, save_json_blob

_BLOB = "recent_html_sends"
_MAX_ENTRIES = 400
_TTL_SEC = 7 * 24 * 3600
_MATCH_WINDOW_SEC = 5 * 24 * 3600


def _canon_email(addr: str) -> str:
    return (addr or "").strip().lower()


def _now() -> float:
    return time.time()


async def record_html_send(
    user_id: int,
    *,
    from_account: str,
    to_addr: str,
) -> None:
    """Вызывать после успешной отправки письма с is_html=True."""
    frm = _canon_email(from_account)
    to = _canon_email(to_addr)
    if not frm or not to or "@" not in to:
        return

    rows = await load_json_blob(int(user_id), _BLOB, default=[])
    if not isinstance(rows, list):
        rows = []

    cutoff = _now() - _TTL_SEC
    fresh: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            if float(item.get("ts") or 0) >= cutoff:
                fresh.append(item)
        except (TypeError, ValueError):
            continue

    fresh.append({"from": frm, "to": to, "ts": _now()})
    if len(fresh) > _MAX_ENTRIES:
        fresh = fresh[-_MAX_ENTRIES :]

    await save_json_blob(int(user_id), _BLOB, fresh)


async def was_recent_html_send(
    user_id: int,
    *,
    from_account: str,
    to_addr: str,
    within_sec: int = _MATCH_WINDOW_SEC,
) -> bool:
    """Был ли HTML на этот адрес с этого ящика за последние N секунд."""
    frm = _canon_email(from_account)
    to = _canon_email(to_addr)
    if not frm or not to:
        return False

    rows = await load_json_blob(int(user_id), _BLOB, default=[])
    if not isinstance(rows, list):
        return False

    since = _now() - max(3600, int(within_sec))
    for item in reversed(rows):
        if not isinstance(item, dict):
            continue
        try:
            ts = float(item.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts < since:
            break
        if item.get("from") == frm and item.get("to") == to:
            return True
    return False

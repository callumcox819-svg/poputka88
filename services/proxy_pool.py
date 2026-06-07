"""Пул SOCKS5: все живые прокси по очереди, без привязок к аккаунтам."""

from __future__ import annotations

import logging

from database import list_sendable_proxies, update_proxy_status

logger = logging.getLogger(__name__)

_rr_index: dict[int, int] = {}

# Только эти типы / тексты = реально мёртвый SOCKS (не обрыв Gmail и не 535 auth).
_SOCKS_EXC_NAMES = frozenset(
    {
        "GeneralProxyError",
        "ProxyError",
        "SOCKS5Error",
        "SOCKS4Error",
        "ProxyConnectionError",
    }
)

_SOCKS_MSG_HINTS = (
    "generalproxyerror",
    "sockshttperror",
    "pysocks",
    "proxy connection",
    "can't connect to proxy",
    "cannot connect to proxy",
    "0x05:",
    "0x05 ",
)


def reset_round_robin(user_id: int) -> None:
    _rr_index.pop(int(user_id), None)


def proxy_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "host": row["host"],
        "port": int(row["port"]),
        "username": row.get("username"),
        "password": row.get("password"),
        "type": row.get("proxy_type") or "socks5",
    }


def pick_next_proxy_from_rows(user_id: int, rows: list[dict]) -> dict | None:
    """Round-robin по уже загруженному списку (без запроса в БД)."""
    if not rows:
        return None
    uid = int(user_id)
    idx = _rr_index.get(uid, 0) % len(rows)
    _rr_index[uid] = idx + 1
    return proxy_to_dict(rows[idx])


async def pick_next_proxy(user_id: int) -> dict | None:
    rows = await list_sendable_proxies(user_id)
    return pick_next_proxy_from_rows(user_id, rows)


def is_socks_proxy_failure(exc: BaseException) -> bool:
    """
    Прокси 🔴 только при явном сбое SOCKS5.
    Таймаут SMTP, «connection closed», 535 auth — не считаем смертью прокси.
    """
    if type(exc).__name__ in _SOCKS_EXC_NAMES:
        return True
    if "socks" in (type(exc).__module__ or "").lower():
        return True
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(h in msg for h in _SOCKS_MSG_HINTS)


async def mark_proxy_dead(user_id: int, proxy_id: int, error: str) -> None:
    err = (error or "SOCKS5 error")[:500]
    await update_proxy_status(proxy_id, user_id, is_active=0, last_error=err)
    logger.warning("proxy dead user_id=%s proxy_id=%s: %s", user_id, proxy_id, err[:160])

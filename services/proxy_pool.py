"""Пул SOCKS5: все живые прокси по очереди, без привязок к аккаунтам."""

from __future__ import annotations

from database import list_sendable_proxies, update_proxy_status

_rr_index: dict[int, int] = {}

_PROXY_ERR_MARKERS = (
    "socks",
    "proxy",
    "timeout",
    "timed out",
    "connect",
    "connection",
    "refused",
    "unreachable",
    "network",
    "tunnel",
    "generalproxyerror",
    "socket",
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


async def pick_next_proxy(user_id: int) -> dict | None:
    rows = await list_sendable_proxies(user_id)
    if not rows:
        return None
    uid = int(user_id)
    idx = _rr_index.get(uid, 0) % len(rows)
    _rr_index[uid] = idx + 1
    return proxy_to_dict(rows[idx])


def is_proxy_tunnel_error(exc: BaseException) -> bool:
    err_l = str(exc).lower()
    return any(m in err_l for m in _PROXY_ERR_MARKERS)


async def mark_proxy_mailing_dead(
    user_id: int, proxy_id: int, error: str
) -> None:
    await update_proxy_status(
        proxy_id,
        user_id,
        is_active=0,
        last_error=(error or "SMTP via proxy failed")[:500],
    )

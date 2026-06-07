"""Пул SOCKS5: все живые прокси по очереди, без привязок к аккаунтам."""

from __future__ import annotations

import logging

from database import list_sendable_proxies, update_proxy_status

logger = logging.getLogger(__name__)

_rr_index: dict[int, int] = {}
_mailing_excluded: dict[int, set[int]] = {}
_mailing_fail_streak: dict[tuple[int, int], int] = {}
_MAILING_HARD_DEAD_STREAK = 3

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


def clear_mailing_session(user_id: int) -> None:
    uid = int(user_id)
    _mailing_excluded.pop(uid, None)
    dead_keys = [k for k in _mailing_fail_streak if k[0] == uid]
    for k in dead_keys:
        _mailing_fail_streak.pop(k, None)


def get_mailing_excluded_proxy_ids(user_id: int) -> set[int]:
    return set(_mailing_excluded.get(int(user_id), set()))


def exclude_proxy_for_mailing_session(user_id: int, proxy_id: int) -> None:
    _mailing_excluded.setdefault(int(user_id), set()).add(int(proxy_id))


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


def proxy_for_batch_slot(user_id: int, rows: list[dict], slot: int) -> dict | None:
    """Прокси для параллельной пачки: slot 0..N-1 без гонки round-robin."""
    if not rows:
        return None
    uid = int(user_id)
    base = _rr_index.get(uid, 0)
    idx = (base + int(slot)) % len(rows)
    return proxy_to_dict(rows[idx])


def advance_proxy_round_robin(user_id: int, n: int) -> None:
    if n > 0:
        _rr_index[int(user_id)] = _rr_index.get(int(user_id), 0) + int(n)


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
    exclude_proxy_for_mailing_session(user_id, proxy_id)
    _mailing_fail_streak.pop((int(user_id), int(proxy_id)), None)
    logger.warning("proxy dead user_id=%s proxy_id=%s: %s", user_id, proxy_id, err[:160])


async def note_proxy_soft_fail(user_id: int, proxy_id: int, error: str) -> None:
    """Таймаут SMTP — не 🔴, только last_error; другой прокси на следующей попытке."""
    err = (error or "SMTP timeout")[:500]
    await update_proxy_status(proxy_id, user_id, is_active=None, last_error=err)


async def note_mailing_proxy_failure(
    user_id: int, proxy_id: int, error: str, *, hard_dead: bool
) -> None:
    uid, pid = int(user_id), int(proxy_id)
    err = (error or "proxy failure")[:500]
    if hard_dead:
        key = (uid, pid)
        streak = _mailing_fail_streak.get(key, 0) + 1
        _mailing_fail_streak[key] = streak
        if streak >= _MAILING_HARD_DEAD_STREAK:
            await mark_proxy_dead(uid, pid, err)
            return
        await note_proxy_soft_fail(uid, pid, err)
        logger.warning(
            "mailing proxy hard err user_id=%s proxy_id=%s streak=%s: %s",
            uid,
            pid,
            streak,
            err[:120],
        )
        return
    _mailing_fail_streak.pop((uid, pid), None)
    await note_proxy_soft_fail(uid, pid, err)
    logger.info(
        "mailing proxy soft fail user_id=%s proxy_id=%s: %s",
        uid,
        pid,
        err[:120],
    )


def build_mailing_proxy_try_order(
    user_id: int,
    rows: list[dict],
    *,
    fixed_proxy: dict | None = None,
    max_tries: int,
) -> list[dict]:
    """Все живые по очереди: сначала назначенный слот, потом остальные (без 🔴 сессии)."""
    excluded = get_mailing_excluded_proxy_ids(user_id)
    ordered: list[dict] = []
    seen: set[int] = set()

    if fixed_proxy:
        pid = int(fixed_proxy.get("id") or 0)
        if pid and pid not in excluded:
            ordered.append(fixed_proxy)
            seen.add(pid)

    for row in rows:
        pid = int(row.get("id") or 0)
        if not pid or pid in seen or pid in excluded:
            continue
        ordered.append(proxy_to_dict(row))
        seen.add(pid)

    limit = max(1, min(max_tries, len(ordered) or 1))
    return ordered[:limit]

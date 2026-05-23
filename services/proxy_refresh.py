"""Массовая проверка прокси пользователя."""

from __future__ import annotations

import asyncio

from database import list_proxies, update_proxy_status
from services.proxy_verify import apply_check_status, test_proxy_socks


async def refresh_user_proxies(
    user_id: int,
    *,
    concurrency: int = 3,
    timeout: int = 20,
) -> tuple[int, int, int]:
    proxies = await list_proxies(user_id)
    if not proxies:
        return 0, 0, 0

    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[tuple[int, bool, str]] = []

    async def _one(p: dict) -> None:
        async with sem:
            pdata = {
                "host": p["host"],
                "port": p["port"],
                "username": p.get("username"),
                "password": p.get("password"),
                "type": p.get("proxy_type") or "socks5",
            }
            try:
                ok, info = await asyncio.wait_for(
                    test_proxy_socks(pdata, timeout=timeout),
                    timeout=timeout + 10,
                )
            except asyncio.TimeoutError:
                ok, info = False, "Timeout"
            except Exception as e:
                ok, info = False, f"{type(e).__name__}: {e}"
        results.append((int(p["id"]), ok, info))

    await asyncio.gather(*[_one(p) for p in proxies])

    ok_n = fail_n = 0
    for pid, ok, info in results:
        active, err = apply_check_status(None, ok, info)
        await update_proxy_status(pid, user_id, is_active=active, last_error=err)
        if ok:
            ok_n += 1
        else:
            fail_n += 1

    return ok_n, fail_n, len(proxies)

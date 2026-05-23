"""Проверка SOCKS5 прокси."""

from __future__ import annotations

import asyncio
import os
from typing import Any

PROXY_CHECK_RETRIES = max(1, min(4, int(os.getenv("PROXY_CHECK_RETRIES", "2"))))
PROXY_CHECK_RETRY_PAUSE_SEC = max(
    0.5, min(5.0, float(os.getenv("PROXY_CHECK_RETRY_PAUSE_SEC", "2")))
)
SMTP_TEST_HOST = (os.getenv("SMTP_TEST_HOST") or "smtp.gmail.com").strip()
SMTP_TEST_PORT = int(os.getenv("SMTP_TEST_PORT") or "587")


def _test_socks5_connect_sync(proxy: dict[str, Any], *, timeout: int = 12) -> tuple[bool, str]:
    import socks

    host = (proxy.get("host") or "").strip()
    port = int(proxy.get("port") or 0)
    if not host or not port:
        return False, "host/port пустые"
    username = (proxy.get("username") or "").strip() or None
    password = (proxy.get("password") or "").strip() or None
    s = socks.socksocket()
    try:
        s.set_proxy(
            socks.SOCKS5,
            host,
            port,
            username=username,
            password=password,
            rdns=True,
        )
        s.settimeout(float(timeout))
        s.connect((SMTP_TEST_HOST, SMTP_TEST_PORT))
        return True, f"SOCKS5 OK -> {SMTP_TEST_HOST}:{SMTP_TEST_PORT}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            s.close()
        except Exception:
            pass


async def test_proxy_socks(proxy: dict[str, Any], *, timeout: int = 18) -> tuple[bool, str]:
    attempts = PROXY_CHECK_RETRIES
    last = ""
    for i in range(attempts):
        ok, info = await asyncio.to_thread(
            _test_socks5_connect_sync, proxy, timeout=timeout
        )
        if ok:
            return True, info
        last = info
        if i + 1 < attempts:
            await asyncio.sleep(PROXY_CHECK_RETRY_PAUSE_SEC)
    return False, last


def apply_check_status(is_active_col: int | None, ok: bool, info: str) -> tuple[int | None, str | None]:
    """1 = ok, NULL = unknown/fail check (still usable), 0 = dead at mailing only."""
    if ok:
        return 1, None
    return None, (info or "")[:500]

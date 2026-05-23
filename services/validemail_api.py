"""Клиент ValidEmail.co API v1."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://validemail.co/api/v1/validate"
_CACHE: dict[str, tuple[bool, str, float]] = {}
_CACHE_TTL = 60 * 60 * 6

_session: aiohttp.ClientSession | None = None


async def _session_get() -> aiohttp.ClientSession:
    global _session
    if _session and not _session.closed:
        return _session
    timeout = aiohttp.ClientTimeout(total=20, connect=6, sock_read=15)
    _session = aiohttp.ClientSession(
        timeout=timeout,
        connector=aiohttp.TCPConnector(limit=300),
    )
    return _session


async def close_validemail_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


def is_validemail_deliverable(data: dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    status = str(data.get("status") or "").lower().strip()
    if status == "deliverable":
        return True
    if data.get("isDeliverable") is True:
        return True
    if data.get("is_deliverable") is True:
        return True
    return False


def validation_reason(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return "invalid_response"
    return str(data.get("reason") or data.get("status") or "unknown")


async def validate_email_api(
    email: str,
    *,
    api_key: str,
    url: str = DEFAULT_URL,
    timeout_sec: int = 8,
) -> tuple[bool, str, dict[str, Any]]:
    email_lc = (email or "").strip().lower()
    if not email_lc or "@" not in email_lc:
        return False, "invalid_format", {}

    api_key = (api_key or "").strip()
    if not api_key:
        return False, "no_api_key", {}

    cache_key = f"{url}::{email_lc}"
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached[2] < _CACHE_TTL:
        ok, reason, _ = cached
        return ok, reason, {}

    params = {"email": email_lc, "timeout": max(2, min(30, int(timeout_sec)))}
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        session = await _session_get()
        async with session.get(url, params=params, headers=headers) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {"raw": str(data)}

            if resp.status == 402:
                return False, "payment_required", data
            if resp.status == 429:
                return False, "rate_limit", data
            if resp.status != 200:
                reason = validation_reason(data) or f"http_{resp.status}"
                _CACHE[cache_key] = (False, reason, time.time())
                return False, reason, data

            ok = is_validemail_deliverable(data)
            reason = "deliverable" if ok else validation_reason(data)
            _CACHE[cache_key] = (ok, reason, time.time())
            return ok, reason, data
    except asyncio.TimeoutError:
        return False, "timeout", {}
    except Exception as exc:
        logger.debug("validemail %s: %s", email_lc, exc)
        return False, str(exc)[:120], {}

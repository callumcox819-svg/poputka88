"""Пул ValidEmail: несколько API-ключей параллельно."""

from __future__ import annotations

import asyncio
from typing import Any

from services.validemail_api import validate_email_api


class ValidemailKeyPool:
    """
    Несколько ключей — у каждого свой лимит параллельных запросов.
    Запросы распределяются по ключам round-robin.
    """

    def __init__(
        self,
        api_keys: list[str],
        *,
        url: str,
        timeout_sec: int,
        concurrency_per_key: int,
    ) -> None:
        keys = [k.strip() for k in api_keys if (k or "").strip()]
        if not keys:
            raise ValueError("no validemail api keys")
        self._keys = keys
        self._url = url
        self._timeout = timeout_sec
        self._sems = [
            asyncio.Semaphore(max(1, concurrency_per_key)) for _ in keys
        ]
        self._rr = 0
        self._pick_lock = asyncio.Lock()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    async def _pick_index(self) -> int:
        async with self._pick_lock:
            idx = self._rr % len(self._keys)
            self._rr += 1
            return idx

    async def validate(self, email: str) -> tuple[bool, str, dict[str, Any]]:
        idx = await self._pick_index()
        async with self._sems[idx]:
            return await validate_email_api(
                email,
                api_key=self._keys[idx],
                url=self._url,
                timeout_sec=self._timeout,
            )


async def find_deliverable_email(
    pool: ValidemailKeyPool,
    local: str,
    domains: list[str],
) -> tuple[str | None, str | None, str | None]:
    """
    Проверяет local@domain для всех доменов параллельно.
    Возвращает (email, domain, fatal_reason) — fatal_reason при payment/rate_limit.
    """
    if not local or not domains:
        return None, None, None

    async def _one(domain: str) -> tuple[str, bool, str]:
        email = f"{local}@{domain}".lower()
        ok, reason, _ = await pool.validate(email)
        return email, ok, reason

    tasks = [asyncio.create_task(_one(d)) for d in domains]
    fatal: str | None = None
    try:
        for done in asyncio.as_completed(tasks):
            email, ok, reason = await done
            if reason in ("payment_required", "rate_limit"):
                fatal = reason
                break
            if ok:
                domain = email.split("@", 1)[1]
                return email, domain, None
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    return None, None, fatal

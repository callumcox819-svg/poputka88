"""Пул ValidEmail: несколько API-ключей, домены по приоритету (как happy88)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from services.validemail_api import validate_email_api

logger = logging.getLogger(__name__)

RATE_LIMIT_BACKOFF_SEC = float(os.getenv("VALIDEMAIL_RATE_LIMIT_BACKOFF_SEC", "10"))
RATE_LIMIT_RETRIES = max(1, int(os.getenv("VALIDEMAIL_RATE_LIMIT_RETRIES", "4")))


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
    Домены по приоритету; на продавца — первая валидная почта, дальше не проверяем.

    Возвращает (email, domain, fatal_reason).
    fatal_reason только при payment_required (кончились деньги на ключе).
    rate_limit — пауза и повтор, без остановки всего подбора (как happy88).
    """
    if not local or not domains:
        return None, None, None

    for dom in domains:
        dom = (dom or "").strip().lower()
        if not dom:
            continue
        email = f"{local}@{dom}".lower()

        for attempt in range(RATE_LIMIT_RETRIES):
            ok, reason, _ = await pool.validate(email)
            if ok:
                return email, dom, None
            if reason == "payment_required":
                return None, None, "payment_required"
            if reason == "rate_limit":
                wait = RATE_LIMIT_BACKOFF_SEC * (attempt + 1)
                logger.warning(
                    "ValidEmail rate_limit %s, retry %s/%s in %ss",
                    email,
                    attempt + 1,
                    RATE_LIMIT_RETRIES,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            # невалидный ящик на этом домене — следующий домен
            break

    return None, None, None

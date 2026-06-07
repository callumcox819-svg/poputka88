"""Проверка SOCKS5 перед рассылкой и периодически во время /send."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from database import count_proxies, list_proxies
from services.proxy_pool import clear_mailing_session, reset_round_robin
from services.proxy_refresh import refresh_user_proxies

logger = logging.getLogger(__name__)

MAIL_PROXY_RECHECK_SEC = max(60, min(600, int(os.getenv("MAIL_PROXY_RECHECK_SEC", "120"))))
MAIL_PROXY_PREFLIGHT_TIMEOUT = max(12, min(45, int(os.getenv("MAIL_PROXY_PREFLIGHT_TIMEOUT", "22"))))
MAIL_PROXY_PREFLIGHT_CONCURRENCY = max(
    1, min(6, int(os.getenv("MAIL_PROXY_PREFLIGHT_CONCURRENCY", "4")))
)


@dataclass(frozen=True)
class ProxyHealthSummary:
    total: int
    ok: int
    unknown: int
    bad: int

    def format_lines(self) -> str:
        return (
            f"SOCKS5: <b>{self.total}</b> · 🟢 OK: <b>{self.ok}</b> · "
            f"🟡 неясно: <b>{self.unknown}</b> · 🔴 мёртв: <b>{self.bad}</b>"
        )


async def summarize_proxy_health(user_id: int) -> ProxyHealthSummary:
    rows = await list_proxies(user_id)
    ok = unk = bad = 0
    for p in rows:
        active = p.get("is_active")
        if active == 1:
            ok += 1
        elif active == 0:
            bad += 1
        else:
            unk += 1
    return ProxyHealthSummary(len(rows), ok, unk, bad)


def mailing_may_start(summary: ProxyHealthSummary) -> tuple[bool, str]:
    if summary.total <= 0:
        return False, "Нет SOCKS5 в «🌐 Прокси»."
    if summary.ok >= 1:
        return True, summary.format_lines()
    if summary.unknown >= 1:
        return (
            True,
            summary.format_lines()
            + "\n<i>Чёткого OK нет (таймаут при проверке) — рассылка стартует по 🟢/🟡.</i>",
        )
    return (
        False,
        summary.format_lines()
        + "\n\n❌ Все прокси 🔴. Откройте «🌐 Прокси» → 🔍 Проверить или добавьте новые.",
    )


async def run_proxy_health_check(user_id: int) -> ProxyHealthSummary:
    """Перед /send и периодически: SOCKS5 → smtp.gmail.com:587."""
    await refresh_user_proxies(
        user_id,
        concurrency=MAIL_PROXY_PREFLIGHT_CONCURRENCY,
        timeout=MAIL_PROXY_PREFLIGHT_TIMEOUT,
    )
    reset_round_robin(user_id)
    return await summarize_proxy_health(user_id)


async def preflight_proxies_for_mailing(user_id: int) -> tuple[bool, ProxyHealthSummary, str]:
    total = await count_proxies(user_id)
    if total <= 0:
        summary = ProxyHealthSummary(0, 0, 0, 0)
        return False, summary, "Нет SOCKS5 в «🌐 Прокси»."
    clear_mailing_session(user_id)
    summary = await run_proxy_health_check(user_id)
    ok, detail = mailing_may_start(summary)
    return ok, summary, detail

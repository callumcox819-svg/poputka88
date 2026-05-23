"""Проверка формата email и наличия MX у домена."""

from __future__ import annotations

import asyncio
import re

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _check_mx_sync(domain: str) -> bool:
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except Exception:
        return False


async def validate_one(email: str) -> tuple[bool, str]:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return False, "неверный формат"
    domain = email.split("@", 1)[1]
    ok = await asyncio.to_thread(_check_mx_sync, domain)
    if ok:
        return True, "ok"
    return False, "нет MX записи"

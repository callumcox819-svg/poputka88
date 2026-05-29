"""Классификация ошибок исходящей почты (SMTP + SOCKS)."""

from __future__ import annotations

import re

_TRANSIENT = (
    r"connection unexpectedly closed",
    r"timed out",
    r"timeout",
    r"temporarily unavailable",
    r"connection reset",
    r"broken pipe",
    r"unexpected_eof",
    r"eof occurred",
    r"smtpserverdisconnected",
    r"smtpconnecterror",
)


def is_transient_smtp_send_failure(exc: BaseException | None) -> bool:
    """Обрыв/таймаут — прокси не обязательно мёртв; другой прокси или повтор могут помочь."""
    if exc is None:
        return False
    t = f"{type(exc).__name__}: {exc}".lower()
    return any(re.search(p, t) for p in _TRANSIENT)


def format_send_error_for_user(exc: BaseException | None, *, is_html: bool = False) -> str:
    raw = str(exc).strip() if exc else "Ошибка отправки"
    if not raw and exc is not None:
        raw = type(exc).__name__
    if not raw:
        raw = "Ошибка отправки"

    low = raw.lower()
    if "webloginrequired" in low or "log in with your web browser" in low:
        return (
            "Gmail: нужен вход через браузер (ящик не пускает SMTP). "
            "Откройте этот ящик в браузере через тот же прокси/IP, "
            "подтвердите вход, затем повторите отправку."
        )

    if is_transient_smtp_send_failure(exc):
        kind = "HTML" if is_html else "письмо"
        return (
            f"Таймаут SMTP через прокси ({raw[:120]}). "
            f"Не удалось отправить {kind}: Gmail/прокси оборвали соединение. "
            "Часто при активной рассылке или медленном SOCKS5 — "
            "подождите, смените прокси или 🌐 Прокси → 🔍 Проверить."
        )

    if len(raw) > 400:
        return raw[:400]
    return raw

"""Подготовка SMTP-аккаунтов для IMAP-опроса (host из БД или по домену)."""

from __future__ import annotations

from typing import Any

from services.mail_providers import imap_host_port


def resolve_imap_account(acc: dict[str, Any]) -> dict[str, Any] | None:
    """
    Аккаунт готов к IMAP, если есть email, password и imap host.
    imap_host пустой в БД — подставляем по домену (как при добавлении ящика).
    """
    email = (acc.get("email") or "").strip()
    password = (acc.get("password") or "").strip()
    if not email or not password:
        return None

    host = (acc.get("imap_host") or "").strip()
    port = int(acc.get("imap_port") or 993)
    if not host:
        host, port = imap_host_port(email, (acc.get("provider") or "").strip())

    if not host:
        return None

    out = dict(acc)
    out["imap_host"] = host
    out["imap_port"] = port
    return out

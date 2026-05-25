"""SMTP через SOCKS5 (для рассылки, ответов, HTML)."""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import socket as stdlib_socket
from contextlib import asynccontextmanager
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)

_smtp_socket_orig = smtplib.socket
_getaddrinfo_orig: Any = None
_lock = asyncio.Lock()


def _apply_socks(proxy: dict[str, Any]) -> None:
    global _getaddrinfo_orig
    import socks

    host = (proxy.get("host") or "").strip()
    port = int(proxy.get("port") or 0)
    user = (proxy.get("username") or "").strip() or None
    pwd = (proxy.get("password") or "").strip() or None
    socks.set_default_proxy(socks.SOCKS5, host, port, username=user, password=pwd, rdns=True)
    if _getaddrinfo_orig is None:
        _getaddrinfo_orig = stdlib_socket.getaddrinfo

    def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return _getaddrinfo_orig(
            host, port, stdlib_socket.AF_INET, type or stdlib_socket.SOCK_STREAM, proto, flags
        )

    stdlib_socket.getaddrinfo = _ipv4
    socks.wrapmodule(smtplib)
    if hasattr(smtplib.socket, "getaddrinfo"):
        smtplib.socket.getaddrinfo = _ipv4


def _reset_socks() -> None:
    global _getaddrinfo_orig
    try:
        import socks

        socks.set_default_proxy()
    except Exception:
        pass
    if _getaddrinfo_orig is not None:
        stdlib_socket.getaddrinfo = _getaddrinfo_orig
    smtplib.socket = _smtp_socket_orig


@asynccontextmanager
async def proxy_smtp_context(proxy: dict[str, Any]):
    async with _lock:
        _apply_socks(proxy)
        try:
            yield
        finally:
            _reset_socks()


def send_message_sync(
    *,
    smtp_host: str,
    smtp_port: int,
    login: str,
    password: str,
    mail_from: str,
    to_addr: str,
    message: EmailMessage,
    timeout: int = 35,
) -> None:
    use_ssl = smtp_port == 465
    if use_ssl:
        srv = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout)
    else:
        srv = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)
    try:
        srv.ehlo()
        if not use_ssl:
            srv.starttls()
            srv.ehlo()
        if login and password:
            srv.login(login, password)
        srv.send_message(message)
    finally:
        try:
            srv.quit()
        except Exception:
            pass


async def send_via_proxy(
    proxy: dict[str, Any],
    *,
    smtp_host: str,
    smtp_port: int,
    login: str,
    password: str,
    mail_from: str,
    to_addr: str,
    message: EmailMessage,
) -> None:
    timeout = max(20, min(60, int(os.getenv("MAIL_SMTP_TIMEOUT_SEC", "35"))))

    async def _run() -> None:
        async with proxy_smtp_context(proxy):
            await asyncio.to_thread(
                send_message_sync,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                login=login,
                password=password,
                mail_from=mail_from,
                to_addr=to_addr,
                message=message,
                timeout=timeout,
            )

    await asyncio.wait_for(_run(), timeout=timeout + 15)

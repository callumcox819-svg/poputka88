"""
Единая исходящая почта: рассылка, ответы, HTML.

Если у пользователя есть прокси в настройках — отправка только через SOCKS5,
по очереди из всех живых (без привязок к аккаунтам).
"""

from __future__ import annotations

from typing import Any

from config import Settings
from database import count_proxies, list_sendable_proxies
from services.encoding import TransferEncoding
from services.proxy_pool import (
    is_proxy_tunnel_error,
    mark_proxy_mailing_dead,
    pick_next_proxy,
)
from services.html_spoof import prepare_html_outbound
from services.smtp_sender import EncodingName, send_one


class NoLiveProxyError(RuntimeError):
    """Нет прокси в настройках или нет ни одного живого SOCKS5 для отправки."""


async def live_proxy_count(user_id: int) -> int:
    return len(await list_sendable_proxies(user_id))


async def user_has_proxies(user_id: int) -> bool:
    return (await count_proxies(user_id)) > 0


async def send_mail(
    settings: Settings,
    user_id: int,
    *,
    to_addr: str,
    subject: str,
    body: str,
    is_html: bool = False,
    transfer: TransferEncoding = TransferEncoding.AUTO,
    reply_to: str | None = None,
    account: dict[str, Any] | None = None,
    use_tls: bool | None = None,
) -> EncodingName:
    """
    Отправить письмо. Всегда только через SOCKS5-прокси из настроек пользователя.
    """
    uid = int(user_id)
    subject, body, from_display_name = await prepare_html_outbound(
        uid, subject=subject, body=body, is_html=is_html
    )

    if not await user_has_proxies(uid):
        raise NoLiveProxyError(
            "Добавьте SOCKS5-прокси в 🌐 Прокси. "
            "Рассылка, ответы (пресеты/ручные) и HTML — только через прокси."
        )

    sendable = await list_sendable_proxies(uid)
    if not sendable:
        raise NoLiveProxyError(
            "В настройках есть прокси, но нет живых. "
            "Добавьте SOCKS5 или нажмите «Проверить прокси»."
        )

    last_exc: Exception | None = None
    attempts = len(sendable)

    for _ in range(attempts):
        proxy = await pick_next_proxy(uid)
        if not proxy:
            break
        try:
            return await send_one(
                settings,
                to_addr=to_addr,
                subject=subject,
                body=body,
                is_html=is_html,
                transfer=transfer,
                reply_to=reply_to,
                account=account,
                from_display_name=from_display_name,
                use_tls=use_tls,
                proxy=proxy,
            )
        except Exception as exc:
            last_exc = exc
            if proxy.get("id") and is_proxy_tunnel_error(exc):
                await mark_proxy_mailing_dead(uid, int(proxy["id"]), str(exc))
            continue

    if last_exc is not None:
        raise last_exc
    raise NoLiveProxyError("Не удалось отправить через прокси.")

"""
Единая исходящая почта: рассылка, ответы, HTML.

Если у пользователя есть прокси в настройках — отправка только через SOCKS5,
по очереди из всех живых (без привязок к аккаунтам).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from config import Settings
from database import count_proxies, list_sendable_proxies
from services.encoding import TransferEncoding
from services.proxy_pool import (
    build_mailing_proxy_try_order,
    is_socks_proxy_failure,
    mark_proxy_dead,
    note_mailing_proxy_failure,
    pick_next_proxy,
    pick_next_proxy_from_rows,
)
from services.email_thread import spoof_subject_for_thread_reply
from services.html_send_tracker import record_html_send
from services.html_spoof import prepare_html_outbound
from services.smtp_errors import is_transient_smtp_send_failure
from services.smtp_sender import EncodingName, send_one

logger = logging.getLogger(__name__)


class NoLiveProxyError(RuntimeError):
    """Нет прокси в настройках или нет ни одного живого SOCKS5 для отправки."""


def _mailing_smtp_timeout() -> int:
    raw = (os.getenv("MAILING_SMTP_TIMEOUT_SEC") or "25").strip()
    try:
        return max(15, min(45, int(raw)))
    except ValueError:
        return 25


def _mailing_max_proxy_tries(proxy_count: int) -> int:
    raw = (os.getenv("MAILING_MAX_PROXY_TRIES") or "10").strip()
    try:
        cap = max(1, min(5, int(raw)))
    except ValueError:
        cap = 2
    return max(1, min(cap, proxy_count or 1))


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
    in_reply_to: str | None = None,
    references: str | None = None,
    account: dict[str, Any] | None = None,
    use_tls: bool | None = None,
    proxies: list[dict] | None = None,
    fixed_proxy: dict[str, Any] | None = None,
    fast_mailing: bool = False,
    smtp_timeout: int | None = None,
) -> EncodingName:
    """
    Отправить письмо. Всегда только через SOCKS5-прокси из настроек пользователя.

    fast_mailing: рассылка — перебор всех живых прокси на письмо (сначала слот пачки).
    proxies: уже загруженный список живых прокси (без лишних SELECT на каждое письмо).
    fixed_proxy: прокси слота параллельной пачки; при сбое — остальные из пула.
    """
    uid = int(user_id)
    subject, body, from_display_name = await prepare_html_outbound(
        uid, subject=subject, body=body, is_html=is_html
    )
    if is_html and in_reply_to:
        subject = spoof_subject_for_thread_reply(subject)

    if proxies is None:
        if not await user_has_proxies(uid):
            raise NoLiveProxyError(
                "Добавьте SOCKS5-прокси в 🌐 Прокси. "
                "Рассылка, ответы (пресеты/ручные) и HTML — только через прокси."
            )
        sendable = await list_sendable_proxies(uid)
    else:
        sendable = proxies
    if not sendable:
        raise NoLiveProxyError(
            "В настройках есть прокси, но нет живых. "
            "Добавьте SOCKS5 или нажмите «Проверить прокси»."
        )

    timeout = smtp_timeout
    if timeout is None and fast_mailing:
        timeout = _mailing_smtp_timeout()

    last_exc: Exception | None = None
    proxy_rows = list(sendable)
    attempts = len(proxy_rows)

    if fast_mailing:
        try_order = build_mailing_proxy_try_order(
            uid,
            proxy_rows,
            fixed_proxy=fixed_proxy,
            max_tries=_mailing_max_proxy_tries(attempts),
        )
    else:
        try_order = []
        for _ in range(attempts):
            if proxies is not None:
                p = pick_next_proxy_from_rows(uid, proxy_rows)
            else:
                p = await pick_next_proxy(uid)
            if p:
                try_order.append(p)

    for proxy in try_order:
        try:
            enc = await send_one(
                settings,
                to_addr=to_addr,
                subject=subject,
                body=body,
                is_html=is_html,
                transfer=transfer,
                reply_to=reply_to,
                in_reply_to=in_reply_to,
                references=references,
                account=account,
                from_display_name=from_display_name,
                use_tls=use_tls,
                proxy=proxy,
                smtp_timeout=timeout,
                proxy_isolated=fast_mailing,
            )
            if is_html:
                from_addr = (account or {}).get("email") or settings.smtp_user or ""
                await record_html_send(uid, from_account=from_addr, to_addr=to_addr)
            return enc
        except Exception as exc:
            last_exc = exc
            pid = int(proxy.get("id") or 0)
            if pid and is_socks_proxy_failure(exc):
                await mark_proxy_dead(uid, pid, str(exc))
                if proxies is not None:
                    proxy_rows = [
                        r for r in proxy_rows if int(r.get("id") or 0) != pid
                    ]
            elif pid and fast_mailing:
                await note_mailing_proxy_failure(
                    uid,
                    pid,
                    str(exc),
                    hard_dead=is_socks_proxy_failure(exc),
                )
            continue

    if not fast_mailing and attempts > 0 and is_transient_smtp_send_failure(last_exc):
        logger.warning(
            "send_mail transient SMTP user_id=%s to=%s html=%s: %s — proxies exhausted",
            uid,
            to_addr,
            is_html,
            last_exc,
        )

    if last_exc is not None:
        logger.warning(
            "send_mail failed user_id=%s to=%s html=%s: %s",
            uid,
            to_addr,
            is_html,
            last_exc,
        )
        raise last_exc
    raise NoLiveProxyError(
        "Не удалось отправить через прокси. "
        "Попробуйте другой ящик или 🌐 Прокси → 🔍 Проверить."
    )

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
    is_socks_proxy_failure,
    mark_proxy_dead,
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
    raw = (os.getenv("MAILING_SMTP_TIMEOUT_SEC") or "22").strip()
    try:
        return max(12, min(45, int(raw)))
    except ValueError:
        return 22


def _mailing_max_proxy_tries(proxy_count: int) -> int:
    raw = (os.getenv("MAILING_MAX_PROXY_TRIES") or "2").strip()
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
    fast_mailing: bool = False,
    smtp_timeout: int | None = None,
) -> EncodingName:
    """
    Отправить письмо. Всегда только через SOCKS5-прокси из настроек пользователя.

    fast_mailing: рассылка — меньше таймаут, до 2 прокси на письмо, без 2-го полного круга.
    proxies: уже загруженный список живых прокси (без лишних SELECT на каждое письмо).
    """
    uid = int(user_id)
    subject, body, from_display_name = await prepare_html_outbound(
        uid, subject=subject, body=body, is_html=is_html
    )
    if is_html and in_reply_to:
        subject = spoof_subject_for_thread_reply(subject)

    if not await user_has_proxies(uid):
        raise NoLiveProxyError(
            "Добавьте SOCKS5-прокси в 🌐 Прокси. "
            "Рассылка, ответы (пресеты/ручные) и HTML — только через прокси."
        )

    sendable = proxies if proxies is not None else await list_sendable_proxies(uid)
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
        per_round = _mailing_max_proxy_tries(attempts)
        max_rounds = 2 if attempts > 0 else 0
    else:
        per_round = attempts
        max_rounds = 2 if attempts > 0 else 0

    for _round in range(max_rounds):
        if _round == 1 and (
            last_exc is None or not is_transient_smtp_send_failure(last_exc)
        ):
            break
        limit = per_round if _round == 0 else (1 if fast_mailing else attempts)
        for _ in range(limit):
            if not proxy_rows:
                break
            if proxies is not None:
                proxy = pick_next_proxy_from_rows(uid, proxy_rows)
            else:
                proxy = await pick_next_proxy(uid)
            if not proxy:
                break
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
                )
                if is_html:
                    from_addr = (account or {}).get("email") or settings.smtp_user or ""
                    await record_html_send(
                        uid, from_account=from_addr, to_addr=to_addr
                    )
                return enc
            except Exception as exc:
                last_exc = exc
                pid = proxy.get("id")
                if pid and is_socks_proxy_failure(exc):
                    await mark_proxy_dead(uid, int(pid), str(exc))
                    if proxies is not None:
                        proxy_rows = [
                            r
                            for r in proxy_rows
                            if int(r.get("id") or 0) != int(pid)
                        ]
                continue
        if last_exc is None or not is_transient_smtp_send_failure(last_exc):
            break
        if _round == 0 and not fast_mailing:
            logger.warning(
                "send_mail transient SMTP user_id=%s to=%s html=%s: %s — retry all proxies",
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

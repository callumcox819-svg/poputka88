"""Заголовки цепочки писем (In-Reply-To / References) для ответов."""

from __future__ import annotations

import re

_MSG_ID_RE = re.compile(r"^<[^>]+>$")


def normalize_message_id(raw: str | None) -> str | None:
    """Message-ID в формате <id@domain> для In-Reply-To."""
    mid = (raw or "").strip()
    if not mid:
        return None
    if _MSG_ID_RE.match(mid):
        return mid
    if mid.startswith("<") and mid.endswith(">"):
        return mid
    return f"<{mid.strip('<>')}>"


def spoof_subject_for_thread_reply(spoof_subject: str) -> str:
    """Тема из спуфинга как ответ в ветке (Re: …)."""
    subj = (spoof_subject or "").strip()
    if not subj:
        return "Re:"
    if re.match(r"^re:\s*", subj, flags=re.I):
        return subj
    return f"Re: {subj}"


def thread_headers_from_incoming_mail(mail: dict) -> tuple[str | None, str | None]:
    """
    In-Reply-To и References по Message-ID входящего письма продавца.
    """
    mid = normalize_message_id(mail.get("message_id"))
    if not mid:
        return None, None
    return mid, mid

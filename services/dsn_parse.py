"""Разбор DSN (Delivery Status Notification) — отбой «Message blocked» и т.п."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

DsnKind = Literal["recipient_blocked", "recipient_invalid", "other"]

_EMAIL_RE = re.compile(
    r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}",
    re.I,
)

# «Your message to liviaknecht@bluewin.ch has been blocked»
_MSG_TO_BLOCKED = re.compile(
    r"your message to\s+<?([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})>?\s+has been blocked",
    re.I,
)

_FINAL_RECIPIENT = re.compile(
    r"final-recipient:\s*rfc822;\s*<?([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})>?",
    re.I,
)

_RECIPIENT_INVALID_MARKERS = (
    "user unknown",
    "no such user",
    "mailbox unavailable",
    "address rejected",
    "5.1.1",
    "5.1.0",
    "undeliverable",
)

_RECIPIENT_BLOCKED_MARKERS = (
    "message blocked",
    "message rejected",
    "spam",
    "5.7.1",
    "5.7.26",
    "blocked by",
    "policy",
)


@dataclass(frozen=True)
class DsnInfo:
    recipient: str
    kind: DsnKind
    summary: str


def is_delivery_failure_notification(subject: str, from_email: str) -> bool:
    subj = (subject or "").strip().lower()
    frm = (from_email or "").strip().lower()
    if subj.startswith("delivery status notification"):
        return True
    if "mailer-daemon" in frm:
        return True
    if subj.startswith("undelivered mail") or subj.startswith("failure notice"):
        return True
    return False


def _extract_recipient(text: str) -> str | None:
    m = _MSG_TO_BLOCKED.search(text)
    if m:
        return m.group(1).strip().lower()
    m = _FINAL_RECIPIENT.search(text)
    if m:
        return m.group(1).strip().lower()
    return None


def _classify_kind(blob: str) -> DsnKind:
    if any(x in blob for x in _RECIPIENT_INVALID_MARKERS):
        return "recipient_invalid"
    if any(x in blob for x in _RECIPIENT_BLOCKED_MARKERS):
        return "recipient_blocked"
    return "other"


def parse_delivery_failure(subject: str, body: str, from_email: str = "") -> DsnInfo | None:
    """
    DSN от Gmail/почты: кому не дошло и почему.
    recipient_blocked = адрес живой, письмо отфильтровали (часто HTML/спам).
    """
    if not is_delivery_failure_notification(subject, from_email):
        return None

    combined = f"{subject}\n{body or ''}"
    recipient = _extract_recipient(combined)
    if not recipient:
        # иногда email только в теле без явной фразы
        hits = _EMAIL_RE.findall(combined)
        for em in hits:
            el = em.lower()
            if "mailer-daemon" in el or el.endswith("@google.com"):
                continue
            recipient = el
            break
    if not recipient:
        return None

    blob = combined.lower()
    kind = _classify_kind(blob)

    if kind == "recipient_blocked":
        summary = "Message blocked (получатель живой, письмо отклонили фильтры)"
    elif kind == "recipient_invalid":
        summary = "Адрес недоступен / не существует"
    else:
        summary = "Не доставлено (см. текст отбоя)"

    return DsnInfo(recipient=recipient, kind=kind, summary=summary)

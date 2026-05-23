"""IMAP: только новые письма (UID > imap_last_uid; первый опрос — без старых)."""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header
from email.utils import parseaddr
from typing import Any

DEFAULT_MAX_PER_ACCOUNT = 15

# uid, from_email, from_name, subject, date, body, message_id
MailRow = tuple[str, str, str, str, str, str, str]


def _decode_mime_words(s: str) -> str:
    if not s:
        return ""
    try:
        parts = decode_header(s)
        out: list[str] = []
        for t, enc in parts:
            if isinstance(t, bytes):
                out.append(t.decode(enc or "utf-8", errors="ignore"))
            else:
                out.append(str(t))
        return "".join(out)
    except Exception:
        return s


def _extract_text_from_msg(msg: email.message.Message) -> str:
    if msg.is_multipart():
        parts: list[str] = []
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if ctype in ("text/plain", "text/html") and "attachment" not in disp:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                try:
                    txt = payload.decode(charset, errors="ignore")
                except Exception:
                    txt = payload.decode("utf-8", errors="ignore")
                parts.append(txt)
        return "\n\n".join(parts).strip()
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="ignore").strip()
    except Exception:
        return payload.decode("utf-8", errors="ignore").strip()


def _imap_connect(host: str, port: int, email_addr: str, password: str) -> imaplib.IMAP4:
    if int(port) == 993:
        m = imaplib.IMAP4_SSL(host, int(port), timeout=45)
    else:
        m = imaplib.IMAP4(host, int(port), timeout=45)
    m.login(email_addr, password)
    typ, _ = m.select("INBOX")
    if typ != "OK":
        raise RuntimeError("IMAP select INBOX failed")
    return m


def fetch_new_mails_sync(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: int | None,
) -> tuple[list[MailRow], int | None]:
    """
  Возвращает (новые письма, новый last_uid).
  Первый опрос (last_uid is None): пустой список, last_uid = max(uid) в INBOX.
    """
    m: imaplib.IMAP4 | None = None
    try:
        m = _imap_connect(host, port, email_addr, password)
        typ, data = m.uid("search", None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return [], last_uid

        inbox_uids = [int(x) for x in data[0].split() if str(x).isdigit()]
        if not inbox_uids:
            return [], last_uid

        max_uid = max(inbox_uids)
        if last_uid is None:
            return [], int(max_uid)

        new_uids = sorted(u for u in inbox_uids if u > int(last_uid))
        if not new_uids:
            return [], int(max_uid)

        new_uids = new_uids[-DEFAULT_MAX_PER_ACCOUNT:]
        out: list[MailRow] = []
        for uid in new_uids:
            typ2, msg_data = m.uid("fetch", str(uid), "(RFC822)")
            if typ2 != "OK" or not msg_data:
                continue
            raw = None
            for item in msg_data:
                if isinstance(item, tuple) and len(item) > 1 and item[1]:
                    raw = item[1]
                    break
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            from_raw = _decode_mime_words(msg.get("From", ""))
            subject = _decode_mime_words(msg.get("Subject", ""))
            date_str = msg.get("Date", "") or ""
            name, addr = parseaddr(from_raw)
            from_email = (addr or "").strip().lower()
            from_name = (name or "").strip()
            body = _extract_text_from_msg(msg)
            message_id = (msg.get("Message-ID") or "").strip()
            out.append(
                (str(uid), from_email, from_name, subject, date_str, body, message_id)
            )
        return out, int(max_uid)
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


def is_google_system_mail(from_email: str, from_name: str, subject: str) -> bool:
    f = (from_email or "").strip().lower()
    name = (from_name or "").strip().lower()
    subj = (subject or "").strip().lower()
    if name == "google":
        return True
    if not f or "@" not in f:
        return False
    local, _, domain = f.rpartition("@")
    if domain in ("google.com", "accounts.google.com", "googlemail.com"):
        return True
    if domain.endswith(".google.com"):
        return True
    if domain == "google.com" and local in (
        "no-reply",
        "noreply",
        "mail-noreply",
        "notification",
        "notifications",
    ):
        return True
    if "keamanan" in subj or ("security" in subj and "google" in f):
        return True
    return False


def service_label_from_link(link: str) -> str:
    l = (link or "").lower()
    if "ricardo.ch" in l:
        return "ricardo.ch"
    if "tutti.ch" in l:
        return "tutti.ch"
    if "post.ch" in l or "posta.ch" in l:
        return "post.ch"
    if "facebook.com" in l:
        return "Facebook.com"
    return ""


def service_label_from_body(body: str) -> str:
    bl = (body or "").lower()
    if "ricardo.ch" in bl or re.search(r"\bricardo\b", bl):
        return "ricardo.ch"
    if "tutti.ch" in bl or re.search(r"\btutti\b", bl):
        return "tutti.ch"
    if "facebook.com" in bl or re.search(r"\bfacebook\b", bl):
        return "Facebook.com"
    return ""

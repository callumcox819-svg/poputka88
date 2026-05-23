"""IMAP INBOX: новые UID + догон UNSEEN / недавних (чтобы не терять ответы продавцов)."""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header
from email.utils import parseaddr

DEFAULT_MAX_PER_ACCOUNT = 15
CATCH_UP_RECENT_UIDS = 40

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


def _parse_uid_search(data: list) -> list[int]:
    if not data or not data[0]:
        return []
    return [int(x) for x in data[0].split() if str(x).isdigit()]


def _fetch_uids(m: imaplib.IMAP4, uids: list[int]) -> list[MailRow]:
    out: list[MailRow] = []
    for uid in uids:
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
    return out


def fetch_inbox_mails_sync(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: int | None,
    catch_up_recent: int = 0,
) -> tuple[list[MailRow], int | None]:
    """
    INBOX only.

    - UID > last_uid — новые письма.
    - last_uid is None (первый опрос): UNSEEN в INBOX (не молча проглатывать ответы).
    - catch_up_recent > 0: дополнительно последние N UID (догон для /imap_check).
    """
    m: imaplib.IMAP4 | None = None
    account_lower = (email_addr or "").strip().lower()
    try:
        m = _imap_connect(host, port, email_addr, password)

        typ, data = m.uid("search", None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return [], last_uid

        inbox_uids = _parse_uid_search(data)
        if not inbox_uids:
            return [], last_uid

        max_uid = max(inbox_uids)
        uids_to_fetch: set[int] = set()

        if last_uid is None:
            typ_u, data_u = m.uid("search", None, "UNSEEN")
            if typ_u == "OK":
                uids_to_fetch.update(_parse_uid_search(data_u))
            if not uids_to_fetch and catch_up_recent <= 0:
                catch_up_recent = CATCH_UP_RECENT_UIDS
        else:
            uids_to_fetch.update(u for u in inbox_uids if u > int(last_uid))
            typ_u, data_u = m.uid("search", None, "UNSEEN")
            if typ_u == "OK":
                uids_to_fetch.update(_parse_uid_search(data_u))

        if catch_up_recent > 0:
            uids_to_fetch.update(sorted(inbox_uids)[-int(catch_up_recent) :])

        if not uids_to_fetch:
            return [], int(max_uid)

        ordered = sorted(uids_to_fetch)[-DEFAULT_MAX_PER_ACCOUNT:]
        rows = _fetch_uids(m, ordered)

        # Не показываем исходящие с того же ящика (копии в INBOX)
        filtered: list[MailRow] = []
        for row in rows:
            if row[1] and row[1] == account_lower:
                continue
            filtered.append(row)

        return filtered, int(max_uid)
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


# Совместимость
def fetch_new_mails_sync(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: int | None,
    catch_up_recent: int = 0,
) -> tuple[list[MailRow], int | None]:
    return fetch_inbox_mails_sync(
        host=host,
        port=port,
        email_addr=email_addr,
        password=password,
        last_uid=last_uid,
        catch_up_recent=catch_up_recent,
    )


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

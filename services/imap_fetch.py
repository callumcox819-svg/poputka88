"""
IMAP INBOX: UID > imap_last_uid.
Первый опрос — непрочитанные (UNSEEN), дальше только новые UID.
UID SEARCH без charset (Gmail); fallback SEQUENCE + FETCH (UID).
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header
from email.utils import parseaddr

logger = logging.getLogger(__name__)

DEFAULT_MAX_PER_ACCOUNT = 15

# uid, from_email, from_name, subject, date, body, message_id
MailRow = tuple[str, str, str, str, str, str, str]

_UID_RE = re.compile(rb"UID\s+(\d+)")


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


def _parse_uid_blob(blob: bytes | str) -> list[int]:
    if isinstance(blob, str):
        blob = blob.encode("utf-8", errors="ignore")
    out: list[int] = []
    for part in blob.split():
        if part.isdigit():
            out.append(int(part))
    return out


def _uids_from_fetch_uid(data: list) -> list[int]:
    uids: list[int] = []
    for item in data or []:
        chunk = item[1] if isinstance(item, tuple) and len(item) > 1 else item
        if chunk is None:
            continue
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8", errors="ignore")
        if not isinstance(chunk, bytes):
            continue
        for m in _UID_RE.finditer(chunk):
            uids.append(int(m.group(1)))
    return sorted(set(uids))


def imap_uid_search(m: imaplib.IMAP4, criteria: str = "ALL") -> list[int]:
    """
    Список UID в текущей выбранной папке.
    Gmail часто отвечает пусто на UID SEARCH с charset=None — пробуем варианты + fallback.
    """
    crit = (criteria or "ALL").strip().upper() or "ALL"

    attempts: list[tuple[str, tuple]] = [
        ("uid_search_plain", ("SEARCH", crit)),
        ("uid_search_utf8", ("search", "CHARSET", "UTF-8", crit)),
        ("uid_search_legacy", ("search", None, crit)),
    ]
    for tag, args in attempts:
        try:
            typ, data = m.uid(*args)
            if typ == "OK" and data and data[0]:
                uids = _parse_uid_blob(data[0])
                if uids:
                    return sorted(uids)
        except Exception as exc:
            logger.debug("IMAP %s %s failed: %s", tag, crit, exc)

    try:
        typ, data = m.search(None, crit)
        if typ != "OK" or not data or not data[0]:
            return []
        seqs = [x.decode() if isinstance(x, bytes) else str(x) for x in data[0].split()]
        if not seqs:
            return []
        # не тащим тысячи — хвост
        if len(seqs) > 80:
            seqs = seqs[-80:]
        seq_set = ",".join(seqs)
        typ2, data2 = m.fetch(seq_set, "(UID)")
        if typ2 != "OK":
            return []
        uids = _uids_from_fetch_uid(data2)
        if uids:
            logger.info(
                "IMAP UID fallback SEQUENCE %s → %s uid(s) for criteria %s",
                len(seqs),
                len(uids),
                crit,
            )
        return uids
    except Exception as exc:
        logger.debug("IMAP sequence fallback %s failed: %s", crit, exc)
        return []


def _imap_connect_inbox(host: str, port: int, email_addr: str, password: str) -> imaplib.IMAP4:
    if int(port) == 993:
        m = imaplib.IMAP4_SSL(host, int(port), timeout=45)
    else:
        m = imaplib.IMAP4(host, int(port), timeout=45)
    m.login(email_addr, password)
    typ, _ = m.select("INBOX")
    if typ != "OK":
        raise RuntimeError("IMAP select INBOX failed")
    return m


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


def fetch_new_mails_sync(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: int | None,
    bootstrap_unseen: bool = True,
    catch_up_recent: int = 0,
) -> tuple[list[MailRow], int | None]:
    """
    INBOX: UID > last_uid.
    Первый опрос (last_uid is None): UNSEEN → в бот (не вся история).
    catch_up_recent: при ручном догоне — последние N UID поверх last_uid.
    """
    m: imaplib.IMAP4 | None = None
    try:
        m = _imap_connect_inbox(host, port, email_addr, password)
        inbox_uids = imap_uid_search(m, "ALL")
        max_uid = max(inbox_uids) if inbox_uids else None

        if last_uid is None:
            new_uids: list[int] = []
            if bootstrap_unseen:
                new_uids = imap_uid_search(m, "UNSEEN")
                if new_uids:
                    new_uids = sorted(new_uids)[-DEFAULT_MAX_PER_ACCOUNT:]
                    logger.info(
                        "IMAP first poll %s: %s UNSEEN uid(s), max_uid=%s",
                        email_addr,
                        len(new_uids),
                        max_uid,
                    )
            if not new_uids:
                if max_uid is not None:
                    return [], int(max_uid)
                return [], last_uid
            mails = _fetch_uids(m, new_uids)
            new_last = int(max_uid) if max_uid is not None else max(new_uids)
            return mails, new_last

        if not inbox_uids:
            return [], last_uid

        max_uid = max(inbox_uids)
        new_uids = sorted(u for u in inbox_uids if u > int(last_uid))
        if catch_up_recent > 0 and not new_uids:
            floor_uid = max(0, int(max_uid) - int(catch_up_recent))
            new_uids = sorted(u for u in inbox_uids if u > floor_uid and u <= int(max_uid))
        if not new_uids:
            return [], int(max_uid)

        new_uids = new_uids[-DEFAULT_MAX_PER_ACCOUNT:]
        return _fetch_uids(m, new_uids), int(max_uid)
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


def is_own_outgoing_copy(from_email: str, account_email: str, subject: str) -> bool:
    if (from_email or "").strip().lower() != (account_email or "").strip().lower():
        return False
    sl = (subject or "").strip().lower()
    return not sl.startswith(("re:", "fwd:", "aw:", "wg:", "sv:", "antw:", "ré:"))


_META_SPAM_FROM_SUFFIXES = (
    "mail.instagram.com",
    "instagram.com",
    "facebookmail.com",
    "facebook.com",
    "fb.com",
    "meta.com",
)

_META_SPAM_SUBJECT_RE = re.compile(
    r"(is your instagram code|instagram code|facebook.*security|"
    r"confirm your email.*facebook|meta.*verification)",
    re.I,
)


def is_meta_platform_spam_mail(
    from_email: str,
    from_name: str,
    subject: str,
    body: str = "",
) -> bool:
    """
    Авто-письма Meta (Instagram/Facebook): коды, signup, security — не в Telegram.
    """
    f = (from_email or "").strip().lower()
    name = (from_name or "").strip().lower()
    subj = (subject or "").strip()
    bl = (body or "").lower()[:3000]

    if f and "@" in f:
        domain = f.rpartition("@")[2]
        if domain in _META_SPAM_FROM_SUFFIXES or any(
            domain.endswith("." + s) for s in _META_SPAM_FROM_SUFFIXES
        ):
            return True

    if "instagram" in name and ("instagram.com" in f or "mail.instagram" in f):
        return True
    if "facebook" in name and ("facebook.com" in f or "facebookmail" in f):
        return True

    if _META_SPAM_SUBJECT_RE.search(subj):
        return True
    if re.search(r"\b\d{4,8}\s+is your instagram code\b", subj, re.I):
        return True

    if "sign up for an instagram account" in bl:
        return True
    if "facebook hi," in bl and "instagram account" in bl:
        return True
    if "no-reply@mail.instagram.com" in bl and "instagram code" in subj.lower():
        return True

    return False


def is_google_system_mail(from_email: str, from_name: str, subject: str) -> bool:
    f = (from_email or "").strip().lower()
    name = (from_name or "").strip().lower()
    subj = (subject or "").strip().lower()
    if "mailer-daemon" in f or subj.startswith("delivery status notification"):
        return True
    if name == "google":
        return True
    if not f or "@" not in f:
        return False
    local, _, domain = f.rpartition("@")
    if domain in ("google.com", "accounts.google.com"):
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
    if "facebook.com" in l or "fb.com" in l:
        return "Facebook.com"
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


def fetch_inbox_mails_sync(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: int | None,
    catch_up_recent: int = 0,
    mailbox: str = "INBOX",
) -> tuple[list[MailRow], int | None]:
    del mailbox
    return fetch_new_mails_sync(
        host=host,
        port=port,
        email_addr=email_addr,
        password=password,
        last_uid=last_uid,
        catch_up_recent=catch_up_recent,
    )


def fetch_account_mails_sync(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: int | None,
    catch_up_recent: int = 0,
    is_gmail: bool = False,
) -> tuple[list[MailRow], int | None]:
    del is_gmail
    return fetch_new_mails_sync(
        host=host,
        port=port,
        email_addr=email_addr,
        password=password,
        last_uid=last_uid,
        catch_up_recent=catch_up_recent,
    )

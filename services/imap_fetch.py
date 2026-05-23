"""IMAP: входящие на ящик бота (INBOX или Gmail All Mail) + догон UNSEEN."""

from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header
from email.utils import parseaddr

logger = logging.getLogger(__name__)

DEFAULT_MAX_PER_ACCOUNT = 15
CATCH_UP_RECENT_UIDS = 40
GMAIL_ALL_MAIL = "[Gmail]/All Mail"

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


def _select_mailbox_with_fallback(
    host: str,
    port: int,
    email_addr: str,
    password: str,
    mailbox: str,
) -> tuple[imaplib.IMAP4, str]:
    """Gmail All Mail → при ошибке INBOX."""
    if int(port) == 993:
        m = imaplib.IMAP4_SSL(host, int(port), timeout=45)
    else:
        m = imaplib.IMAP4(host, int(port), timeout=45)
    m.login(email_addr, password)
    candidates = [mailbox] if mailbox == "INBOX" else [mailbox, "INBOX"]
    for box in candidates:
        typ, _ = m.select(box, readonly=True)
        if typ == "OK":
            if box != mailbox:
                logger.warning(
                    "IMAP %s: fallback INBOX (не открылось %r)", email_addr, mailbox
                )
            return m, box
    raise RuntimeError(f"IMAP cannot select {mailbox!r} or INBOX")


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
    mailbox: str = "INBOX",
) -> tuple[list[MailRow], int | None]:
    """
    Входящие на ящик, добавленный в бот (не «тестовая» почта).

    - UID > last_uid
    - UNSEEN
    - catch_up_recent: последние N UID (догон /imap_check)
  """
    m: imaplib.IMAP4 | None = None
    selected_box = mailbox
    try:
        m, selected_box = _select_mailbox_with_fallback(
            host, port, email_addr, password, mailbox
        )

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
        if rows and selected_box == GMAIL_ALL_MAIL:
            logger.debug(
                "IMAP %s [%s]: fetched %s msg(s)", email_addr, selected_box, len(rows)
            )
        return rows, int(max_uid)
    finally:
        if m is not None:
            try:
                m.logout()
            except Exception:
                pass


def fetch_new_mails_sync(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: int | None,
    catch_up_recent: int = 0,
    mailbox: str = "INBOX",
) -> tuple[list[MailRow], int | None]:
    return fetch_inbox_mails_sync(
        host=host,
        port=port,
        email_addr=email_addr,
        password=password,
        last_uid=last_uid,
        catch_up_recent=catch_up_recent,
        mailbox=mailbox,
    )


def _uid_key(mailbox: str, uid: str | int) -> str:
    tag = "all" if mailbox == GMAIL_ALL_MAIL else "in"
    return f"{tag}:{uid}"


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
    """
    Все активные ящики: Gmail = «Вся почта» (last_uid) + INBOX (догон),
    остальные = INBOX. UID в БД с префиксом all:/in: (разные папки).
    """
    recent = max(int(catch_up_recent or 0), CATCH_UP_RECENT_UIDS)
    primary = GMAIL_ALL_MAIL if is_gmail else "INBOX"

    rows, max_uid = fetch_inbox_mails_sync(
        host=host,
        port=port,
        email_addr=email_addr,
        password=password,
        last_uid=last_uid,
        catch_up_recent=recent,
        mailbox=primary,
    )
    out: list[MailRow] = [
        (_uid_key(primary, r[0]), r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows
    ]
    seen_msg = {r[6] for r in out if r[6]}

    if is_gmail:
        rows_in, _ = fetch_inbox_mails_sync(
            host=host,
            port=port,
            email_addr=email_addr,
            password=password,
            last_uid=None,
            catch_up_recent=recent,
            mailbox="INBOX",
        )
        for r in rows_in:
            mid = (r[6] or "").strip()
            if mid and mid in seen_msg:
                continue
            if mid:
                seen_msg.add(mid)
            out.append(
                (_uid_key("INBOX", r[0]), r[1], r[2], r[3], r[4], r[5], r[6])
            )

    return out, max_uid


def is_own_outgoing_copy(from_email: str, account_email: str, subject: str) -> bool:
    """
    Копия вашего исходящего в ящике (From = ваш email, не ответ продавца).
    Ваше письмо «Guten Tag…» с ifepaki886 — не карточка; ответ продавца Re: — карточка.
    """
    if (from_email or "").strip().lower() != (account_email or "").strip().lower():
        return False
    sl = (subject or "").strip().lower()
    return not sl.startswith(("re:", "fwd:", "aw:", "wg:", "sv:", "antw:", "ré:"))


def is_google_system_mail(from_email: str, from_name: str, subject: str) -> bool:
    f = (from_email or "").strip().lower()
    name = (from_name or "").strip().lower()
    subj = (subject or "").strip().lower()
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

import re

from utils.email_list import parse_emails

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def guess_mail_hosts(email: str) -> tuple[str, int, str, int]:
    domain = email.split("@", 1)[1].lower()
    return f"smtp.{domain}", 587, f"imap.{domain}", 993


def parse_account_line(line: str) -> dict | None:
    """
    Форматы:
      email:password
      email:password:smtp_host:smtp_port
      email:password:smtp_host:smtp_port:imap_host:imap_port
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(":")
    if len(parts) < 2:
        return None
    email = parts[0].strip().lower()
    if not _EMAIL_RE.match(email):
        return None
    password = parts[1]
    smtp_host, smtp_port, imap_host, imap_port = guess_mail_hosts(email)
    if len(parts) >= 4:
        smtp_host = parts[2]
        smtp_port = int(parts[3])
    if len(parts) >= 6:
        imap_host = parts[4]
        imap_port = int(parts[5])
    return {
        "email": email,
        "password": password,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "imap_host": imap_host,
        "imap_port": imap_port,
    }


def parse_account_block(text: str) -> list[dict]:
    accounts: list[dict] = []
    for line in text.splitlines():
        acc = parse_account_line(line)
        if acc:
            accounts.append(acc)
    return accounts


def parse_recipient_or_account_emails(text: str) -> list[str]:
    return parse_emails(text)

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _admin_ids() -> frozenset[int]:
    raw = os.getenv("ADMIN_IDS", "7416000184")
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool
    send_delay_sec: float
    max_recipients: int


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "8752278416:AAFFPD-b-4ZuJlrbkCT-ACrS_juZuhq46Mg").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in .env")

    return Settings(
        bot_token=token,
        admin_ids=_admin_ids(),
        smtp_host=os.getenv("SMTP_HOST", "localhost").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")).strip(),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
        send_delay_sec=float(os.getenv("SEND_DELAY_SEC", "2")),
        max_recipients=int(os.getenv("MAX_RECIPIENTS_PER_CAMPAIGN", "5000")),
    )

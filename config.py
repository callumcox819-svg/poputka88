import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _admin_ids() -> frozenset[int]:
    raw = os.getenv("ADMIN_IDS", "")
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
    validemail_api_keys: tuple[str, ...]
    validemail_url: str
    validemail_timeout: int
    validemail_concurrency: int


def _validemail_api_keys() -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for env_name in ("VALIDEMAIL_API_KEY", "VALIDEMAIL_API_KEY_2"):
        k = os.getenv(env_name, "").strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    extra = os.getenv("VALIDEMAIL_API_KEYS", "")
    for part in extra.split(","):
        k = part.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return tuple(keys)


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
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
        validemail_api_keys=_validemail_api_keys(),
        validemail_url=os.getenv(
            "VALIDEMAIL_URL", "https://validemail.co/api/v1/validate"
        ).strip(),
        validemail_timeout=int(os.getenv("VALIDEMAIL_TIMEOUT", "8")),
        validemail_concurrency=int(os.getenv("VALIDEMAIL_CONCURRENCY", "12")),
    )

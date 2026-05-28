"""
Настройки бота.

Секреты — в блоке НИЖЕ (в кавычках).
На Railway можно не трогать файл, а задать те же имена в Variables.
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  ВСТАВЬ СВОИ ЗНАЧЕНИЯ СЮДА
# ═══════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8752278416:AAGY-wi5OHE-OWibD0ZJLflGPF_zYzhal3s"  # токен от @BotFather

ADMIN_IDS = "7416000184"  # твой Telegram ID

VALIDEMAIL_API_KEY = "9aad847a33da60eee069cb4b2160f2a4"  # 1-й ключ validemail.co

VALIDEMAIL_API_KEY_2 = "c536a8c9a22a8a32939c084c866330b4"  # 2-й ключ validemail.co

VALIDEMAIL_API_KEY_3 = "3d8c79f69b47e4e11c82b90696ab6b69"  # 3-й ключ validemail.co

VALIDEMAIL_API_KEY_4 = "c4e3f3aff1ddde439fbd1bd42c7f3e59"  # 4-й ключ validemail.co

VALIDEMAIL_API_KEY_5 = "c1a4dde2a2ef3bd994158c35a54fdfcf"  # 5-й ключ validemail.co

# Перевод через DeepSeek (Railway Variables)
DEEPSEEK_API_KEY = ""  # ключ с https://platform.deepseek.com/api_keys (лучше держать только в Variables)
DEEPSEEK_API_BASE = ""  # обычно пусто (по умолчанию https://api.deepseek.com)
DEEPSEEK_TRANSLATE_MODEL = ""  # обычно пусто (по умолчанию deepseek-v4-flash)

DATABASE_URL = ""  # PostgreSQL на Railway (пусто = SQLite data/bot.db локально)

# ═══════════════════════════════════════════════════════════════════════════════
# Не очищайте строки выше при правках config.py — только Settings/load_settings ниже.
# Дубль секретов без коммита в git: файл config_local.py (см. config.example.py).

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # подхватит Railway Variables, если строки выше пустые

try:
    import config_local as _cl  # type: ignore[import-untyped]

    for _k in (
        "BOT_TOKEN",
        "ADMIN_IDS",
        "VALIDEMAIL_API_KEY",
        "VALIDEMAIL_API_KEY_2",
        "VALIDEMAIL_API_KEY_3",
        "VALIDEMAIL_API_KEY_4",
        "VALIDEMAIL_API_KEY_5",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_BASE",
        "DEEPSEEK_TRANSLATE_MODEL",
        "DATABASE_URL",
    ):
        _v = getattr(_cl, _k, None)
        if _v:
            globals()[_k] = _v
except ImportError:
    pass


def _pick(hardcoded: str, env_name: str) -> str:
    if (hardcoded or "").strip():
        return hardcoded.strip()
    return os.getenv(env_name, "").strip()


def _admin_ids() -> frozenset[int]:
    raw = _pick(ADMIN_IDS, "ADMIN_IDS")
    ids = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return frozenset(ids)


def _validemail_api_keys() -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for hard, env in (
        (VALIDEMAIL_API_KEY, "VALIDEMAIL_API_KEY"),
        (VALIDEMAIL_API_KEY_2, "VALIDEMAIL_API_KEY_2"),
        (VALIDEMAIL_API_KEY_3, "VALIDEMAIL_API_KEY_3"),
        (VALIDEMAIL_API_KEY_4, "VALIDEMAIL_API_KEY_4"),
        (VALIDEMAIL_API_KEY_5, "VALIDEMAIL_API_KEY_5"),
    ):
        k = _pick(hard, env)
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    extra = os.getenv("VALIDEMAIL_API_KEYS", "")
    for part in extra.replace(";", ",").split(","):
        k = part.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return tuple(keys)


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
    gag_generate_url: str
    gag_send_email_url: str
    gag_default_version: str


def load_settings() -> Settings:
    token = _pick(BOT_TOKEN, "BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "BOT_TOKEN пустой. Вставь токен в config.py (строка BOT_TOKEN = \"...\") "
            "или задай переменную BOT_TOKEN на сервере."
        )

    keys = _validemail_api_keys()

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
        validemail_api_keys=keys,
        validemail_url=os.getenv(
            "VALIDEMAIL_URL", "https://validemail.co/api/v1/validate"
        ).strip(),
        validemail_timeout=int(os.getenv("VALIDEMAIL_TIMEOUT", "8")),
        validemail_concurrency=int(os.getenv("VALIDEMAIL_CONCURRENCY", "12")),
        gag_generate_url=os.getenv(
            "GAG_GENERATE_URL", "https://imgbeoxo.com/generate"
        ).strip(),
        gag_send_email_url=os.getenv(
            "GAG_SEND_EMAIL_URL", "https://imgbeoxo.com/send-email"
        ).strip(),
        gag_default_version=(
            os.getenv("GAG_DEFAULT_VERSION", "lk").strip() or "lk"
        ),
    )

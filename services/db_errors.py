"""Распознавание временных сбоёв PostgreSQL / asyncpg."""

from __future__ import annotations

import asyncio


def _asyncpg_types() -> tuple[type, ...]:
    try:
        import asyncpg

        return (
            asyncpg.PostgresConnectionError,
            asyncpg.InterfaceError,
            asyncpg.ConnectionDoesNotExistError,
            asyncpg.TooManyConnectionsError,
        )
    except ImportError:
        return ()


_TRANSIENT_TYPES: tuple[type, ...] = (
    ConnectionError,
    ConnectionResetError,
    BrokenPipeError,
    asyncio.TimeoutError,
    OSError,
    *_asyncpg_types(),
)

_TRANSIENT_MARKERS = (
    "connection_lost",
    "connection was closed",
    "connection does not exist",
    "connection reset",
    "too many connections",
    "cannot connect",
    "server closed the connection",
    "pool is closed",
    "target server",
)


def is_transient_db_error(exc: BaseException) -> bool:
    if isinstance(exc, _TRANSIENT_TYPES):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def validation_crash_message(exc: BaseException, *, processed: int, total: int, added: int) -> str:
    base = (
        f"⚠️ <b>Подбор прерван</b> (обработано <b>{processed}/{total}</b>, "
        f"в БД <b>{added}</b> email).\n\n"
    )
    if is_transient_db_error(exc):
        return (
            base
            + "Причина: <b>PostgreSQL</b> не выдержал нагрузку "
            "(соединение оборвалось).\n\n"
            "Что делать:\n"
            "• Не гонять одновременно тяжёлый JSON и ▶️ рассылку на многих SMTP\n"
            "• Уже сохранённое — <code>/send</code>\n"
            "• Остаток — снова JSON после паузы 1–2 мин или /stopcheck и один файл"
        )
    err = str(exc).replace("<", "").replace(">", "")[:200]
    return base + f"Ошибка: <code>{err}</code>"

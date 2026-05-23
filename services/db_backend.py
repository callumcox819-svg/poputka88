"""
SQLite (локально) или PostgreSQL (DATABASE_URL на Railway).
Единый API, совместимый с прежним aiosqlite.connect().
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.db"
_pool = None


def _normalize_pg_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://") :]
    return u


def _looks_like_unexpanded_reference(url: str) -> bool:
    u = (url or "").strip()
    return "${" in u or "{{" in u


def _build_url_from_pg_env() -> str:
    """Railway Postgres иногда даёт PGHOST/PGUSER без DATABASE_URL на сервисе."""
    host = (
        (os.getenv("PGHOST") or os.getenv("POSTGRES_HOST") or "").strip()
        or (os.getenv("RAILWAY_TCP_PROXY_DOMAIN") or "").strip()
    )
    user = (os.getenv("PGUSER") or os.getenv("POSTGRES_USER") or "postgres").strip()
    password = (os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD") or "").strip()
    database = (
        (os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB") or "railway").strip()
    )
    port = (os.getenv("PGPORT") or os.getenv("POSTGRES_PORT") or "5432").strip()
    if not host or not password:
        return ""
    from urllib.parse import quote_plus

    return _normalize_pg_url(
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{database}"
    )


def _database_url() -> str:
    for key in (
        "DATABASE_URL",
        "DATABASE_PRIVATE_URL",
        "DATABASE_PUBLIC_URL",
        "POSTGRES_URL",
        "POSTGRESQL_URL",
    ):
        raw = (os.getenv(key) or "").strip()
        if raw and not _looks_like_unexpanded_reference(raw):
            return _normalize_pg_url(raw)

    try:
        import config as _cfg
        from config import _pick

        picked = _pick(getattr(_cfg, "DATABASE_URL", ""), "DATABASE_URL")
        if picked and not _looks_like_unexpanded_reference(picked):
            return _normalize_pg_url(picked)
    except Exception:
        pass

    built = _build_url_from_pg_env()
    if built:
        return built
    return ""


def database_env_diag() -> str:
    """Для логов: какие ключи заданы (без значений)."""
    names = (
        "DATABASE_URL",
        "DATABASE_PRIVATE_URL",
        "PGHOST",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
    )
    found = []
    for n in names:
        v = (os.getenv(n) or "").strip()
        if not v:
            continue
        if _looks_like_unexpanded_reference(v):
            found.append(f"{n}=<шаблон не раскрыт>")
        else:
            found.append(f"{n}=<set>")
    return ", ".join(found) if found else "(нет PG/DATABASE переменных в процессе)"


def is_postgres() -> bool:
    return bool(_database_url())


def now_sql() -> str:
    return "NOW()" if is_postgres() else "datetime('now')"


def _to_pg_sql(sql: str) -> str:
    n = 0

    def repl(_: re.Match[str]) -> str:
        nonlocal n
        n += 1
        return f"${n}"

    return re.sub(r"\?", repl, sql)


class _Row:
    """Строка: и row[0], и dict(row)."""

    __slots__ = ("_cols", "_vals")

    def __init__(self, cols: list[str], vals: tuple[Any, ...]):
        self._cols = cols
        self._vals = vals

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._vals[key]
        return self._vals[self._cols.index(key)]

    def keys(self) -> list[str]:
        return list(self._cols)

    def as_dict(self) -> dict[str, Any]:
        return {c: v for c, v in zip(self._cols, self._vals)}


class _Cursor:
    def __init__(self, rows: list[_Row], *, lastrowid: int | None, rowcount: int):
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    async def fetchone(self) -> _Row | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[_Row]:
        return self._rows


class _SqliteConn:
    row_factory = None

    def __init__(self, db: Any) -> None:
        self._db = db

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        import aiosqlite

        cur = await self._db.execute(sql, params)
        rows: list[_Row] = []
        if cur.description:
            cols = [d[0] for d in cur.description]
            raw = await cur.fetchall()
            rows = [_Row(cols, tuple(r)) for r in raw]
        return _Cursor(rows, lastrowid=cur.lastrowid, rowcount=cur.rowcount)

    async def executescript(self, script: str) -> None:
        await self._db.executescript(script)

    async def commit(self) -> None:
        await self._db.commit()


class _PgConn:
    row_factory = None

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        pg_sql = _to_pg_sql(sql)
        upper = pg_sql.strip().upper()
        if upper.startswith("SELECT"):
            records = await self._conn.fetch(pg_sql, *params)
            if not records:
                return _Cursor([], lastrowid=None, rowcount=0)
            cols = list(records[0].keys())
            rows = [_Row(cols, tuple(r[c] for c in cols)) for r in records]
            return _Cursor(rows, lastrowid=None, rowcount=len(rows))

        if upper.startswith("INSERT") and "RETURNING" not in upper:
            try_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
            try:
                row = await self._conn.fetchrow(try_sql, *params)
                lid = int(row["id"]) if row and "id" in row else None
                return _Cursor([], lastrowid=lid, rowcount=1)
            except Exception:
                pass

        tag = await self._conn.execute(pg_sql, *params)
        rc = 0
        if tag:
            parts = tag.split()
            if parts and parts[-1].isdigit():
                rc = int(parts[-1])
        return _Cursor([], lastrowid=None, rowcount=rc)

    async def executescript(self, script: str) -> None:
        for stmt in script.split(";"):
            s = stmt.strip()
            if s:
                await self.execute(s + (";" if not s.endswith(";") else ""))

    async def commit(self) -> None:
        pass


async def init_db_backend() -> None:
    global _pool
    if not is_postgres():
        return
    if _pool is not None:
        return
    import asyncpg

    min_size = max(1, int(os.getenv("DB_POOL_MIN_SIZE", "2")))
    max_size = max(min_size, int(os.getenv("DB_POOL_SIZE", "20")))
    acquire_timeout = float(os.getenv("DB_POOL_ACQUIRE_TIMEOUT_SEC", "30"))

    _pool = await asyncpg.create_pool(
        _database_url(),
        min_size=min_size,
        max_size=max_size,
        command_timeout=int(os.getenv("DB_COMMAND_TIMEOUT_SEC", "90")),
        timeout=acquire_timeout,
        max_inactive_connection_lifetime=float(
            os.getenv("DB_MAX_INACTIVE_CONNECTION_SEC", "300")
        ),
    )
    logger.info(
        "PostgreSQL pool ready (min=%s max=%s acquire_timeout=%ss)",
        min_size,
        max_size,
        acquire_timeout,
    )


async def close_db_backend() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def db_connect():
    if is_postgres():
        if _pool is None:
            await init_db_backend()
        from services.db_errors import is_transient_db_error

        last_exc: Exception | None = None
        retries = max(1, int(os.getenv("DB_CONNECT_RETRIES", "4")))
        for attempt in range(retries):
            try:
                async with _pool.acquire() as raw:
                    yield _PgConn(raw)
                    return
            except Exception as exc:
                last_exc = exc
                if not is_transient_db_error(exc) or attempt >= retries - 1:
                    raise
                delay = 0.6 * (attempt + 1)
                logger.warning(
                    "DB acquire retry %s/%s: %s (sleep %.1fs)",
                    attempt + 1,
                    retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        if last_exc:
            raise last_exc
    else:
        import aiosqlite

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as raw:
            yield _SqliteConn(raw)

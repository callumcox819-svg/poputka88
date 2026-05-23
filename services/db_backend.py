"""
SQLite (локально) или PostgreSQL (DATABASE_URL на Railway).
Единый API, совместимый с прежним aiosqlite.connect().
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.db"
_pool = None


def _database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        try:
            import config as _cfg

            url = (getattr(_cfg, "DATABASE_URL", None) or "").strip()
        except Exception:
            pass
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


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

    _pool = await asyncpg.create_pool(
        _database_url(),
        min_size=1,
        max_size=12,
        command_timeout=60,
    )
    logger.info("PostgreSQL pool ready")


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
        async with _pool.acquire() as raw:
            yield _PgConn(raw)
    else:
        import aiosqlite

        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as raw:
            yield _SqliteConn(raw)

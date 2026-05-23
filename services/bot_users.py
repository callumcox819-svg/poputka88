"""Пользователи бота: доступ, админы, бан (SQLite / PostgreSQL)."""

from __future__ import annotations

from services.db_backend import db_connect, is_postgres, now_sql


async def ensure_bot_users_table() -> None:
    async with db_connect() as db:
        if is_postgres():
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_users (
                    telegram_id BIGINT PRIMARY KEY,
                    access_granted INTEGER NOT NULL DEFAULT 0,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        else:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_users (
                    telegram_id INTEGER PRIMARY KEY,
                    access_granted INTEGER NOT NULL DEFAULT 0,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
        await db.commit()


async def get_or_create_bot_user(telegram_id: int) -> dict:
    tid = int(telegram_id)
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT * FROM bot_users WHERE telegram_id = ?",
            (tid,),
        )
        row = await cur.fetchone()
        if row:
            return row.as_dict()
        await db.execute(
            f"""
            INSERT INTO bot_users (telegram_id, access_granted, is_admin, is_banned, created_at)
            VALUES (?, 0, 0, 0, {now_sql()})
            """,
            (tid,),
        )
        await db.commit()
        cur2 = await db.execute(
            "SELECT * FROM bot_users WHERE telegram_id = ?",
            (tid,),
        )
        r2 = await cur2.fetchone()
        return r2.as_dict() if r2 else {"telegram_id": tid}


async def seed_config_admins(admin_ids: frozenset[int]) -> None:
    for tid in admin_ids:
        await get_or_create_bot_user(int(tid))
        await set_bot_user_flags(
            int(tid),
            access_granted=True,
            is_admin=True,
            is_banned=False,
        )


async def set_bot_user_flags(
    telegram_id: int,
    *,
    access_granted: bool | None = None,
    is_admin: bool | None = None,
    is_banned: bool | None = None,
) -> None:
    tid = int(telegram_id)
    parts: list[str] = []
    vals: list[object] = []
    if access_granted is not None:
        parts.append("access_granted = ?")
        vals.append(1 if access_granted else 0)
    if is_admin is not None:
        parts.append("is_admin = ?")
        vals.append(1 if is_admin else 0)
    if is_banned is not None:
        parts.append("is_banned = ?")
        vals.append(1 if is_banned else 0)
    if not parts:
        return
    vals.append(tid)
    async with db_connect() as db:
        await db.execute(
            f"UPDATE bot_users SET {', '.join(parts)} WHERE telegram_id = ?",
            tuple(vals),
        )
        await db.commit()


async def list_bot_user_ids(*, limit: int = 500) -> list[int]:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT telegram_id FROM bot_users
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        return [int(r[0]) for r in await cur.fetchall()]


async def list_admin_telegram_ids() -> list[int]:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT telegram_id FROM bot_users WHERE is_admin = 1 ORDER BY created_at DESC"
        )
        return [int(r[0]) for r in await cur.fetchall()]


async def count_bot_users() -> int:
    async with db_connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM bot_users")
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def user_stats_for_telegram(telegram_id: int) -> dict:
    tid = int(telegram_id)
    async with db_connect() as db:
        cur_a = await db.execute(
            "SELECT COUNT(*) FROM smtp_accounts WHERE user_id = ?",
            (tid,),
        )
        accounts = int((await cur_a.fetchone())[0])

        cur_v = await db.execute(
            "SELECT COUNT(*) FROM validated_leads WHERE user_id = ?",
            (tid,),
        )
        validated = int((await cur_v.fetchone())[0])

        cur_s = await db.execute(
            """
            SELECT COUNT(*) FROM recipients r
            JOIN campaigns c ON c.id = r.campaign_id
            WHERE c.user_id = ? AND r.status = 'sent'
            """,
            (tid,),
        )
        sent = int((await cur_s.fetchone())[0])

    u = await get_or_create_bot_user(tid)
    has_access = bool(int(u.get("access_granted") or 0)) and not bool(
        int(u.get("is_banned") or 0)
    )
    is_admin = bool(int(u.get("is_admin") or 0))
    return {
        "telegram_id": tid,
        "has_access": has_access,
        "is_admin": is_admin,
        "accounts": accounts,
        "validated": validated,
        "sent": sent,
    }

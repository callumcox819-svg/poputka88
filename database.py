import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "bot.db"


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                is_html INTEGER NOT NULL DEFAULT 0,
                encoding TEXT NOT NULL DEFAULT 'auto',
                status TEXT NOT NULL DEFAULT 'draft',
                total INTEGER NOT NULL DEFAULT 0,
                sent INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                sent_at TEXT,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS smtp_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                sender_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                smtp_host TEXT NOT NULL,
                smtp_port INTEGER NOT NULL DEFAULT 587,
                imap_host TEXT NOT NULL DEFAULT '',
                imap_port INTEGER NOT NULL DEFAULT 993,
                provider TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, email)
            );

            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY,
                send_delay REAL,
                sender_name TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_recipients_campaign
                ON recipients(campaign_id, status);
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, key)
            );

            CREATE INDEX IF NOT EXISTS idx_campaigns_user_status
                ON campaigns(user_id, status);
            """
        )
        await db.commit()
        for stmt in (
            "ALTER TABLE smtp_accounts ADD COLUMN provider TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE user_prefs ADD COLUMN sender_name TEXT NOT NULL DEFAULT ''",
        ):
            try:
                await db.execute(stmt)
                await db.commit()
            except Exception:
                pass


async def create_campaign(
    user_id: int,
    subject: str,
    body: str,
    *,
    is_html: bool,
    encoding: str,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO campaigns (user_id, subject, body, is_html, encoding)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, subject, body, int(is_html), encoding),
        )
        await db.commit()
        return cur.lastrowid or 0


async def add_recipients(campaign_id: int, emails: list[str]) -> int:
    rows = [(campaign_id, e.strip().lower()) for e in emails if e.strip()]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO recipients (campaign_id, email) VALUES (?, ?)",
            rows,
        )
        await db.execute(
            """
            UPDATE campaigns
            SET total = (SELECT COUNT(*) FROM recipients WHERE campaign_id = ?),
                status = 'ready'
            WHERE id = ?
            """,
            (campaign_id, campaign_id),
        )
        await db.commit()
    return len(rows)


async def get_campaign(campaign_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_latest_ready_campaign(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM campaigns
            WHERE user_id = ? AND status IN ('ready', 'draft') AND total > 0
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_running_campaign(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM campaigns
            WHERE user_id = ? AND status = 'running'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def pending_recipients(campaign_id: int, limit: int = 50) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT email FROM recipients
            WHERE campaign_id = ? AND status = 'pending'
            LIMIT ?
            """,
            (campaign_id, limit),
        )
        return [r[0] for r in await cur.fetchall()]


async def mark_sent(campaign_id: int, email: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE recipients SET status = 'sent', sent_at = datetime('now')
            WHERE campaign_id = ? AND email = ?
            """,
            (campaign_id, email),
        )
        await db.execute(
            "UPDATE campaigns SET sent = sent + 1 WHERE id = ?",
            (campaign_id,),
        )
        await db.commit()


async def mark_failed(campaign_id: int, email: str, error: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE recipients SET status = 'failed', error = ?
            WHERE campaign_id = ? AND email = ?
            """,
            (error[:500], campaign_id, email),
        )
        await db.execute(
            "UPDATE campaigns SET failed = failed + 1 WHERE id = ?",
            (campaign_id,),
        )
        await db.commit()


async def set_campaign_status(campaign_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE campaigns SET status = ? WHERE id = ?",
            (status, campaign_id),
        )
        await db.commit()


async def pause_running_campaigns(user_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM campaigns WHERE user_id = ? AND status = 'running'",
            (user_id,),
        )
        ids = [r[0] for r in await cur.fetchall()]
        if ids:
            await db.execute(
                """
                UPDATE campaigns SET status = 'paused'
                WHERE user_id = ? AND status = 'running'
                """,
                (user_id,),
            )
            await db.commit()
        return ids


async def upsert_smtp_account(
    user_id: int,
    *,
    sender_name: str,
    email: str,
    password: str,
    smtp_host: str,
    smtp_port: int,
    imap_host: str,
    imap_port: int,
    provider: str = "",
) -> int:
    email = email.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM smtp_accounts WHERE user_id = ? AND email = ?",
            (user_id, email),
        )
        row = await cur.fetchone()
        if row:
            await db.execute(
                """
                UPDATE smtp_accounts SET
                    sender_name = ?, password = ?, smtp_host = ?, smtp_port = ?,
                    imap_host = ?, imap_port = ?, provider = ?, enabled = 1
                WHERE id = ?
                """,
                (
                    sender_name,
                    password,
                    smtp_host,
                    smtp_port,
                    imap_host,
                    imap_port,
                    provider,
                    row[0],
                ),
            )
            await db.commit()
            return int(row[0])
        cur = await db.execute(
            """
            INSERT INTO smtp_accounts
            (user_id, sender_name, email, password, smtp_host, smtp_port,
             imap_host, imap_port, provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                sender_name,
                email,
                password,
                smtp_host,
                smtp_port,
                imap_host,
                imap_port,
                provider,
            ),
        )
        await db.commit()
        return cur.lastrowid or 0


async def set_user_sender_name(user_id: int, sender_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_prefs (user_id, sender_name) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET sender_name = excluded.sender_name
            """,
            (user_id, sender_name),
        )
        await db.commit()


async def get_user_sender_name(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT sender_name FROM user_prefs WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return (row[0] or "") if row else ""


async def get_last_campaign(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM campaigns WHERE user_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_smtp_accounts(user_id: int, *, with_secrets: bool = False) -> list[dict]:
    cols = (
        "id, sender_name, email, password, smtp_host, smtp_port, imap_host, imap_port, provider, enabled"
        if with_secrets
        else "id, sender_name, email, smtp_host, smtp_port, imap_host, imap_port, provider, enabled"
    )
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"""
            SELECT {cols}
            FROM smtp_accounts WHERE user_id = ? AND enabled = 1
            ORDER BY id
            """,
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_smtp_account(account_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM smtp_accounts WHERE id = ? AND user_id = ?",
            (account_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_smtp_account(user_id: int, account_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM smtp_accounts WHERE id = ? AND user_id = ?",
            (account_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def count_smtp_accounts(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM smtp_accounts WHERE user_id = ? AND enabled = 1",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def get_user_delay(user_id: int, default: float) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT send_delay FROM user_prefs WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return default


async def set_user_delay(user_id: int, delay: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_prefs (user_id, send_delay) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET send_delay = excluded.send_delay
            """,
            (user_id, delay),
        )
        await db.commit()

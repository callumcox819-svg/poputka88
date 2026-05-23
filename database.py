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

            CREATE INDEX IF NOT EXISTS idx_recipients_campaign
                ON recipients(campaign_id, status);
            """
        )
        await db.commit()


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
            "UPDATE campaigns SET total = (SELECT COUNT(*) FROM recipients WHERE campaign_id = ?) WHERE id = ?",
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

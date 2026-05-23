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
            CREATE TABLE IF NOT EXISTS proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                username TEXT,
                password TEXT,
                proxy_type TEXT NOT NULL DEFAULT 'socks5',
                is_active INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_proxies_user ON proxies(user_id);

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, key)
            );

            CREATE INDEX IF NOT EXISTS idx_campaigns_user_status
                ON campaigns(user_id, status);

            CREATE TABLE IF NOT EXISTS validated_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                person_name TEXT NOT NULL DEFAULT '',
                email_local TEXT NOT NULL DEFAULT '',
                email_domain TEXT NOT NULL DEFAULT '',
                item_title TEXT NOT NULL DEFAULT '',
                item_price TEXT NOT NULL DEFAULT '',
                item_link TEXT NOT NULL DEFAULT '',
                person_link TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                item_photo TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, email)
            );

            CREATE INDEX IF NOT EXISTS idx_validated_leads_user
                ON validated_leads(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS incoming_mails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                imap_uid TEXT NOT NULL,
                message_id TEXT NOT NULL DEFAULT '',
                from_email TEXT NOT NULL DEFAULT '',
                from_name TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                lead_id INTEGER,
                campaign_id INTEGER,
                recipient_id INTEGER,
                generated_link TEXT NOT NULL DEFAULT '',
                gag_ad_id TEXT NOT NULL DEFAULT '',
                generation_status TEXT NOT NULL DEFAULT 'pending',
                generation_error TEXT NOT NULL DEFAULT '',
                notified INTEGER NOT NULL DEFAULT 0,
                received_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(account_id, imap_uid),
                FOREIGN KEY (lead_id) REFERENCES validated_leads(id),
                FOREIGN KEY (account_id) REFERENCES smtp_accounts(id)
            );

            CREATE INDEX IF NOT EXISTS idx_incoming_mails_user
                ON incoming_mails(user_id, received_at DESC);

            CREATE TABLE IF NOT EXISTS seller_blacklist (
                user_id INTEGER NOT NULL,
                seller_key TEXT NOT NULL,
                person_name TEXT NOT NULL DEFAULT '',
                validated_email TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, seller_key)
            );

            CREATE INDEX IF NOT EXISTS idx_seller_blacklist_user
                ON seller_blacklist(user_id);
            """
        )
        await db.commit()
        for stmt in (
            "ALTER TABLE smtp_accounts ADD COLUMN provider TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE user_prefs ADD COLUMN sender_name TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE smtp_accounts ADD COLUMN smtp_enabled INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE smtp_accounts ADD COLUMN last_error TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE recipients ADD COLUMN lead_id INTEGER",
            "ALTER TABLE recipients ADD COLUMN generated_link TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE validated_leads ADD COLUMN offer_id INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE validated_leads ADD COLUMN email_norm TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE validated_leads ADD COLUMN seller_key TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE validated_leads ADD COLUMN title_key TEXT NOT NULL DEFAULT ''",
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
    camp = await get_campaign(campaign_id)
    user_id = int(camp["user_id"]) if camp else 0
    rows = [(campaign_id, e.strip().lower()) for e in emails if e.strip()]
    async with aiosqlite.connect(DB_PATH) as db:
        for cid, em in rows:
            lead_id = None
            if user_id:
                cur = await db.execute(
                    "SELECT id FROM validated_leads WHERE user_id = ? AND email = ?",
                    (user_id, em),
                )
                lr = await cur.fetchone()
                if lr:
                    lead_id = int(lr[0])
            await db.execute(
                "INSERT INTO recipients (campaign_id, email, lead_id) VALUES (?, ?, ?)",
                (cid, em, lead_id),
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
    email = email.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id FROM campaigns WHERE id = ?", (campaign_id,)
        )
        camp = await cur.fetchone()
        lead_id = None
        if camp:
            cur = await db.execute(
                "SELECT id FROM validated_leads WHERE user_id = ? AND email = ?",
                (int(camp[0]), email),
            )
            lr = await cur.fetchone()
            if lr:
                lead_id = int(lr[0])
        await db.execute(
            """
            UPDATE recipients SET status = 'sent', sent_at = datetime('now'),
                lead_id = COALESCE(lead_id, ?)
            WHERE campaign_id = ? AND email = ?
            """,
            (lead_id, campaign_id, email),
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
                    imap_host = ?, imap_port = ?, provider = ?, enabled = 1,
                    smtp_enabled = 1, last_error = ''
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


def _smtp_account_cols(*, with_secrets: bool) -> str:
    base = (
        "id, sender_name, email, smtp_host, smtp_port, imap_host, imap_port, "
        "provider, enabled, smtp_enabled, last_error"
    )
    if with_secrets:
        return (
            "id, sender_name, email, password, smtp_host, smtp_port, imap_host, "
            "imap_port, provider, enabled, smtp_enabled, last_error"
        )
    return base


async def list_smtp_accounts(user_id: int, *, with_secrets: bool = False) -> list[dict]:
    """Все активные ящики (IMAP + список в настройках)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"""
            SELECT {_smtp_account_cols(with_secrets=with_secrets)}
            FROM smtp_accounts WHERE user_id = ? AND enabled = 1
            ORDER BY id
            """,
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def list_smtp_mailing_accounts(
    user_id: int, *, with_secrets: bool = False
) -> list[dict]:
    """Ящики, с которых можно слать рассылку (не smtp_blocked)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            f"""
            SELECT {_smtp_account_cols(with_secrets=with_secrets)}
            FROM smtp_accounts
            WHERE user_id = ? AND enabled = 1 AND smtp_enabled = 1
            ORDER BY id
            """,
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def mark_account_smtp_blocked(
    user_id: int, account_id: int, reason: str
) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE smtp_accounts
            SET smtp_enabled = 0, last_error = ?
            WHERE id = ? AND user_id = ? AND enabled = 1 AND smtp_enabled = 1
            """,
            ((reason or "")[:1000], account_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def disable_account_fully(
    user_id: int, account_id: int, reason: str
) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE smtp_accounts
            SET enabled = 0, smtp_enabled = 0, last_error = ?
            WHERE id = ? AND user_id = ?
            """,
            ((reason or "")[:1000], account_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


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


async def count_smtp_mailing_accounts(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM smtp_accounts
            WHERE user_id = ? AND enabled = 1 AND smtp_enabled = 1
            """,
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


async def count_proxies(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM proxies WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def list_proxies(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, host, port, username, password, proxy_type, is_active, last_error, created_at
            FROM proxies WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def list_sendable_proxies(user_id: int) -> list[dict]:
    """SOCKS5 для рассылки: не помечены мёртвыми (is_active != 0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, host, port, username, password, proxy_type, is_active, last_error
            FROM proxies
            WHERE user_id = ? AND (is_active IS NULL OR is_active = 1)
            ORDER BY id
            """,
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def add_proxy(
    user_id: int,
    *,
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    proxy_type: str = "socks5",
    is_active: int | None = None,
    last_error: str | None = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO proxies (user_id, host, port, username, password, proxy_type, is_active, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                host,
                int(port),
                username,
                password,
                proxy_type,
                is_active,
                last_error,
            ),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def update_proxy_status(
    proxy_id: int,
    user_id: int,
    *,
    is_active: int | None,
    last_error: str | None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE proxies SET is_active = ?, last_error = ?
            WHERE id = ? AND user_id = ?
            """,
            (is_active, last_error, proxy_id, user_id),
        )
        await db.commit()


async def delete_proxy(user_id: int, proxy_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM proxies WHERE id = ? AND user_id = ?",
            (proxy_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_all_proxies(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM proxies WHERE user_id = ?", (user_id,))
        await db.commit()
        return int(cur.rowcount or 0)


async def is_seller_blacklisted(user_id: int, seller_dedupe: str) -> bool:
    key = (seller_dedupe or "").strip()
    if not key:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM seller_blacklist WHERE user_id = ? AND seller_key = ?",
            (user_id, key),
        )
        return await cur.fetchone() is not None


async def add_seller_blacklist(
    user_id: int,
    seller_dedupe: str,
    *,
    person_name: str = "",
    validated_email: str = "",
) -> None:
    key = (seller_dedupe or "").strip()
    if not key:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO seller_blacklist (user_id, seller_key, person_name, validated_email)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, seller_key) DO UPDATE SET
                person_name = excluded.person_name,
                validated_email = CASE
                    WHEN excluded.validated_email != '' THEN excluded.validated_email
                    ELSE seller_blacklist.validated_email
                END
            """,
            (
                user_id,
                key,
                (person_name or "").strip(),
                (validated_email or "").strip().lower(),
            ),
        )
        await db.commit()


async def sync_seller_blacklist_from_leads(user_id: int) -> int:
    """Подтянуть в чёрный список уже валидированных продавцов (один раз за прогон)."""
    import json

    from services.void_parser import seller_dedupe_key

    added = 0
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT email, person_name, person_link, raw_json
            FROM validated_leads WHERE user_id = ?
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        for row in rows:
            lead = dict(row)
            item: dict = {}
            raw = (lead.get("raw_json") or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        item = parsed
                except json.JSONDecodeError:
                    pass
            if lead.get("person_link") and not item.get("person_link"):
                item["person_link"] = lead["person_link"]
            if lead.get("person_name") and not item.get("item_person_name"):
                item["item_person_name"] = lead["person_name"]
            dedupe = seller_dedupe_key(item)
            if not dedupe:
                continue
            cur2 = await db.execute(
                "SELECT 1 FROM seller_blacklist WHERE user_id = ? AND seller_key = ?",
                (user_id, dedupe),
            )
            if await cur2.fetchone():
                continue
            await db.execute(
                """
                INSERT INTO seller_blacklist (user_id, seller_key, person_name, validated_email)
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    dedupe,
                    (lead.get("person_name") or "").strip(),
                    (lead.get("email") or "").strip().lower(),
                ),
            )
            added += 1
        await db.commit()
    return added


async def count_seller_blacklist(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM seller_blacklist WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def save_validated_lead(
    user_id: int,
    *,
    email: str,
    person_name: str,
    email_local: str,
    email_domain: str,
    item_title: str = "",
    item_price: str = "",
    item_link: str = "",
    person_link: str = "",
    location: str = "",
    item_photo: str = "",
    raw_json: str,
    offer_id: int = 0,
    email_norm: str = "",
    seller_key: str = "",
    title_key: str = "",
) -> tuple[bool, str]:
    """Возвращает (created, email). created=False если дубликат email."""
    from services.lead_keys import email_norm_key, seller_match_key, title_match_key

    email = email.strip().lower()
    if not email_norm:
        email_norm = email_norm_key(email)
    if not seller_key:
        seller_key = seller_match_key(person_name)
    if not title_key:
        title_key = title_match_key(item_title)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM validated_leads WHERE user_id = ? AND email = ?",
            (user_id, email),
        )
        if await cur.fetchone():
            return False, email
        await db.execute(
            """
            INSERT INTO validated_leads (
                user_id, email, person_name, email_local, email_domain,
                item_title, item_price, item_link, person_link, location,
                item_photo, raw_json, offer_id, email_norm, seller_key, title_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                email,
                person_name,
                email_local,
                email_domain,
                item_title,
                item_price,
                item_link,
                person_link,
                location,
                item_photo,
                raw_json,
                int(offer_id or 0),
                email_norm,
                seller_key,
                title_key,
            ),
        )
        await db.commit()
        return True, email


async def register_validated_seller(
    user_id: int,
    *,
    seller_dedupe: str,
    person_name: str,
    email: str,
) -> None:
    """Глобальный чёрный список продавца после успешной валидации."""
    await add_seller_blacklist(
        user_id,
        seller_dedupe,
        person_name=person_name,
        validated_email=email,
    )


async def count_validated_leads(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM validated_leads WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def list_validated_emails(user_id: int, *, limit: int = 10000) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT email FROM validated_leads WHERE user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return [str(r[0]) for r in await cur.fetchall()]


async def get_validated_lead_by_email(user_id: int, email: str) -> dict | None:
    """Лид по email продавца (тот же, что в рассылке / ответе)."""
    email = email.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? AND email = ?",
            (user_id, email),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_validated_lead_by_id(user_id: int, lead_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? AND id = ?",
            (user_id, lead_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def find_lead_by_exact_email(user_id: int, email: str) -> dict | None:
    return await get_validated_lead_by_email(user_id, email)


async def find_lead_by_email_norm(user_id: int, email_norm: str) -> dict | None:
    norm = (email_norm or "").strip().lower()
    if not norm:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM validated_leads WHERE user_id = ? AND email_norm = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, norm),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC LIMIT 5000",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import email_norm_key

    for row in rows:
        lead = dict(row)
        stored = (lead.get("email_norm") or "").strip()
        if stored and stored == norm:
            return lead
        if email_norm_key(lead.get("email") or "") == norm:
            return lead
    return None


async def find_lead_by_offer_id(user_id: int, offer_id: int) -> dict | None:
    oid = int(offer_id)
    if oid <= 0:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM validated_leads
            WHERE user_id = ? AND offer_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, oid),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import offer_id_from_lead_row

    for row in rows:
        lead = dict(row)
        if int(lead.get("offer_id") or 0) == oid:
            return lead
        if offer_id_from_lead_row(lead) == oid:
            return lead
    return None


async def find_lead_by_title(user_id: int, title_key: str) -> dict | None:
    tkey = (title_key or "").strip()
    if not tkey:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM validated_leads
            WHERE user_id = ? AND title_key = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, tkey),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import title_match_key

    for row in rows:
        lead = dict(row)
        if title_match_key(lead.get("item_title") or "") == tkey:
            return lead
    return None


async def find_lead_by_seller_key(user_id: int, seller_key: str) -> dict | None:
    skey = (seller_key or "").strip().lower()
    if not skey:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM validated_leads
            WHERE user_id = ? AND seller_key = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, skey),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import seller_match_key, seller_names_from_lead

    for row in rows:
        lead = dict(row)
        if (lead.get("seller_key") or "").strip().lower() == skey:
            return lead
        for name in seller_names_from_lead(lead):
            if seller_match_key(name) == skey:
                return lead
    return None


async def save_incoming_gag_link(
    incoming_id: int,
    user_id: int,
    *,
    url: str,
    gag_ad_id: str = "",
    error: str = "",
) -> bool:
    """Сохранить ссылку после кнопки «Создать ссылку» (UI подключим позже)."""
    status = "ok" if url else "error"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE incoming_mails SET
                generated_link = ?,
                gag_ad_id = ?,
                generation_status = ?,
                generation_error = ?
            WHERE id = ? AND user_id = ?
            """,
            (url[:2000], gag_ad_id[:64], status, (error or "")[:500], incoming_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_proxy(proxy_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM proxies WHERE id = ? AND user_id = ?",
            (proxy_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

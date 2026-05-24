from pathlib import Path

from services.db_backend import db_connect, init_db_backend, is_postgres, now_sql
from services.db_init import (
    init_postgres_schema,
    migrate_json_blobs_to_postgres,
    migrate_sqlite_to_postgres_if_needed,
)

DB_PATH = Path(__file__).resolve().parent / "data" / "bot.db"


async def init_db() -> None:
    await init_db_backend()
    if is_postgres():
        await init_postgres_schema()
        await migrate_sqlite_to_postgres_if_needed()
        await migrate_json_blobs_to_postgres()
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with db_connect() as db:
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

            CREATE TABLE IF NOT EXISTS user_blobs (
                user_id INTEGER NOT NULL,
                blob_key TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (user_id, blob_key)
            );
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
            "ALTER TABLE smtp_accounts ADD COLUMN imap_last_uid INTEGER",
            "ALTER TABLE incoming_mails ADD COLUMN body TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE incoming_mails ADD COLUMN account_email TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE incoming_mails ADD COLUMN product_title TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE incoming_mails ADD COLUMN service_label TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE incoming_mails ADD COLUMN photo_url TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE incoming_mails ADD COLUMN offer_price TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE incoming_mails ADD COLUMN tg_chat_id INTEGER",
            "ALTER TABLE incoming_mails ADD COLUMN tg_message_id INTEGER",
            ):
                try:
                    await db.execute(stmt)
                    await db.commit()
                except Exception:
                    pass

    from services.bot_users import ensure_bot_users_table

    await ensure_bot_users_table()


async def create_campaign(
    user_id: int,
    subject: str,
    body: str,
    *,
    is_html: bool,
    encoding: str,
) -> int:
    async with db_connect() as db:
        cur = await db.execute(
            """
            INSERT INTO campaigns (user_id, subject, body, is_html, encoding)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, subject, body, int(is_html), encoding),
        )
        await db.commit()
        return cur.lastrowid or 0


async def add_recipients(
    campaign_id: int, emails: list[str], *, preserve_status: bool = False
) -> int:
    camp = await get_campaign(campaign_id)
    user_id = int(camp["user_id"]) if camp else 0
    rows = [(campaign_id, e.strip().lower()) for e in emails if e.strip()]
    async with db_connect() as db:
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
        if preserve_status:
            await db.execute(
                """
                UPDATE campaigns
                SET total = (SELECT COUNT(*) FROM recipients WHERE campaign_id = ?)
                WHERE id = ?
                """,
                (campaign_id, campaign_id),
            )
        else:
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


async def get_campaign(campaign_id: int, user_id: int | None = None) -> dict | None:
    async with db_connect() as db:
        if user_id is not None:
            cur = await db.execute(
                "SELECT * FROM campaigns WHERE id = ? AND user_id = ?",
                (campaign_id, user_id),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
            )
        row = await cur.fetchone()
        if not row:
            return None
        return row.as_dict()


async def get_user_blob(user_id: int, blob_key: str) -> object | None:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT data FROM user_blobs WHERE user_id = ? AND blob_key = ?",
            (user_id, blob_key),
        )
        row = await cur.fetchone()
        if not row or not row[0]:
            return None
        import json

        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None


async def set_user_blob(user_id: int, blob_key: str, data: object) -> None:
    import json

    payload = json.dumps(data, ensure_ascii=False)
    async with db_connect() as db:
        await db.execute(
            """
            INSERT INTO user_blobs (user_id, blob_key, data) VALUES (?, ?, ?)
            ON CONFLICT(user_id, blob_key) DO UPDATE SET data = excluded.data
            """,
            (user_id, blob_key, payload),
        )
        await db.commit()


async def get_latest_ready_campaign(user_id: int) -> dict | None:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM campaigns
            WHERE user_id = ? AND status IN ('ready', 'draft') AND total > 0
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def append_emails_to_running_campaign(user_id: int, emails: list[str]) -> int:
    """Добавить email в активную рассылку (status=running)."""
    camp = await get_running_campaign(user_id)
    if not camp or not emails:
        return 0
    total = 0
    for em in emails:
        em = (em or "").strip().lower()
        if em:
            total += await add_recipients(
                int(camp["id"]), [em], preserve_status=True
            )
    return total


async def get_running_campaign(user_id: int) -> dict | None:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM campaigns
            WHERE user_id = ? AND status = 'running'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def pending_recipients(campaign_id: int, limit: int = 50) -> list[str]:
    async with db_connect() as db:
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
    async with db_connect() as db:
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
            f"""
            UPDATE recipients SET status = 'sent', sent_at = {now_sql()},
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
    async with db_connect() as db:
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
    async with db_connect() as db:
        await db.execute(
            "UPDATE campaigns SET status = ? WHERE id = ?",
            (status, campaign_id),
        )
        await db.commit()


async def pause_running_campaigns(user_id: int) -> list[int]:
    async with db_connect() as db:
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


async def reset_user_mailing_queue(user_id: int) -> dict[str, int]:
    """
    Обнулить очередь рассылки: удалить все pending-получатели.
    validated_leads и уже отправленные (status=sent) не трогаем.
    """
    stopped_running = await pause_running_campaigns(user_id)
    removed = 0
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT id FROM campaigns WHERE user_id = ?",
            (user_id,),
        )
        campaign_ids = [int(r[0]) for r in await cur.fetchall()]
        for cid in campaign_ids:
            del_cur = await db.execute(
                """
                DELETE FROM recipients
                WHERE campaign_id = ? AND status = 'pending'
                """,
                (cid,),
            )
            removed += int(del_cur.rowcount or 0)
            await db.execute(
                """
                UPDATE campaigns
                SET total = (
                    SELECT COUNT(*) FROM recipients WHERE campaign_id = ?
                )
                WHERE id = ?
                """,
                (cid, cid),
            )
        await db.commit()
    await mark_mailing_queue_reset(user_id)
    return {"removed": removed, "stopped_running": len(stopped_running)}


MAILING_RESET_SINCE_BLOB = "mailing_reset_since"


async def mark_mailing_queue_reset(user_id: int) -> None:
    """После /reset следующий /send берёт только лиды, добавленные в БД после сброса."""
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    await set_user_blob(user_id, MAILING_RESET_SINCE_BLOB, ts)


async def get_mailing_reset_since(user_id: int) -> str | None:
    raw = await get_user_blob(user_id, MAILING_RESET_SINCE_BLOB)
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


async def clear_mailing_reset_since(user_id: int) -> None:
    await set_user_blob(user_id, MAILING_RESET_SINCE_BLOB, None)


def _mailing_since_query_param(since: str) -> str | object:
    """SQLite: строка; PostgreSQL: datetime (asyncpg не принимает str для timestamptz)."""
    if not is_postgres():
        return since
    from datetime import datetime, timezone

    s = since.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s) if "T" in s else datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return since
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def find_lead_by_seller_display_name(
    user_id: int, from_name: str
) -> dict | None:
    """Лид по имени в From (если email в ответе другой)."""
    from services.lead_keys import seller_match_key

    sk = seller_match_key(from_name or "")
    if len(sk) < 4:
        return None
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM validated_leads
            WHERE user_id = ? AND seller_key = ?
            ORDER BY id DESC
            LIMIT 2
            """,
            (user_id, sk),
        )
        rows = [r.as_dict() for r in await cur.fetchall()]
    if len(rows) == 1:
        return rows[0]
    return None


async def find_lead_from_incoming_thread(
    user_id: int, account_id: int, from_email: str
) -> dict | None:
    """Лид с прошлого письма этого продавца на том же ящике."""
    em = (from_email or "").strip().lower()
    if not em or not account_id:
        return None
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT vl.* FROM incoming_mails im
            INNER JOIN validated_leads vl ON vl.id = im.lead_id
            WHERE im.user_id = ? AND im.account_id = ? AND im.from_email = ?
              AND im.lead_id IS NOT NULL
            ORDER BY im.id DESC
            LIMIT 1
            """,
            (user_id, int(account_id), em),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


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
    async with db_connect() as db:
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
    async with db_connect() as db:
        await db.execute(
            """
            INSERT INTO user_prefs (user_id, sender_name) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET sender_name = excluded.sender_name
            """,
            (user_id, sender_name),
        )
        await db.commit()


async def get_user_sender_name(user_id: int) -> str:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT sender_name FROM user_prefs WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return (row[0] or "") if row else ""


async def get_mailing_sender_display(user_id: int) -> str | None:
    """Имя From для массовой рассылки — из smtp_accounts, не из HTML-спуфинга."""
    accounts = await list_smtp_mailing_accounts(user_id)
    if not accounts:
        accounts = await list_smtp_accounts(user_id)
    names: list[str] = []
    seen: set[str] = set()
    for acc in accounts:
        n = (acc.get("sender_name") or "").strip()
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    if not names:
        fallback = (await get_user_sender_name(user_id) or "").strip()
        return fallback or None
    if len(names) == 1:
        return names[0]
    if len(names) <= 3:
        return ", ".join(names)
    return f"{names[0]} (+{len(names) - 1} других)"


async def get_last_campaign(user_id: int) -> dict | None:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM campaigns WHERE user_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def count_total_sent_mails(user_id: int) -> int:
    """Сумма успешно отправленных писем по всем кампаниям."""
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(sent), 0) FROM campaigns WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def get_active_mailing_campaign(user_id: int) -> dict | None:
    """
    Кампания с непустой очередью: running или paused с pending > 0.
    Завершённые (done) без pending — не активны (счётчик в /stat = 0).
    """
    running = await get_running_campaign(user_id)
    if running:
        pending = await count_pending_recipients(int(running["id"]))
        if pending > 0:
            return running
    paused = await get_latest_paused_campaign(user_id)
    if paused:
        pending = await count_pending_recipients(int(paused["id"]))
        if pending > 0:
            return paused
    return None


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
    async with db_connect() as db:
        cur = await db.execute(
            f"""
            SELECT {_smtp_account_cols(with_secrets=with_secrets)}
            FROM smtp_accounts WHERE user_id = ? AND enabled = 1
            ORDER BY id
            """,
            (user_id,),
        )
        return [r.as_dict() for r in await cur.fetchall()]


async def list_smtp_mailing_accounts(
    user_id: int, *, with_secrets: bool = False
) -> list[dict]:
    """Ящики, с которых можно слать рассылку (не smtp_blocked)."""
    async with db_connect() as db:
        cur = await db.execute(
            f"""
            SELECT {_smtp_account_cols(with_secrets=with_secrets)}
            FROM smtp_accounts
            WHERE user_id = ? AND enabled = 1 AND smtp_enabled = 1
            ORDER BY id
            """,
            (user_id,),
        )
        return [r.as_dict() for r in await cur.fetchall()]


async def mark_account_smtp_blocked(
    user_id: int, account_id: int, reason: str
) -> bool:
    async with db_connect() as db:
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


async def toggle_smtp_account_enabled(user_id: int, account_id: int) -> int | None:
    """Переключить enabled (IMAP/ящик в боте). Возвращает новое значение 0/1 или None."""
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT enabled FROM smtp_accounts WHERE id = ? AND user_id = ?",
            (account_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        new_val = 0 if int(row[0] or 0) else 1
        await db.execute(
            """
            UPDATE smtp_accounts
            SET enabled = ?
            WHERE id = ? AND user_id = ?
            """,
            (new_val, account_id, user_id),
        )
        await db.commit()
        return new_val


async def disable_account_fully(
    user_id: int, account_id: int, reason: str
) -> bool:
    async with db_connect() as db:
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
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT * FROM smtp_accounts WHERE id = ? AND user_id = ?",
            (account_id, user_id),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def delete_smtp_account(user_id: int, account_id: int) -> bool:
    async with db_connect() as db:
        cur = await db.execute(
            "DELETE FROM smtp_accounts WHERE id = ? AND user_id = ?",
            (account_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def list_all_smtp_accounts(
    user_id: int, *, with_secrets: bool = False
) -> list[dict]:
    """Все ящики пользователя (включая отключённые)."""
    async with db_connect() as db:
        cur = await db.execute(
            f"""
            SELECT {_smtp_account_cols(with_secrets=with_secrets)}
            FROM smtp_accounts WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        )
        return [r.as_dict() for r in await cur.fetchall()]


async def delete_inactive_smtp_accounts(user_id: int) -> int:
    """Удалить ящики с enabled=0 (неверный пароль / полностью отключены)."""
    async with db_connect() as db:
        cur = await db.execute(
            """
            DELETE FROM smtp_accounts
            WHERE user_id = ? AND enabled = 0
            """,
            (user_id,),
        )
        await db.commit()
        return cur.rowcount or 0


async def delete_all_smtp_accounts(user_id: int) -> int:
    async with db_connect() as db:
        cur = await db.execute(
            "DELETE FROM smtp_accounts WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
        return cur.rowcount or 0


async def count_smtp_accounts(user_id: int) -> int:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM smtp_accounts WHERE user_id = ? AND enabled = 1",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_smtp_mailing_accounts(user_id: int) -> int:
    async with db_connect() as db:
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
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT send_delay FROM user_prefs WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return default


async def set_user_delay(user_id: int, delay: float) -> None:
    async with db_connect() as db:
        await db.execute(
            """
            INSERT INTO user_prefs (user_id, send_delay) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET send_delay = excluded.send_delay
            """,
            (user_id, delay),
        )
        await db.commit()


async def count_proxies(user_id: int) -> int:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM proxies WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def list_proxies(user_id: int) -> list[dict]:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT id, host, port, username, password, proxy_type, is_active, last_error, created_at
            FROM proxies WHERE user_id = ?
            ORDER BY id
            """,
            (user_id,),
        )
        return [r.as_dict() for r in await cur.fetchall()]


async def list_sendable_proxies(user_id: int) -> list[dict]:
    """SOCKS5 для рассылки: не помечены мёртвыми (is_active != 0)."""
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT id, host, port, username, password, proxy_type, is_active, last_error
            FROM proxies
            WHERE user_id = ? AND (is_active IS NULL OR is_active = 1)
            ORDER BY id
            """,
            (user_id,),
        )
        return [r.as_dict() for r in await cur.fetchall()]


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
    async with db_connect() as db:
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
    async with db_connect() as db:
        await db.execute(
            """
            UPDATE proxies SET is_active = ?, last_error = ?
            WHERE id = ? AND user_id = ?
            """,
            (is_active, last_error, proxy_id, user_id),
        )
        await db.commit()


async def delete_proxy(user_id: int, proxy_id: int) -> bool:
    async with db_connect() as db:
        cur = await db.execute(
            "DELETE FROM proxies WHERE id = ? AND user_id = ?",
            (proxy_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_all_proxies(user_id: int) -> int:
    async with db_connect() as db:
        cur = await db.execute("DELETE FROM proxies WHERE user_id = ?", (user_id,))
        await db.commit()
        return int(cur.rowcount or 0)


async def is_seller_blacklisted(user_id: int, seller_dedupe: str) -> bool:
    key = (seller_dedupe or "").strip()
    if not key:
        return False
    async with db_connect() as db:
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
    async with db_connect() as db:
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
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT email, person_name, person_link, raw_json
            FROM validated_leads WHERE user_id = ?
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        for row in rows:
            lead = row.as_dict()
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
    async with db_connect() as db:
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
    created, _lid, em = await upsert_validated_lead(
        user_id,
        email=email,
        person_name=person_name,
        email_local=email_local,
        email_domain=email_domain,
        item_title=item_title,
        item_price=item_price,
        item_link=item_link,
        person_link=person_link,
        location=location,
        item_photo=item_photo,
        raw_json=raw_json,
        offer_id=offer_id,
        email_norm=email_norm,
        seller_key=seller_key,
        title_key=title_key,
    )
    return created, em


async def upsert_validated_lead(
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
) -> tuple[bool, int | None, str]:
    """(created, lead_id, email). Обновляет лид, если email уже есть."""
    from services.lead_keys import email_norm_key, seller_match_key, title_match_key

    email = email.strip().lower()
    if not email_norm:
        email_norm = email_norm_key(email)
    if not seller_key:
        seller_key = seller_match_key(person_name)
    if not title_key:
        title_key = title_match_key(item_title)
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT id FROM validated_leads WHERE user_id = ? AND email = ?",
            (user_id, email),
        )
        row = await cur.fetchone()
        if row:
            lead_id = int(row[0])
            await db.execute(
                """
                UPDATE validated_leads SET
                    person_name = ?, email_local = ?, email_domain = ?,
                    item_title = ?, item_price = ?, item_link = ?,
                    person_link = ?, location = ?, item_photo = ?,
                    raw_json = ?, offer_id = ?, email_norm = ?,
                    seller_key = ?, title_key = ?
                WHERE id = ? AND user_id = ?
                """,
                (
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
                    lead_id,
                    user_id,
                ),
            )
            await db.commit()
            return False, lead_id, email
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
        cur2 = await db.execute(
            "SELECT id FROM validated_leads WHERE user_id = ? AND email = ?",
            (user_id, email),
        )
        row2 = await cur2.fetchone()
        lead_id = int(row2[0]) if row2 else None
        return True, lead_id, email


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
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM validated_leads WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def list_validated_emails(user_id: int, *, limit: int = 10000) -> list[str]:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT email FROM validated_leads WHERE user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return [str(r[0]) for r in await cur.fetchall()]


async def count_already_sent_mailing_emails(user_id: int) -> int:
    """Сколько адресов из validated_leads уже получили письмо (status=sent) в любой кампании."""
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT COUNT(DISTINCT lower(vl.email))
            FROM validated_leads vl
            WHERE vl.user_id = ?
              AND EXISTS (
                SELECT 1 FROM recipients r
                JOIN campaigns c ON c.id = r.campaign_id
                WHERE c.user_id = vl.user_id
                  AND lower(r.email) = lower(vl.email)
                  AND r.status = 'sent'
              )
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def list_validated_emails_pending_mailing(
    user_id: int,
    *,
    limit: int = 10000,
    since_created_at: str | None = None,
) -> list[str]:
    """Email из validated_leads, которым ещё не слали (ни в одной кампании)."""
    since = (since_created_at or "").strip()
    async with db_connect() as db:
        if since:
            since_param = _mailing_since_query_param(since)
            cur = await db.execute(
                """
                SELECT vl.email FROM validated_leads vl
                WHERE vl.user_id = ?
                  AND vl.created_at >= ?
                  AND NOT EXISTS (
                    SELECT 1 FROM recipients r
                    JOIN campaigns c ON c.id = r.campaign_id
                    WHERE c.user_id = vl.user_id
                      AND lower(r.email) = lower(vl.email)
                      AND r.status = 'sent'
                  )
                ORDER BY vl.id DESC
                LIMIT ?
                """,
                (user_id, since_param, limit),
            )
        else:
            cur = await db.execute(
                """
                SELECT vl.email FROM validated_leads vl
                WHERE vl.user_id = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM recipients r
                    JOIN campaigns c ON c.id = r.campaign_id
                    WHERE c.user_id = vl.user_id
                      AND lower(r.email) = lower(vl.email)
                      AND r.status = 'sent'
                  )
                ORDER BY vl.id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        return [str(r[0]) for r in await cur.fetchall()]


async def get_latest_paused_campaign(user_id: int) -> dict | None:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM campaigns
            WHERE user_id = ? AND status = 'paused'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def count_pending_recipients(campaign_id: int) -> int:
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM recipients
            WHERE campaign_id = ? AND status = 'pending'
            """,
            (campaign_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def get_lead_for_mailing_recipient(
    user_id: int,
    contact_email: str,
    *,
    campaign_id: int | None = None,
) -> dict | None:
    """
    Лид, привязанный к рассылке: recipients.lead_id для отправленного письма.
    Это 100% тот товар, который ушёл в кампании.
    """
    email = contact_email.strip().lower()
    if not email:
        return None
    async with db_connect() as db:
        if campaign_id:
            cur = await db.execute(
                """
                SELECT vl.* FROM recipients r
                JOIN campaigns c ON c.id = r.campaign_id
                JOIN validated_leads vl ON vl.id = r.lead_id
                WHERE c.user_id = ? AND r.email = ? AND r.campaign_id = ?
                  AND r.status = 'sent' AND r.lead_id IS NOT NULL
                ORDER BY r.sent_at DESC, r.id DESC
                LIMIT 1
                """,
                (user_id, email, int(campaign_id)),
            )
        else:
            cur = await db.execute(
                """
                SELECT vl.* FROM recipients r
                JOIN campaigns c ON c.id = r.campaign_id
                JOIN validated_leads vl ON vl.id = r.lead_id
                WHERE c.user_id = ? AND r.email = ? AND r.status = 'sent'
                  AND r.lead_id IS NOT NULL
                ORDER BY r.sent_at DESC, r.id DESC
                LIMIT 1
                """,
                (user_id, email),
            )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def get_validated_lead_by_reply_email(
    user_id: int, reply_email: str
) -> dict | None:
    """
    Ответ с другого адреса того же ящика (Maria.Johansen vs MariaJohansen).
    Сопоставление по email_norm валидированной почты, не по названию товара.
    """
    from services.lead_keys import email_norm_key

    norm = email_norm_key(reply_email)
    if not norm:
        return None
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM validated_leads
            WHERE user_id = ? AND email_norm = ?
            LIMIT 2
            """,
            (user_id, norm),
        )
        rows = [r.as_dict() for r in await cur.fetchall()]
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        return None
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ?",
            (user_id,),
        )
        all_rows = await cur.fetchall()
    matches = []
    for row in all_rows:
        lead = row.as_dict()
        if email_norm_key(lead.get("email") or "") == norm:
            matches.append(lead)
    if len(matches) == 1:
        return matches[0]
    return None


async def get_validated_lead_by_email(user_id: int, email: str) -> dict | None:
    """Лид по email продавца (валидированная почта в БД)."""
    email = email.strip().lower()
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? AND email = ?",
            (user_id, email),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def get_validated_lead_by_id(user_id: int, lead_id: int) -> dict | None:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? AND id = ?",
            (user_id, lead_id),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def find_lead_by_exact_email(user_id: int, email: str) -> dict | None:
    return await get_validated_lead_by_email(user_id, email)


async def find_lead_by_email_norm(user_id: int, email_norm: str) -> dict | None:
    norm = (email_norm or "").strip().lower()
    if not norm:
        return None
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM validated_leads WHERE user_id = ? AND email_norm = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, norm),
        )
        row = await cur.fetchone()
        if row:
            return row.as_dict()
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC LIMIT 5000",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import email_norm_key

    for row in rows:
        lead = row.as_dict()
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
    async with db_connect() as db:
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
            return row.as_dict()
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import offer_id_from_lead_row

    for row in rows:
        lead = row.as_dict()
        if int(lead.get("offer_id") or 0) == oid:
            return lead
        if offer_id_from_lead_row(lead) == oid:
            return lead
    return None


async def find_lead_by_title(user_id: int, title_key: str) -> dict | None:
    tkey = (title_key or "").strip()
    if not tkey:
        return None
    async with db_connect() as db:
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
            return row.as_dict()
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import title_match_key

    for row in rows:
        lead = row.as_dict()
        if title_match_key(lead.get("item_title") or "") == tkey:
            return lead
    return None


async def find_lead_by_incoming_subject(user_id: int, subject: str) -> dict | None:
    """Лид по теме Re: <товар> (если email продавца другой или не совпал)."""
    from services.fixture_fields import normalize_incoming_subject
    from services.lead_keys import title_match_key

    needle = normalize_incoming_subject(subject)
    if len(needle) < 4:
        return None

    hit = await find_lead_by_title(user_id, title_match_key(needle))
    if hit:
        return hit

    nl = needle.lower()

    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT * FROM validated_leads
            WHERE user_id = ? ORDER BY id DESC LIMIT 2500
            """,
            (user_id,),
        )
        rows = [r.as_dict() for r in await cur.fetchall()]

    best: dict | None = None
    best_len = 0
    for lead in rows:
        title = (lead.get("item_title") or "").strip()
        if not title or len(title) < 4:
            continue
        tl = title.lower()
        if nl == tl or (len(tl) >= 8 and tl in nl) or (len(nl) >= 8 and nl in tl):
            if len(title) > best_len:
                best = lead
                best_len = len(title)
    return best


async def find_lead_by_recent_mailing(
    user_id: int, *, contact_email: str = "", subject: str = ""
) -> dict | None:
    """Лид из недавней рассылки: email получателя или тема ≈ item_title."""
    from services.fixture_fields import normalize_incoming_subject

    email = (contact_email or "").strip().lower()
    subj_needle = normalize_incoming_subject(subject).lower()

    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT vl.*, r.email AS rcpt_email
            FROM recipients r
            JOIN campaigns c ON c.id = r.campaign_id
            LEFT JOIN validated_leads vl ON vl.id = COALESCE(
                r.lead_id,
                (SELECT id FROM validated_leads
                 WHERE user_id = c.user_id AND email = r.email LIMIT 1)
            )
            WHERE c.user_id = ? AND r.status = 'sent' AND vl.id IS NOT NULL
            ORDER BY r.sent_at DESC, r.id DESC
            LIMIT 400
            """,
            (user_id,),
        )
        rows = [r.as_dict() for r in await cur.fetchall()]

    if email:
        for row in rows:
            rcpt = (row.get("rcpt_email") or "").strip().lower()
            vl_em = (row.get("email") or "").strip().lower()
            if rcpt == email or vl_em == email:
                return {k: v for k, v in row.items() if k != "rcpt_email"}

    if len(subj_needle) >= 4:
        best: dict | None = None
        best_len = 0
        for row in rows:
            title = (row.get("item_title") or "").strip()
            if not title:
                continue
            tl = title.lower()
            if (
                subj_needle == tl
                or (len(tl) >= 8 and tl in subj_needle)
                or (len(subj_needle) >= 8 and subj_needle in tl)
            ):
                if len(title) > best_len:
                    best = {k: v for k, v in row.items() if k != "rcpt_email"}
                    best_len = len(title)
        if best:
            return best
    return None


async def find_lead_by_seller_key(user_id: int, seller_key: str) -> dict | None:
    skey = (seller_key or "").strip().lower()
    if not skey:
        return None
    async with db_connect() as db:
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
            return row.as_dict()
        cur = await db.execute(
            "SELECT * FROM validated_leads WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
    from services.lead_keys import seller_match_key, seller_names_from_lead

    for row in rows:
        lead = row.as_dict()
        if (lead.get("seller_key") or "").strip().lower() == skey:
            return lead
        for name in seller_names_from_lead(lead):
            if seller_match_key(name) == skey:
                return lead
    return None


async def count_imap_poll_accounts_raw() -> dict[str, int]:
    """Диагностика: сколько SMTP в БД и сколько готовы к IMAP."""
    from services.imap_accounts import resolve_imap_account

    async with db_connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM smtp_accounts")
        total = int((await cur.fetchone())[0])
        cur = await db.execute(
            "SELECT COUNT(*) FROM smtp_accounts WHERE enabled = 1"
        )
        enabled = int((await cur.fetchone())[0])
        cur = await db.execute(
            """
            SELECT id, user_id, sender_name, email, password, imap_host, imap_port,
                   imap_last_uid, provider
            FROM smtp_accounts WHERE enabled = 1
            """
        )
        rows = [r.as_dict() for r in await cur.fetchall()]

    with_password = sum(1 for r in rows if (r.get("password") or "").strip())
    pollable = sum(1 for r in rows if resolve_imap_account(r))
    return {
        "total": total,
        "enabled": enabled,
        "with_password": with_password,
        "pollable": pollable,
    }


async def list_imap_poll_accounts() -> list[dict]:
    """Аккаунты для IMAP-воркера (enabled=1; imap_host из БД или по домену email)."""
    from services.imap_accounts import resolve_imap_account

    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT id, user_id, sender_name, email, password, imap_host, imap_port,
                   imap_last_uid, provider
            FROM smtp_accounts
            WHERE enabled = 1
            ORDER BY id
            """
        )
        rows = [r.as_dict() for r in await cur.fetchall()]

    out: list[dict] = []
    for acc in rows:
        resolved = resolve_imap_account(acc)
        if resolved:
            out.append(resolved)
    return out


async def get_imap_last_uid(account_id: int) -> int | None:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT imap_last_uid FROM smtp_accounts WHERE id = ?",
            (account_id,),
        )
        row = await cur.fetchone()
        if not row or row[0] is None:
            return None
        return int(row[0])


async def set_imap_last_uid(account_id: int, uid: int) -> None:
    async with db_connect() as db:
        await db.execute(
            "UPDATE smtp_accounts SET imap_last_uid = ? WHERE id = ?",
            (int(uid), account_id),
        )
        await db.commit()


async def get_incoming_mail_id_by_uid(account_id: int, imap_uid: str) -> int | None:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT id FROM incoming_mails WHERE account_id = ? AND imap_uid = ?",
            (account_id, str(imap_uid)),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def list_incoming_pending_notify(*, limit: int = 80) -> list[dict]:
    """Письма в БД без карточки в Telegram (повторная отправка)."""
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT id, user_id, account_id, from_email, from_name, subject, body,
                   product_title, service_label, photo_url, offer_price, lead_id,
                   account_email
            FROM incoming_mails
            WHERE tg_message_id IS NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        return [r.as_dict() for r in await cur.fetchall()]


async def incoming_mail_exists(account_id: int, imap_uid: str) -> bool:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM incoming_mails WHERE account_id = ? AND imap_uid = ?",
            (account_id, str(imap_uid)),
        )
        return await cur.fetchone() is not None


async def incoming_is_first_from_sender(
    account_id: int, from_email: str, mail_id: int
) -> bool:
    """Первое входящее от продавца на этом ящике (нет более ранних писем с тем же From)."""
    email = (from_email or "").strip().lower()
    if not email or not mail_id:
        return True
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT 1 FROM incoming_mails
            WHERE account_id = ? AND from_email = ? AND id < ?
            LIMIT 1
            """,
            (int(account_id), email, int(mail_id)),
        )
        return await cur.fetchone() is None


async def count_incoming_from_sender(account_id: int, from_email: str) -> int:
    email = from_email.strip().lower()
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM incoming_mails
            WHERE account_id = ? AND from_email = ?
            """,
            (account_id, email),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def insert_incoming_mail(
    user_id: int,
    account_id: int,
    *,
    imap_uid: str,
    message_id: str,
    account_email: str,
    from_email: str,
    from_name: str,
    subject: str,
    body: str,
    lead_id: int | None,
    product_title: str,
    service_label: str,
    photo_url: str,
    offer_price: str,
) -> int:
    async with db_connect() as db:
        cur = await db.execute(
            """
            INSERT INTO incoming_mails (
                user_id, account_id, imap_uid, message_id, account_email,
                from_email, from_name, subject, body, lead_id,
                product_title, service_label, photo_url, offer_price, notified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                user_id,
                account_id,
                str(imap_uid),
                (message_id or "")[:500],
                account_email.strip().lower(),
                from_email.strip().lower(),
                (from_name or "")[:300],
                (subject or "")[:1000],
                body[:50000],
                lead_id,
                (product_title or "")[:500],
                (service_label or "")[:120],
                (photo_url or "")[:2000],
                (offer_price or "")[:80],
            ),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def update_incoming_mail_lead_snapshot(
    incoming_id: int,
    user_id: int,
    *,
    lead_id: int | None,
    product_title: str = "",
    service_label: str = "",
    photo_url: str = "",
    offer_price: str = "",
) -> None:
    async with db_connect() as db:
        await db.execute(
            """
            UPDATE incoming_mails SET
                lead_id = ?,
                product_title = ?,
                service_label = ?,
                photo_url = ?,
                offer_price = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                lead_id,
                (product_title or "")[:500],
                (service_label or "")[:120],
                (photo_url or "")[:2000],
                (offer_price or "")[:80],
                incoming_id,
                user_id,
            ),
        )
        await db.commit()


async def set_incoming_mail_tg_message(
    incoming_id: int, user_id: int, *, chat_id: int, message_id: int
) -> None:
    async with db_connect() as db:
        await db.execute(
            """
            UPDATE incoming_mails SET tg_chat_id = ?, tg_message_id = ?, notified = 1
            WHERE id = ? AND user_id = ?
            """,
            (int(chat_id), int(message_id), incoming_id, user_id),
        )
        await db.commit()


async def get_incoming_thread_reply_message_id(
    account_id: int, from_email: str
) -> int | None:
    """tg_message_id первого письма в цепочке (для reply_to)."""
    email = from_email.strip().lower()
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT tg_message_id FROM incoming_mails
            WHERE account_id = ? AND from_email = ?
              AND tg_message_id IS NOT NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (account_id, email),
        )
        row = await cur.fetchone()
        if row and row[0]:
            return int(row[0])
    return None


async def get_gag_generated_link(
    user_id: int,
    *,
    incoming_id: int | None = None,
    seller_email: str | None = None,
) -> str | None:
    """GAG-ссылка: для письма — только его generated_link; иначе последняя по продавцу."""
    async with db_connect() as db:
        if incoming_id:
            cur = await db.execute(
                """
                SELECT generated_link FROM incoming_mails
                WHERE id = ? AND user_id = ?
                """,
                (int(incoming_id), user_id),
            )
            row = await cur.fetchone()
            link = (row[0] if row else "") or ""
            link = str(link).strip()
            if link:
                return link
        em = (seller_email or "").strip().lower()
        if em:
            cur = await db.execute(
                """
                SELECT generated_link FROM incoming_mails
                WHERE user_id = ? AND from_email = ?
                  AND TRIM(COALESCE(generated_link, '')) != ''
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, em),
            )
            row = await cur.fetchone()
            if row and row[0]:
                return str(row[0]).strip()
    return None


async def inherit_incoming_gag_link(
    incoming_id: int,
    user_id: int,
    from_email: str,
) -> bool:
    """Скопировать GAG-ссылку с предыдущего письма того же продавца на новое."""
    em = (from_email or "").strip().lower()
    if not em or not incoming_id:
        return False
    async with db_connect() as db:
        cur = await db.execute(
            """
            SELECT generated_link, gag_ad_id FROM incoming_mails
            WHERE user_id = ? AND from_email = ? AND id != ?
              AND TRIM(COALESCE(generated_link, '')) != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, em, int(incoming_id)),
        )
        row = await cur.fetchone()
        if not row:
            return False
        prev = row.as_dict() if hasattr(row, "as_dict") else {}
        link = str(prev.get("generated_link") or row[0] or "").strip()
        if not link:
            return False
        ad_id = str(prev.get("gag_ad_id") or "").strip()
        cur2 = await db.execute(
            """
            UPDATE incoming_mails SET
                generated_link = ?,
                gag_ad_id = ?,
                generation_status = 'ok',
                generation_error = ''
            WHERE id = ? AND user_id = ?
              AND TRIM(COALESCE(generated_link, '')) = ''
            """,
            (link[:2000], ad_id[:64], int(incoming_id), user_id),
        )
        await db.commit()
        return bool(cur2.rowcount)


async def get_incoming_mail(incoming_id: int, user_id: int) -> dict | None:
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT * FROM incoming_mails WHERE id = ? AND user_id = ?",
            (incoming_id, user_id),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None


async def propagate_gag_link_for_lead(
    user_id: int,
    *,
    lead_id: int,
    seller_email: str,
    url: str,
    gag_ad_id: str = "",
    offer_price: str = "",
) -> int:
    """Обновить GAG-ссылку и цену на всех входящих письмах этого лида/продавца (для HTML)."""
    link = (url or "").strip()[:2000]
    if not link:
        return 0
    em = (seller_email or "").strip().lower()
    price = (offer_price or "").strip()[:80]
    lid = int(lead_id or 0)
    async with db_connect() as db:
        if lid > 0 and em:
            cur = await db.execute(
                """
                UPDATE incoming_mails SET
                    generated_link = ?,
                    gag_ad_id = ?,
                    generation_status = 'ok',
                    generation_error = '',
                    offer_price = ?
                WHERE user_id = ? AND (lead_id = ? OR from_email = ?)
                """,
                (link, (gag_ad_id or "")[:64], price, user_id, lid, em),
            )
        elif lid > 0:
            cur = await db.execute(
                """
                UPDATE incoming_mails SET
                    generated_link = ?,
                    gag_ad_id = ?,
                    generation_status = 'ok',
                    generation_error = '',
                    offer_price = ?
                WHERE user_id = ? AND lead_id = ?
                """,
                (link, (gag_ad_id or "")[:64], price, user_id, lid),
            )
        elif em:
            cur = await db.execute(
                """
                UPDATE incoming_mails SET
                    generated_link = ?,
                    gag_ad_id = ?,
                    generation_status = 'ok',
                    generation_error = '',
                    offer_price = ?
                WHERE user_id = ? AND from_email = ?
                """,
                (link, (gag_ad_id or "")[:64], price, user_id, em),
            )
        else:
            return 0
        await db.commit()
        return int(cur.rowcount or 0)


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
    async with db_connect() as db:
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
    async with db_connect() as db:
        cur = await db.execute(
            "SELECT * FROM proxies WHERE id = ? AND user_id = ?",
            (proxy_id, user_id),
        )
        row = await cur.fetchone()
        return row.as_dict() if row else None

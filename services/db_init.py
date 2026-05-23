"""Схема PostgreSQL и одноразовая миграция с SQLite / json_blobs."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from services.db_backend import DB_PATH, db_connect, is_postgres
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "json_blobs"

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    is_html INTEGER NOT NULL DEFAULT 0,
    encoding TEXT NOT NULL DEFAULT 'auto',
    status TEXT NOT NULL DEFAULT 'draft',
    total INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS recipients (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    sent_at TIMESTAMPTZ,
    lead_id INTEGER,
    generated_link TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS smtp_accounts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    sender_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL,
    password TEXT NOT NULL,
    smtp_host TEXT NOT NULL,
    smtp_port INTEGER NOT NULL DEFAULT 587,
    imap_host TEXT NOT NULL DEFAULT '',
    imap_port INTEGER NOT NULL DEFAULT 993,
    provider TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    smtp_enabled INTEGER NOT NULL DEFAULT 1,
    last_error TEXT NOT NULL DEFAULT '',
    imap_last_uid BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, email)
);
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id BIGINT PRIMARY KEY,
    send_delay DOUBLE PRECISION,
    sender_name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS proxies (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT,
    password TEXT,
    proxy_type TEXT NOT NULL DEFAULT 'socks5',
    is_active INTEGER,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id BIGINT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS user_blobs (
    user_id BIGINT NOT NULL,
    blob_key TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (user_id, blob_key)
);
CREATE TABLE IF NOT EXISTS validated_leads (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
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
    offer_id INTEGER NOT NULL DEFAULT 0,
    email_norm TEXT NOT NULL DEFAULT '',
    seller_key TEXT NOT NULL DEFAULT '',
    title_key TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, email)
);
CREATE TABLE IF NOT EXISTS incoming_mails (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES smtp_accounts(id),
    imap_uid TEXT NOT NULL,
    message_id TEXT NOT NULL DEFAULT '',
    from_email TEXT NOT NULL DEFAULT '',
    from_name TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    lead_id INTEGER REFERENCES validated_leads(id),
    campaign_id INTEGER,
    recipient_id INTEGER,
    generated_link TEXT NOT NULL DEFAULT '',
    gag_ad_id TEXT NOT NULL DEFAULT '',
    generation_status TEXT NOT NULL DEFAULT 'pending',
    generation_error TEXT NOT NULL DEFAULT '',
    notified INTEGER NOT NULL DEFAULT 0,
    account_email TEXT NOT NULL DEFAULT '',
    product_title TEXT NOT NULL DEFAULT '',
    service_label TEXT NOT NULL DEFAULT '',
    photo_url TEXT NOT NULL DEFAULT '',
    offer_price TEXT NOT NULL DEFAULT '',
    tg_chat_id BIGINT,
    tg_message_id BIGINT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, imap_uid)
);
CREATE TABLE IF NOT EXISTS seller_blacklist (
    user_id BIGINT NOT NULL,
    seller_key TEXT NOT NULL,
    person_name TEXT NOT NULL DEFAULT '',
    validated_email TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, seller_key)
);
CREATE INDEX IF NOT EXISTS idx_recipients_campaign ON recipients(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_proxies_user ON proxies(user_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_user_status ON campaigns(user_id, status);
CREATE INDEX IF NOT EXISTS idx_validated_leads_user ON validated_leads(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incoming_mails_user ON incoming_mails(user_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_seller_blacklist_user ON seller_blacklist(user_id);
"""


async def init_postgres_schema() -> None:
    async with db_connect() as db:
        for stmt in PG_SCHEMA.split(";"):
            s = stmt.strip()
            if s:
                await db.execute(s)
        await db.commit()


async def _pg_count(table: str) -> int:
    async with db_connect() as db:
        cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def migrate_sqlite_to_postgres_if_needed() -> None:
    if not is_postgres() or not DB_PATH.is_file():
        return
    if await _pg_count("user_settings") > 0 or await _pg_count("campaigns") > 0:
        return

    import aiosqlite

    logger.info("Migrating local SQLite -> PostgreSQL")
    async with aiosqlite.connect(DB_PATH) as src:
        src.row_factory = aiosqlite.Row

        async def all_rows(table: str) -> list[dict]:
            try:
                cur = await src.execute(f"SELECT * FROM {table}")
                return [dict(r) for r in await cur.fetchall()]
            except Exception:
                return []

        camp_map: dict[int, int] = {}
        acc_map: dict[int, int] = {}
        lead_map: dict[int, int] = {}

        for r in all_rows("user_settings"):
            async with db_connect() as db:
                await db.execute(
                    """
                    INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?)
                    ON CONFLICT (user_id, key) DO NOTHING
                    """,
                    (r["user_id"], r["key"], r["value"]),
                )
                await db.commit()

        for r in all_rows("user_prefs"):
            async with db_connect() as db:
                await db.execute(
                    """
                    INSERT INTO user_prefs (user_id, send_delay, sender_name)
                    VALUES (?, ?, ?)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (r["user_id"], r.get("send_delay"), r.get("sender_name", "")),
                )
                await db.commit()

        for r in all_rows("campaigns"):
            old = int(r["id"])
            async with db_connect() as db:
                cur = await db.execute(
                    """
                    INSERT INTO campaigns (user_id, subject, body, is_html, encoding,
                        status, total, sent, failed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["user_id"],
                        r["subject"],
                        r["body"],
                        r["is_html"],
                        r["encoding"],
                        r["status"],
                        r["total"],
                        r["sent"],
                        r["failed"],
                        r.get("created_at"),
                    ),
                )
                if cur.lastrowid:
                    camp_map[old] = int(cur.lastrowid)

        for r in all_rows("smtp_accounts"):
            old = int(r["id"])
            async with db_connect() as db:
                cur = await db.execute(
                    """
                    INSERT INTO smtp_accounts (
                        user_id, sender_name, email, password, smtp_host, smtp_port,
                        imap_host, imap_port, provider, enabled, smtp_enabled, last_error,
                        imap_last_uid, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["user_id"],
                        r.get("sender_name", ""),
                        r["email"],
                        r["password"],
                        r["smtp_host"],
                        r["smtp_port"],
                        r.get("imap_host", ""),
                        r.get("imap_port", 993),
                        r.get("provider", ""),
                        r.get("enabled", 1),
                        r.get("smtp_enabled", 1),
                        r.get("last_error", ""),
                        r.get("imap_last_uid"),
                        r.get("created_at"),
                    ),
                )
                if cur.lastrowid:
                    acc_map[old] = int(cur.lastrowid)

        for r in all_rows("proxies"):
            async with db_connect() as db:
                await db.execute(
                    """
                    INSERT INTO proxies (user_id, host, port, username, password,
                        proxy_type, is_active, last_error, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["user_id"],
                        r["host"],
                        r["port"],
                        r.get("username"),
                        r.get("password"),
                        r.get("proxy_type", "socks5"),
                        r.get("is_active"),
                        r.get("last_error"),
                        r.get("created_at"),
                    ),
                )
                await db.commit()

        for r in all_rows("validated_leads"):
            old = int(r["id"])
            async with db_connect() as db:
                cur = await db.execute(
                    """
                    INSERT INTO validated_leads (
                        user_id, email, person_name, email_local, email_domain,
                        item_title, item_price, item_link, person_link, location,
                        item_photo, raw_json, offer_id, email_norm, seller_key, title_key,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["user_id"],
                        r["email"],
                        r.get("person_name", ""),
                        r.get("email_local", ""),
                        r.get("email_domain", ""),
                        r.get("item_title", ""),
                        r.get("item_price", ""),
                        r.get("item_link", ""),
                        r.get("person_link", ""),
                        r.get("location", ""),
                        r.get("item_photo", ""),
                        r["raw_json"],
                        r.get("offer_id", 0),
                        r.get("email_norm", ""),
                        r.get("seller_key", ""),
                        r.get("title_key", ""),
                        r.get("created_at"),
                    ),
                )
                if cur.lastrowid:
                    lead_map[old] = int(cur.lastrowid)

        for r in all_rows("recipients"):
            cid = camp_map.get(int(r["campaign_id"]))
            if not cid:
                continue
            lid = r.get("lead_id")
            if lid:
                lid = lead_map.get(int(lid))
            async with db_connect() as db:
                await db.execute(
                    """
                    INSERT INTO recipients (campaign_id, email, status, error, sent_at,
                        lead_id, generated_link)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        r["email"],
                        r.get("status", "pending"),
                        r.get("error"),
                        r.get("sent_at"),
                        lid,
                        r.get("generated_link", ""),
                    ),
                )
                await db.commit()

        for r in all_rows("seller_blacklist"):
            async with db_connect() as db:
                await db.execute(
                    """
                    INSERT INTO seller_blacklist (user_id, seller_key, person_name,
                        validated_email, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (user_id, seller_key) DO NOTHING
                    """,
                    (
                        r["user_id"],
                        r["seller_key"],
                        r.get("person_name", ""),
                        r.get("validated_email", ""),
                        r.get("created_at"),
                    ),
                )
                await db.commit()

        for r in all_rows("incoming_mails"):
            aid = acc_map.get(int(r["account_id"]))
            if not aid:
                continue
            lid = r.get("lead_id")
            if lid:
                lid = lead_map.get(int(lid))
            async with db_connect() as db:
                await db.execute(
                    """
                    INSERT INTO incoming_mails (
                        user_id, account_id, imap_uid, message_id, from_email, from_name,
                        subject, body, lead_id, campaign_id, recipient_id, generated_link,
                        gag_ad_id, generation_status, generation_error, notified,
                        account_email, product_title, service_label, photo_url, offer_price,
                        tg_chat_id, tg_message_id, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (account_id, imap_uid) DO NOTHING
                    """,
                    (
                        r["user_id"],
                        aid,
                        r["imap_uid"],
                        r.get("message_id", ""),
                        r.get("from_email", ""),
                        r.get("from_name", ""),
                        r.get("subject", ""),
                        r.get("body", ""),
                        lid,
                        r.get("campaign_id"),
                        r.get("recipient_id"),
                        r.get("generated_link", ""),
                        r.get("gag_ad_id", ""),
                        r.get("generation_status", "pending"),
                        r.get("generation_error", ""),
                        r.get("notified", 0),
                        r.get("account_email", ""),
                        r.get("product_title", ""),
                        r.get("service_label", ""),
                        r.get("photo_url", ""),
                        r.get("offer_price", ""),
                        r.get("tg_chat_id"),
                        r.get("tg_message_id"),
                        r.get("received_at"),
                    ),
                )
                await db.commit()

    await migrate_json_blobs_to_postgres()
    logger.info("SQLite -> PostgreSQL migration finished")


async def migrate_json_blobs_to_postgres() -> None:
    if not is_postgres() or not DATA_DIR.is_dir():
        return
    for user_dir in DATA_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        try:
            uid = int(user_dir.name)
        except ValueError:
            continue
        for path in user_dir.glob("*.json"):
            key = path.stem
            try:
                payload = path.read_text(encoding="utf-8")
                json.loads(payload)
            except Exception:
                continue
            async with db_connect() as db:
                await db.execute(
                    """
                    INSERT INTO user_blobs (user_id, blob_key, data)
                    VALUES (?, ?, ?)
                    ON CONFLICT (user_id, blob_key) DO NOTHING
                    """,
                    (uid, key, payload),
                )
                await db.commit()

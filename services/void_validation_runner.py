"""Проверка объявлений void-parser через ValidEmail."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from config import Settings
from database import (
    is_seller_blacklisted,
    register_validated_seller,
    save_validated_lead,
    sync_seller_blacklist_from_leads,
)
from services.domain_list import get_validation_domains
from services.lead_keys import (
    email_norm_key,
    offer_id_from_item,
    seller_match_key,
    title_match_key,
)
from services.seller_name import (
    display_local,
    make_email_local,
    seller_name_eligible,
    seller_name_from_item,
)
from services.task_control import should_stop_validation
from services.validemail_pool import ValidemailKeyPool, find_deliverable_email
from services.void_parser import seller_dedupe_key

if TYPE_CHECKING:
    from services.validation_session import ValidationSession

logger = logging.getLogger(__name__)


@dataclass
class ValidemailWorkerContext:
    pool: ValidemailKeyPool
    domains: list[str]
    per_key: int
    keys_line: str

    @classmethod
    async def create(cls, settings: Settings, user_id: int) -> ValidemailWorkerContext | None:
        api_keys = list(settings.validemail_api_keys)
        if not api_keys:
            return None
        domains = await get_validation_domains(user_id)
        if not domains:
            return None
        per_key = max(2, settings.validemail_concurrency)
        try:
            pool = ValidemailKeyPool(
                api_keys,
                url=settings.validemail_url,
                timeout_sec=settings.validemail_timeout,
                concurrency_per_key=per_key,
            )
        except ValueError:
            return None
        keys_line = (
            f"🔑 Ключей API: <b>{pool.key_count}</b> · "
            f"до <b>{pool.key_count * per_key}</b> запросов"
        )
        return cls(pool=pool, domains=domains, per_key=per_key, keys_line=keys_line)


def _enrich_export_item(item: dict[str, Any], email: str) -> dict[str, Any]:
    row = dict(item)
    row["validated_email"] = email
    row["validated_emails"] = [email]
    return row


async def process_validation_item(
    item: dict[str, Any],
    *,
    ctx: ValidemailWorkerContext,
    session: ValidationSession,
    settings: Settings,
) -> None:
    from database import append_emails_to_running_campaign
    from services.validation_session import ValidationSession as VS

    assert isinstance(session, VS)
    stats = session.stats

    if stats.stopped or should_stop_validation(session.user_id):
        stats.stopped = True
        return

    async with session.lock:
        stats.processed += 1

    name = seller_name_from_item(item)
    if not seller_name_eligible(name):
        async with session.lock:
            stats.short += 1
        return

    dedupe = seller_dedupe_key(item)
    if dedupe and await is_seller_blacklisted(session.user_id, dedupe):
        async with session.lock:
            stats.blacklist += 1
        return

    async with session.lock:
        if dedupe and dedupe in session.batch_seen_sellers:
            stats.dup_seller += 1
            return

    local = make_email_local(name)
    if not local:
        async with session.lock:
            stats.short += 1
        return

    found_email, found_domain, fatal = await find_deliverable_email(
        ctx.pool, local, ctx.domains
    )

    if fatal:
        async with session.lock:
            stats.errors += 1
            stats.fatal_reason = fatal
            stats.stopped = True
        return

    if found_email:
        raw_json = json.dumps(item, ensure_ascii=False)
        ititle = str(item.get("item_title") or item.get("title") or "")
        created, _ = await save_validated_lead(
            session.user_id,
            email=found_email,
            person_name=name,
            email_local=local,
            email_domain=found_domain or "",
            item_title=ititle,
            item_price=str(item.get("item_price") or item.get("price") or ""),
            item_link=str(item.get("item_link") or item.get("link") or ""),
            person_link=str(item.get("person_link") or ""),
            location=str(item.get("location") or ""),
            item_photo=str(item.get("item_photo") or ""),
            raw_json=raw_json,
            offer_id=int(offer_id_from_item(item) or 0),
            email_norm=email_norm_key(found_email),
            seller_key=seller_match_key(name),
            title_key=title_match_key(ititle),
        )
        if dedupe:
            await register_validated_seller(
                session.user_id,
                seller_dedupe=dedupe,
                person_name=name,
                email=found_email,
            )
        n_mail = 0
        if created:
            n_mail = await append_emails_to_running_campaign(
                session.user_id, [found_email]
            )
        async with session.lock:
            if created:
                stats.added += 1
                session.export_rows.append(_enrich_export_item(item, found_email))
                stats.mailing_added += n_mail
            else:
                stats.duplicates += 1
            if dedupe:
                session.batch_seen_sellers.add(dedupe)
        logger.info("valid lead %s -> %s", display_local(name), found_email)
    else:
        async with session.lock:
            stats.no_email += 1


async def run_void_validation(
    bot,
    settings: Settings,
    user_id: int,
    chat_id: int,
    items: list[dict[str, Any]],
    *,
    status_message_id: int | None = None,
    username: str = "",
) -> None:
    """Совместимость: делегирует в сессию с очередью."""
    from services.validation_session import enqueue_void_validation

    await sync_seller_blacklist_from_leads(user_id)
    msg = await enqueue_void_validation(
        bot,
        settings,
        user_id=user_id,
        chat_id=chat_id,
        items=items,
        username=username,
        status_message_id=status_message_id,
    )
    if status_message_id:
        try:
            await bot.edit_message_text(
                msg,
                chat_id=chat_id,
                message_id=status_message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass
    elif "➕" not in msg:
        await bot.send_message(chat_id, msg, parse_mode="HTML")


def stop_void_validation(user_id: int) -> bool:
    from services.validation_session import stop_void_validation as _stop

    return _stop(user_id)

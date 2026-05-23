"""Валидация void-parser JSON через ValidEmail (несколько API-ключей)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot

from config import Settings
from database import (
    is_seller_blacklisted,
    register_validated_seller,
    save_validated_lead,
    sync_seller_blacklist_from_leads,
)
from services.domain_list import get_validation_domains
from services.seller_name import (
    display_local,
    make_email_local,
    seller_name_eligible,
    seller_name_from_item,
)
from services.task_control import clear_stop_validation, should_stop_validation
from services.validemail_pool import ValidemailKeyPool, find_deliverable_email
from services.lead_keys import email_norm_key, offer_id_from_item, seller_match_key, title_match_key
from services.void_parser import seller_dedupe_key

logger = logging.getLogger(__name__)

_active_users: set[int] = set()
PROGRESS_EVERY = 40


def _progress_bar(done: int, total: int, width: int = 18) -> str:
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, int(done / total * width)))
    return "█" * filled + "░" * (width - filled)


def _split_items_round_robin(
    items: list[dict[str, Any]], n: int
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = [[] for _ in range(n)]
    for i, item in enumerate(items):
        chunks[i % n].append(item)
    return chunks


@dataclass
class _SharedStats:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    processed: int = 0
    skipped_short: int = 0
    skipped_dup_seller: int = 0
    skipped_blacklist: int = 0
    no_valid: int = 0
    saved: int = 0
    errors: int = 0
    batch_seen_sellers: set[str] = field(default_factory=set)
    stopped: bool = False
    fatal_reason: str | None = None


async def _process_items_chunk(
    items: list[dict[str, Any]],
    *,
    pool: ValidemailKeyPool,
    domains: list[str],
    user_id: int,
    settings: Settings,
    stats: _SharedStats,
    total: int,
    on_progress,
) -> None:
    for item in items:
        if stats.stopped or should_stop_validation(user_id):
            stats.stopped = True
            break

        async with stats.lock:
            stats.processed += 1
            processed = stats.processed

        name = seller_name_from_item(item)
        if not seller_name_eligible(name):
            async with stats.lock:
                stats.skipped_short += 1
            if processed % PROGRESS_EVERY == 0:
                await on_progress()
            continue

        dedupe = seller_dedupe_key(item)
        if dedupe and await is_seller_blacklisted(user_id, dedupe):
            async with stats.lock:
                stats.skipped_blacklist += 1
            if processed % PROGRESS_EVERY == 0:
                await on_progress()
            continue

        async with stats.lock:
            if dedupe and dedupe in stats.batch_seen_sellers:
                stats.skipped_dup_seller += 1
                if processed % PROGRESS_EVERY == 0:
                    await on_progress()
                continue

        local = make_email_local(name)
        if not local:
            async with stats.lock:
                stats.skipped_short += 1
            continue

        found_email, found_domain, fatal = await find_deliverable_email(
            pool, local, domains
        )

        if fatal:
            async with stats.lock:
                stats.errors += 1
                stats.fatal_reason = fatal
                stats.stopped = True
            break

        if found_email:
            raw_json = json.dumps(item, ensure_ascii=False)
            ititle = str(item.get("item_title") or item.get("title") or "")
            created, _ = await save_validated_lead(
                user_id,
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
                    user_id,
                    seller_dedupe=dedupe,
                    person_name=name,
                    email=found_email,
                )
            async with stats.lock:
                if created:
                    stats.saved += 1
                if dedupe:
                    stats.batch_seen_sellers.add(dedupe)
            logger.info("valid lead %s -> %s", display_local(name), found_email)
        else:
            async with stats.lock:
                stats.no_valid += 1

        if processed % PROGRESS_EVERY == 0:
            await on_progress()


def stop_void_validation(user_id: int) -> bool:
    if user_id not in _active_users:
        return False
    from services.task_control import request_stop_validation

    request_stop_validation(user_id)
    return True


async def run_void_validation(
    bot: Bot,
    settings: Settings,
    user_id: int,
    chat_id: int,
    items: list[dict[str, Any]],
    *,
    status_message_id: int | None = None,
) -> None:
    if user_id in _active_users:
        await bot.send_message(chat_id, "Валидация уже идёт. /stopcheck — остановить.")
        return

    api_keys = list(settings.validemail_api_keys)
    if not api_keys:
        await bot.send_message(
            chat_id,
            "❌ Задайте <code>VALIDEMAIL_API_KEY</code> и "
            "<code>VALIDEMAIL_API_KEY_2</code> в <code>config.py</code> (вверху файла)",
            parse_mode="HTML",
        )
        return

    domains = await get_validation_domains(user_id)
    if not domains:
        await bot.send_message(
            chat_id,
            "❌ Список доменов пуст.\n"
            "⚙️ Настройки → 📊 Приоритет отправки — добавьте домены.",
        )
        return

    if not items:
        await bot.send_message(chat_id, "В JSON нет объявлений (items).")
        return

    _active_users.add(user_id)
    clear_stop_validation(user_id)

    await sync_seller_blacklist_from_leads(user_id)

    total = len(items)
    stats = _SharedStats()
    last_edit = 0.0
    per_key = max(2, settings.validemail_concurrency)

    try:
        pool = ValidemailKeyPool(
            api_keys,
            url=settings.validemail_url,
            timeout_sec=settings.validemail_timeout,
            concurrency_per_key=per_key,
        )
    except ValueError:
        await bot.send_message(chat_id, "❌ Нет API-ключей ValidEmail.")
        _active_users.discard(user_id)
        return

    async def _status(finished: bool = False) -> str:
        async with stats.lock:
            processed = stats.processed
            saved = stats.saved
            no_valid = stats.no_valid
            skipped_short = stats.skipped_short
            skipped_dup = stats.skipped_dup_seller
            skipped_bl = stats.skipped_blacklist
            errors = stats.errors
            stopped = stats.stopped

        bar = _progress_bar(processed, total)
        pct = int(processed / total * 100) if total else 0
        title = "✅ Валидация завершена" if finished else "🔎 Валидация JSON…"
        if finished and stopped:
            title = "⏹ Валидация остановлена"
        keys_line = (
            f"🔑 Ключей API: <b>{pool.key_count}</b> · "
            f"параллельно до <b>{pool.key_count * per_key}</b> запросов"
        )
        return (
            f"<b>{title}</b>\n"
            f"{keys_line}\n"
            f"<code>{bar}</code> <b>{pct}%</b>\n\n"
            f"📄 Объявлений: <b>{processed}/{total}</b>\n"
            f"✅ Сохранено email: <b>{saved}</b>\n"
            f"📭 Без валидного email: <b>{no_valid}</b>\n"
            f"✂️ Короткое имя: <b>{skipped_short}</b>\n"
            f"♻️ Повтор в файле: <b>{skipped_dup}</b>\n"
            f"🚫 Чёрный список (уже валидирован): <b>{skipped_bl}</b>\n"
            f"⚠️ Ошибок API: <b>{errors}</b>\n"
            f"🌐 Доменов: <b>{len(domains)}</b>"
        )

    status_msg_id = status_message_id

    async def _edit_status(finished: bool = False) -> None:
        nonlocal last_edit, status_msg_id
        if not status_msg_id:
            return
        now = time.monotonic()
        if not finished and now - last_edit < 2.0:
            return
        last_edit = now
        try:
            await bot.edit_message_text(
                await _status(finished),
                chat_id=chat_id,
                message_id=status_msg_id,
                parse_mode="HTML",
            )
        except Exception:
            pass

    async def on_progress() -> None:
        await _edit_status()

    try:
        if not status_msg_id:
            msg = await bot.send_message(
                chat_id, await _status(), parse_mode="HTML"
            )
            status_msg_id = msg.message_id

        chunks = _split_items_round_robin(items, pool.key_count)
        workers = [
            _process_items_chunk(
                chunk,
                pool=pool,
                domains=domains,
                user_id=user_id,
                settings=settings,
                stats=stats,
                total=total,
                on_progress=on_progress,
            )
            for chunk in chunks
            if chunk
        ]
        await asyncio.gather(*workers)

        await _edit_status(finished=True)

        if stats.fatal_reason:
            await bot.send_message(
                chat_id,
                f"❌ ValidEmail: <code>{stats.fatal_reason}</code>",
                parse_mode="HTML",
            )
        elif stats.saved and not stats.stopped:
            await bot.send_message(
                chat_id,
                f"💾 Сохранено <b>{stats.saved}</b> продавцов с email "
                f"(ключей: {pool.key_count}).",
                parse_mode="HTML",
            )
    except Exception:
        logger.exception("void validation failed user_id=%s", user_id)
        await bot.send_message(chat_id, "❌ Ошибка валидации. Смотрите логи.")
    finally:
        _active_users.discard(user_id)
        clear_stop_validation(user_id)

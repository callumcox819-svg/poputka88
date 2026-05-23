"""Проверка списка готовых email через ValidEmail (несколько ключей)."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from config import Settings
from services.task_control import (
    clear_stop_validation,
    should_stop_validation,
)
from services.validemail_pool import ValidemailKeyPool
from utils.email_list import parse_emails

logger = logging.getLogger(__name__)

_active_users: set[int] = set()


def stop_validation(user_id: int) -> bool:
    if user_id not in _active_users:
        return False
    from services.task_control import request_stop_validation

    request_stop_validation(user_id)
    return True


def _split_round_robin(items: list[str], n: int) -> list[list[str]]:
    chunks: list[list[str]] = [[] for _ in range(n)]
    for i, x in enumerate(items):
        chunks[i % n].append(x)
    return chunks


async def run_email_list_validation(
    bot: Bot,
    settings: Settings,
    user_id: int,
    chat_id: int,
    text: str,
) -> None:
    if user_id in _active_users:
        await bot.send_message(chat_id, "Проверка уже идёт. /stopcheck — остановить.")
        return

    api_keys = list(settings.validemail_api_keys)
    if not api_keys:
        await bot.send_message(
            chat_id,
            "❌ Задайте VALIDEMAIL_API_KEY и VALIDEMAIL_API_KEY_2 в config.py",
            parse_mode="HTML",
        )
        return

    emails = parse_emails(text)
    if not emails:
        await bot.send_message(chat_id, "Не найдено email для проверки.")
        return

    _active_users.add(user_id)
    clear_stop_validation(user_id)

    valid: list[str] = []
    invalid: list[tuple[str, str]] = []
    lock = asyncio.Lock()
    per_key = max(2, settings.validemail_concurrency)

    try:
        pool = ValidemailKeyPool(
            api_keys,
            url=settings.validemail_url,
            timeout_sec=settings.validemail_timeout,
            concurrency_per_key=per_key,
        )
        await bot.send_message(
            chat_id,
            f"Проверка {len(emails)} адресов · ключей: {pool.key_count}…",
        )

        async def _check_one(email: str) -> None:
            if should_stop_validation(user_id):
                return
            ok, reason, _ = await pool.validate(email)
            async with lock:
                if ok:
                    valid.append(email)
                else:
                    invalid.append((email, reason))

        chunks = _split_round_robin(emails, pool.key_count)

        async def _chunk_worker(chunk: list[str]) -> None:
            for email in chunk:
                if should_stop_validation(user_id):
                    return
                await _check_one(email)

        await asyncio.gather(*[_chunk_worker(c) for c in chunks if c])

        lines = [
            f"Готово. Валидных: {len(valid)}, невалидных: {len(invalid)}.",
        ]
        if valid[:20]:
            lines.append("\n✅ Примеры:\n" + "\n".join(valid[:20]))
        if invalid[:15]:
            lines.append(
                "\n❌ Невалидные:\n"
                + "\n".join(f"{e} — {r}" for e, r in invalid[:15])
            )
        await bot.send_message(chat_id, "\n".join(lines))
    finally:
        _active_users.discard(user_id)
        clear_stop_validation(user_id)

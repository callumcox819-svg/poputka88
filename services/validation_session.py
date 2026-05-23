"""Сессия валидации JSON: очередь, живой статус, накопление, файл результата."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile

from config import Settings
from services.task_control import clear_stop_validation, should_stop_validation
from services.void_validation_runner import (
    ValidemailWorkerContext,
    process_validation_item,
)

logger = logging.getLogger(__name__)

PROGRESS_EDIT_SEC = 3.0
_sessions: dict[int, ValidationSession] = {}


def _progress_bar(done: int, total: int, width: int = 20) -> tuple[str, int]:
    if total <= 0:
        return "░" * width, 0
    pct = int(done / total * 100)
    filled = max(0, min(width, int(done / total * width)))
    return "█" * filled + "░" * (width - filled), pct


@dataclass
class SessionStats:
    total: int = 0
    processed: int = 0
    added: int = 0
    duplicates: int = 0
    dup_seller: int = 0
    blacklist: int = 0
    short: int = 0
    no_email: int = 0
    errors: int = 0
    mailing_added: int = 0
    stopped: bool = False
    fatal_reason: str | None = None


@dataclass
class ValidationSession:
    user_id: int
    chat_id: int
    username: str
    stats: SessionStats = field(default_factory=SessionStats)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    status_message_id: int | None = None
    export_rows: list[dict[str, Any]] = field(default_factory=list)
    batch_seen_sellers: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    worker_task: asyncio.Task | None = None
    updater_task: asyncio.Task | None = None
    stop_updater: asyncio.Event = field(default_factory=asyncio.Event)
    last_ui_text: str = ""
    keys_line: str = ""


def _user_line(session: ValidationSession) -> str:
    un = f"@{session.username}" if session.username else ""
    return f"👤 <code>{session.user_id}</code> {un}".strip()


def format_status(session: ValidationSession, *, finished: bool = False) -> str:
    s = session.stats
    bar, pct = _progress_bar(s.processed, s.total)
    if finished and s.stopped:
        title = "⏹ Подбор остановлен (/stopcheck)"
    elif finished:
        title = "✅ Подбор завершён"
    else:
        title = "🔎 Подбор email…"

    lines = [
        f"<b>{title}</b>",
        _user_line(session),
        f"<code>{bar}</code> <b>{pct}%</b>",
        "",
        f"📄 Объявлений обработано: <b>{s.processed}/{s.total}</b>",
        f"📧 Добавлено: <b>{s.added}</b>",
        f"♻️ Дубликатов: <b>{s.dup_seller + s.duplicates}</b>",
        f"⛔ Повтор продавца (пропуск): <b>{s.blacklist}</b>",
        f"✂️ Коротких ников: <b>{s.short}</b>",
        f"📬 Без email: <b>{s.no_email}</b>",
        f"⚠️ Ошибок: <b>{s.errors}</b>",
    ]
    if session.keys_line:
        lines.insert(2, session.keys_line)
    if s.mailing_added > 0:
        lines.append(f"📨 В рассылку добавлено: <b>{s.mailing_added}</b>")
    return "\n".join(lines)


async def _edit_status(bot: Bot, session: ValidationSession, *, finished: bool = False) -> None:
    if not session.status_message_id:
        return
    text = format_status(session, finished=finished)
    if text == session.last_ui_text and not finished:
        return
    try:
        await bot.edit_message_text(
            text,
            chat_id=session.chat_id,
            message_id=session.status_message_id,
            parse_mode="HTML",
        )
        session.last_ui_text = text
    except Exception:
        pass


def _drain_validation_queue(session: ValidationSession) -> int:
    """Снять необработанные объявления с очереди (иначе queue.join() зависает навсегда)."""
    dropped = 0
    while True:
        try:
            session.queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        session.queue.task_done()
        dropped += 1
    return dropped


async def _progress_updater(bot: Bot, session: ValidationSession) -> None:
    while not session.stop_updater.is_set():
        await _edit_status(bot, session, finished=False)
        await asyncio.sleep(PROGRESS_EDIT_SEC)
    await _edit_status(bot, session, finished=False)


async def _send_export_file(bot: Bot, session: ValidationSession, *, stopped: bool) -> None:
    if not session.export_rows:
        return
    out_path = os.path.join(
        tempfile.gettempdir(),
        f"validated_{session.user_id}_{int(time.time())}.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(session.export_rows, f, ensure_ascii=False, indent=2)

    s = session.stats
    stop_note = " · остановлено" if stopped else ""
    mail_note = ""
    if s.mailing_added > 0:
        mail_note = f" · ➕ в рассылку {s.mailing_added}"
    try:
        await bot.send_document(
            session.chat_id,
            FSInputFile(out_path),
            caption=(
                f"📎 Результат · в БД {s.added} email · обработано {s.processed}/{s.total}"
                f"{stop_note}{mail_note}"
            ),
        )
    except Exception:
        logger.exception("send validated json failed")
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


async def _worker(bot: Bot, settings: Settings, session: ValidationSession) -> None:
    try:
        ctx = await ValidemailWorkerContext.create(settings, session.user_id)
        if not ctx:
            await bot.send_message(session.chat_id, "❌ Нет ключей ValidEmail или доменов.")
            return
        session.keys_line = ctx.keys_line

        if not session.status_message_id:
            msg = await bot.send_message(
                session.chat_id,
                format_status(session),
                parse_mode="HTML",
            )
            session.status_message_id = msg.message_id

        session.stop_updater.clear()
        session.updater_task = asyncio.create_task(_progress_updater(bot, session))

        while True:
            if session.stats.stopped or should_stop_validation(session.user_id):
                session.stats.stopped = True
                break
            try:
                item = await asyncio.wait_for(session.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if session.queue.empty():
                    break
                continue

            await process_validation_item(
                item,
                ctx=ctx,
                session=session,
                settings=settings,
            )
            session.queue.task_done()

            if session.stats.fatal_reason:
                logger.warning(
                    "validation stopped (fatal=%s) user_id=%s processed=%s/%s",
                    session.stats.fatal_reason,
                    session.user_id,
                    session.stats.processed,
                    session.stats.total,
                )
                break

        dropped = _drain_validation_queue(session)
        if dropped:
            logger.info(
                "validation queue drained %s items user_id=%s (stopped=%s fatal=%s)",
                dropped,
                session.user_id,
                session.stats.stopped,
                session.stats.fatal_reason,
            )
        await session.queue.join()
    except Exception:
        logger.exception("validation worker user_id=%s", session.user_id)
        await bot.send_message(session.chat_id, "❌ Ошибка валидации. Смотрите логи.")
    finally:
        _drain_validation_queue(session)
        session.stop_updater.set()
        if session.updater_task:
            session.updater_task.cancel()
            try:
                await session.updater_task
            except asyncio.CancelledError:
                pass
        await _edit_status(bot, session, finished=True)
        await _send_export_file(bot, session, stopped=session.stats.stopped)
        if session.stats.fatal_reason:
            await bot.send_message(
                session.chat_id,
                f"❌ ValidEmail: <code>{session.stats.fatal_reason}</code>",
                parse_mode="HTML",
            )
        session.worker_task = None
        clear_stop_validation(session.user_id)
        session.export_rows.clear()


async def enqueue_void_validation(
    bot: Bot,
    settings: Settings,
    *,
    user_id: int,
    chat_id: int,
    items: list[dict[str, Any]],
    username: str = "",
    status_message_id: int | None = None,
) -> str:
    """Добавить объявления в очередь. Статистика накапливается в одном сообщении."""
    if not items:
        return "В JSON нет объявлений."

    session = _sessions.get(user_id)
    if session is None:
        session = ValidationSession(
            user_id=user_id,
            chat_id=chat_id,
            username=username or "",
        )
        _sessions[user_id] = session
    else:
        session.stats.stopped = False
        clear_stop_validation(user_id)

    if status_message_id and not session.status_message_id:
        session.status_message_id = status_message_id

    async with session.lock:
        session.stats.total += len(items)
        for it in items:
            session.queue.put_nowait(it)

    if session.worker_task is None or session.worker_task.done():
        session.worker_task = asyncio.create_task(_worker(bot, settings, session))
        return f"🔎 В очереди <b>{len(items)}</b> объявлений (всего {session.stats.total})."

    return (
        f"➕ Добавлено <b>{len(items)}</b> в очередь "
        f"(всего {session.stats.total}, обработано {session.stats.processed})."
    )


def stop_void_validation(user_id: int) -> bool:
    session = _sessions.get(user_id)
    if session is None:
        return False
    if session.worker_task is None or session.worker_task.done():
        if session.stats.processed > 0 or session.export_rows:
            return True
        return False
    session.stats.stopped = True
    from services.task_control import request_stop_validation

    request_stop_validation(user_id)
    return True


def is_validation_active(user_id: int) -> bool:
    session = _sessions.get(user_id)
    return bool(session and session.worker_task and not session.worker_task.done())

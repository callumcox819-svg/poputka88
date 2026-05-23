"""Автоматическая обработка JSON void-parser (файл или текст в чат)."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from config import Settings
from services.void_parser import parse_void_json_bytes, parse_void_json_text
from services.void_validation_runner import run_void_validation

router = Router()
logger = logging.getLogger(__name__)


class JsonDocumentFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        doc = message.document
        return bool(doc and doc.file_name and doc.file_name.lower().endswith(".json"))


class JsonTextFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        text = (message.text or "").strip()
        return bool(text) and text[0] in "{["


@router.message(F.document, JsonDocumentFilter())
async def on_json_document(message: Message, bot, settings: Settings) -> None:
    doc = message.document
    assert doc

    status = await message.answer("⏳ Загружаю JSON…")

    try:
        file = await bot.get_file(doc.file_id)
        buf = await bot.download_file(file.file_path)
        items = parse_void_json_bytes(buf.read())
    except json.JSONDecodeError:
        await status.edit_text("❌ Не удалось разобрать JSON.")
        return
    except Exception as exc:
        logger.exception("json download failed")
        await status.edit_text(f"❌ Ошибка загрузки: {exc}")
        return

    if not items:
        await status.edit_text("В файле нет массива <code>items</code>.", parse_mode="HTML")
        return

    u = message.from_user
    await run_void_validation(
        bot,
        settings,
        u.id,
        message.chat.id,
        items,
        status_message_id=status.message_id,
        username=(u.username or "") if u else "",
    )


@router.message(F.text, JsonTextFilter())
async def on_json_text(message: Message, bot, settings: Settings) -> None:
    text = (message.text or "").strip()
    try:
        items = parse_void_json_text(text)
    except json.JSONDecodeError:
        await message.answer("❌ Неверный JSON.")
        return

    if not items:
        await message.answer("В JSON нет объявлений (items).")
        return

    u = message.from_user
    await run_void_validation(
        bot,
        settings,
        u.id,
        message.chat.id,
        items,
        username=(u.username or "") if u else "",
    )

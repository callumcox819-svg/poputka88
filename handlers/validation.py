"""Валидация: JSON void-parser или список email."""

from __future__ import annotations

import asyncio
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from handlers.states import EmailValidation
from keyboards.main_menu import is_main_menu_text
from services.void_parser import parse_void_json_bytes, parse_void_json_text
from services.void_validation_runner import run_void_validation
from services.validation_runner import run_email_list_validation

router = Router()
logger = logging.getLogger(__name__)

VALIDATE_HELP = (
    "📧 <b>Валидация email</b>\n\n"
    "Пришлите <b>JSON</b> из void-parser (файл <code>.json</code>).\n\n"
    "Бот возьмёт <code>item_person_name</code>, соберёт адрес "
    "(например <code>Matthias.Gune.Kreis</code> → <code>matthias.gune.kreis@домен</code>) "
    "и проверит через ValidEmail.\n\n"
    "Домены — в ⚙️ Настройки → 📊 <b>Приоритет отправки</b>.\n"
    "GAG: ключ и профиль — ⚙️ → 🔑 Ключ / 🧾 Профиль.\n"
    "Ключи API — <code>VALIDEMAIL_API_KEY</code> и "
    "<code>VALIDEMAIL_API_KEY_2</code> (работают параллельно).\n\n"
    "Имя: минимум <b>3</b> буквы/цифры. При первом валидном email продавец сохраняется.\n\n"
    "/stopcheck — остановить."
)


@router.message(Command("validate"))
async def cmd_validate(message: Message, state: FSMContext) -> None:
    await state.set_state(EmailValidation.waiting_list)
    await message.answer(VALIDATE_HELP, parse_mode="HTML")


@router.message(EmailValidation.waiting_list, F.document)
async def on_validation_document(
    message: Message, state: FSMContext, bot, settings: Settings
) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return

    doc = message.document
    if not doc or not doc.file_name:
        await message.answer("Пришлите файл .json")
        return
    if not doc.file_name.lower().endswith(".json"):
        await message.answer("Нужен файл <code>.json</code> void-parser.", parse_mode="HTML")
        return

    await state.clear()
    status = await message.answer("⏳ Загружаю JSON…")

    try:
        file = await bot.get_file(doc.file_id)
        buf = await bot.download_file(file.file_path)
        raw = buf.read()
        items = parse_void_json_bytes(raw)
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

    await status.edit_text(
        f"🔎 Найдено объявлений: <b>{len(items)}</b>. Старт валидации…",
        parse_mode="HTML",
    )
    asyncio.create_task(
        run_void_validation(
            bot,
            settings,
            message.from_user.id,
            message.chat.id,
            items,
            status_message_id=status.message_id,
        )
    )


@router.message(EmailValidation.waiting_list)
async def on_validation_text(
    message: Message, state: FSMContext, bot, settings: Settings
) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        return

    # JSON текстом
    if text.startswith("{") or text.startswith("["):
        await state.clear()
        try:
            items = parse_void_json_text(text)
        except json.JSONDecodeError:
            await message.answer("❌ Неверный JSON.")
            return
        if not items:
            await message.answer("Нет объявлений в JSON.")
            return
        status = await message.answer(
            f"🔎 Объявлений: {len(items)}. Валидация…", parse_mode="HTML"
        )
        asyncio.create_task(
            run_void_validation(
                bot,
                settings,
                message.from_user.id,
                message.chat.id,
                items,
                status_message_id=status.message_id,
            )
        )
        return

    # Список email (старый режим)
    await state.clear()
    asyncio.create_task(
        run_email_list_validation(
            bot, settings, message.from_user.id, message.chat.id, text
        )
    )
    await message.answer("Проверка списка email запущена. /stopcheck — остановить.")

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.states import QuickAdd
from keyboards.main_menu import (
    BTN_QUICK_ADD,
    is_main_menu_text,
    main_keyboard,
)
from services.accounts_bulk import bulk_add_accounts, trim_details
from utils.bg_jobs import is_running as bg_is_running, start as bg_start
from utils.text_html import e

router = Router()


async def quick_add_begin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(QuickAdd.sender_name)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="quick_add_cancel")],
        ]
    )
    await message.answer(
        "⚡ <b>Быстрое добавление</b>\n\n"
        "<b>Шаг 1/2.</b> Введите <b>имя и фамилию</b> для отправки писем\n"
        "(например: <code>Maria Johansen</code>).\n\n"
        "Поддерживаются: Gmail, GMX, iCloud.\n\n"
        "Отмена: отправьте <code>-</code>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(F.text.in_({BTN_QUICK_ADD, "⚡ Быстрое добавление (Gmail)"}))
async def quick_add_from_menu(message: Message, state: FSMContext) -> None:
    await quick_add_begin(message, state)


@router.callback_query(F.data == "quick_add_cancel")
async def quick_add_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer("❌ Отменено.", reply_markup=main_keyboard())


@router.message(QuickAdd.sender_name)
async def quick_add_sender_name(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return

    raw = (message.text or "").strip()
    if raw == "-":
        await state.clear()
        return await message.answer("❌ Отменено.", reply_markup=main_keyboard())

    words = [w for w in raw.split() if w.strip()]
    if len(words) < 2:
        return await message.answer(
            "Укажите имя и фамилию через пробел (минимум 2 слова).\n"
            "Пример: <code>Maria Johansen</code>",
            parse_mode="HTML",
        )

    await state.update_data(quick_sender_name=raw)
    await state.set_state(QuickAdd.accounts)
    await message.answer(
        "✅ Имя сохранено.\n\n"
        "<b>Шаг 2/2.</b> Отправьте почтовые аккаунты:\n"
        "<code>email:пароль</code>\n\n"
        "Каждый аккаунт — с новой строки (можно несколько).\n"
        "<b>Gmail / iCloud</b> — пароль приложения.\n"
        "<b>GMX</b> — обычный пароль, IMAP включён в настройках GMX.\n\n"
        "Отмена: <code>-</code>",
        parse_mode="HTML",
    )


@router.message(QuickAdd.accounts)
async def quick_add_accounts(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return

    raw = message.text or ""
    if raw.strip() == "-":
        await state.clear()
        return await message.answer("❌ Отменено.", reply_markup=main_keyboard())

    data = await state.get_data()
    sender_name = (data.get("quick_sender_name") or "").strip()
    if not sender_name:
        await state.clear()
        return await message.answer(
            "Сессия сброшена. Начните с «⚡ Быстрое добавление».",
            reply_markup=main_keyboard(),
        )

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return await message.answer(
            "Не вижу строк. Формат: <code>email:пароль</code>",
            parse_mode="HTML",
        )

    tg_id = message.from_user.id
    if bg_is_running(tg_id, "accounts_add"):
        return await message.answer("⏳ Добавление аккаунтов уже выполняется…")

    await state.clear()
    await message.answer("⏳ Проверяю аккаунты (IMAP)…", reply_markup=main_keyboard())

    async def _job() -> None:
        ok_count, fail_count, details = await bulk_add_accounts(
            message, tg_id, sender_name, lines
        )
        summary = (
            f"⚡ <b>Готово</b>\n\n"
            f"Имя отправителя: <b>{e(sender_name)}</b>\n"
            f"Аккаунтов добавлено: <b>{ok_count}</b>\n"
            f"Ошибок: <b>{fail_count}</b>\n\n"
            + trim_details(details)
        )
        await message.answer(summary, parse_mode="HTML", reply_markup=main_keyboard())

    if not bg_start(tg_id, "accounts_add", _job()):
        await message.answer("⏳ Добавление аккаунтов уже выполняется…")

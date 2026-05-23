"""Меню настроек happy88 + подменю."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Settings
from database import (
    count_seller_blacklist,
    get_user_delay,
    get_user_sender_name,
    set_user_delay,
    set_user_sender_name,
)
from handlers.settings_accounts import render_accounts_menu
from keyboards.main_menu import main_keyboard
from keyboards.settings_happy import back_settings_kb, settings_menu_kb
from services.mailing_timing import load_timing, save_timing
from services.user_settings import (
    SPOOF_FROM_NAME_KEY,
    SPOOF_SUBJECT_KEY,
    get_setting,
    get_toggle_flags,
    set_setting,
    toggle_bool,
)
from utils.callback_edit import cq_edit_text
from utils.text_html import e

router = Router()

SETTINGS_MENU_TEXT = "Настройки"
DOMAIN_PRIORITY_KEY = "domain_priority"


class SettingsInput(StatesGroup):
    priority = State()
    timings = State()
    spoof_name = State()
    spoof_subject = State()


def match_settings_menu_text(text: str | None) -> bool:
    t = (text or "").strip().casefold().replace("\ufe0f", "")
    if not t:
        return False
    if "настройки" in t:
        return True
    return t in {"settings", "setting", "⚙️ настройки"}


async def settings_kb_for(user_id: int) -> InlineKeyboardMarkup:
    flags = await get_toggle_flags(user_id)
    return settings_menu_kb(flags)


async def _settings_header(user_id: int) -> str:
    bl = await count_seller_blacklist(user_id)
    return (
        f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>\n"
        f"<i>Ваши настройки, пресеты и чёрный список (отдельно у каждого пользователя).</i>\n"
        f"📧 Рассылка: тема = <code>OFFER</code> (название товара из валидации).\n"
        f"🚫 Чёрный список продавцов: <b>{bl}</b>"
    )


async def open_settings_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    uid = message.from_user.id
    kb = await settings_kb_for(uid)
    await message.answer(
        await _settings_header(uid),
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings_open")
async def settings_open_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    uid = callback.from_user.id
    kb = await settings_kb_for(uid)
    await cq_edit_text(callback, await _settings_header(uid), reply_markup=kb)


@router.callback_query(F.data.startswith("ref_toggle:"))
async def ref_toggle(callback: CallbackQuery) -> None:
    key = (callback.data or "").split(":", 1)[1].strip()
    if key not in {"smart_mode", "spoofing", "block_control"}:
        return await callback.answer()
    await toggle_bool(callback.from_user.id, key)
    kb = await settings_kb_for(callback.from_user.id)
    await cq_edit_text(callback, f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "ref_hide")
async def ref_hide(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await callback.answer()


# ——— Приоритет доменов ———

@router.callback_query(F.data == "priority_menu")
async def priority_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    raw = await get_setting(callback.from_user.id, DOMAIN_PRIORITY_KEY)
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list):
        items = []
    lst = "\n".join(f"{i + 1}. <code>{e(d)}</code>" for i, d in enumerate(items)) if items else "—"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить приоритет", callback_data="priority_edit")],
            [InlineKeyboardButton(text="🗑 Сбросить приоритет", callback_data="priority_reset")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
        ]
    )
    await cq_edit_text(
        callback,
        "📊 <b>Приоритет отправки</b>\n\n"
        "Домен №1 проверяется первым при валидации JSON, потом №2 и т.д.\n\n"
        f"<b>Текущий приоритет:</b>\n{lst}",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "priority_edit")
async def priority_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsInput.priority)
    await cq_edit_text(
        callback,
        "📊 <b>Приоритет отправки</b>\n\n"
        "Отправь домены списком (каждый с новой строки).\n"
        "Пример:\n<code>gmx.de\ngmail.com</code>\n\n"
        "Очистить: <code>-</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="priority_menu")]
            ]
        ),
    )
    await callback.answer()


@router.message(SettingsInput.priority)
async def priority_set(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    items = [] if txt == "-" else [
        re.sub(r"^https?://", "", x.strip().lower())
        for x in txt.splitlines()
        if x.strip()
    ]
    await set_setting(message.from_user.id, DOMAIN_PRIORITY_KEY, json.dumps(items))
    await state.clear()
    kb = await settings_kb_for(message.from_user.id)
    await message.answer("✅ Сохранено.", reply_markup=kb)


@router.callback_query(F.data == "priority_reset")
async def priority_reset(callback: CallbackQuery, state: FSMContext) -> None:
    await set_setting(callback.from_user.id, DOMAIN_PRIORITY_KEY, json.dumps([]))
    await callback.answer("Сброшено ✅")
    await priority_menu(callback, state)


# ——— Интервал / тайминги ———

@router.callback_query(F.data == "settings_timings")
async def settings_timings(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    timing = await load_timing(callback.from_user.id, settings.send_delay_sec)
    await cq_edit_text(
        callback,
        "⏱ <b>Тайминги рассылки</b>\n\n"
        f"MIN: <code>{timing['min']}</code> сек\n"
        f"MAX: <code>{timing['max']}</code> сек\n"
        f"Пачка с ящика: <code>{timing['batch_size']}</code> писем\n\n"
        "<i>Формат: <code>MIN MAX ПАЧКА</code> (пример: <code>2 4 5</code>)</i>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить тайминг", callback_data="timings_edit")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "timings_edit")
async def timings_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsInput.timings)
    await cq_edit_text(
        callback,
        "⏱ Отправь: <code>MIN MAX ПАЧКА</code> (пример: <code>2 4 5</code>).",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_timings")]
            ]
        ),
    )
    await callback.answer()


@router.message(SettingsInput.timings)
async def timings_set(message: Message, state: FSMContext) -> None:
    m = re.match(r"^(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)(?:\s+(\d+))?$", (message.text or "").strip())
    if not m:
        return await message.answer("❌ Формат: MIN MAX [ПАЧКА] (например: 2 4 5)")
    mn, mx = float(m.group(1)), float(m.group(2))
    batch = int(m.group(3) or 3)
    batch = max(1, min(8, batch))
    if mn > mx:
        mn, mx = mx, mn
    await save_timing(message.from_user.id, mn, mx, batch)
    await set_user_delay(message.from_user.id, mn)
    await state.clear()
    kb = await settings_kb_for(message.from_user.id)
    await message.answer("✅ Тайминги сохранены.", reply_markup=kb)


# ——— Спуфинг / имя ———

@router.callback_query(F.data == "spoof_name_menu")
async def spoof_name_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    uid = callback.from_user.id
    cur_name = (await get_setting(uid, SPOOF_FROM_NAME_KEY) or "").strip()
    if not cur_name:
        cur_name = await get_user_sender_name(uid) or "— не задано —"
    cur_subj = await get_setting(uid, SPOOF_SUBJECT_KEY) or "— не задана —"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Установить имя", callback_data="spoof_name_set")],
            [
                InlineKeyboardButton(
                    text="✅ Установить тему", callback_data="spoof_subject_set"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
        ]
    )
    await cq_edit_text(
        callback,
        (
            f"👤 <b>Имя для спуфинга</b>\n\n"
            f"Имя (From): <b>{e(cur_name)}</b>\n"
            f"Тема (Subject): <b>{e(cur_subj)}</b>\n\n"
            "При <b>HTML</b> строго из этой секции:\n"
            "• <b>From</b> и <code>{{NICK}}</code> — только «Имя» выше\n"
            "• <b>Subject</b> — только «Установить тему»\n"
            "Тема входящего письма и имя SMTP-аккаунта <b>не</b> используются.\n"
            "HTML — только через прокси, с GAG-ссылкой в <code>{{LINK}}</code>.\n"
        ),
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "spoof_name_set")
async def spoof_name_set(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsInput.spoof_name)
    await cq_edit_text(
        callback,
        "Введите имя и фамилию для отправки (например <code>Maria Johansen</code>):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚫 Отмена", callback_data="spoof_name_menu")]
            ]
        ),
    )
    await callback.answer()


@router.message(SettingsInput.spoof_name)
async def spoof_name_save(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name.split()) < 2:
        return await message.answer("Минимум 2 слова (имя и фамилия).")
    await set_setting(message.from_user.id, SPOOF_FROM_NAME_KEY, name)
    await state.clear()
    await message.answer(f"✅ Имя сохранено: <b>{e(name)}</b>", parse_mode="HTML")
    kb = await settings_kb_for(message.from_user.id)
    await message.answer(f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "spoof_subject_set")
async def spoof_subject_set(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsInput.spoof_subject)
    await cq_edit_text(
        callback,
        "Введите тему письма для HTML-спуфинга:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚫 Отмена", callback_data="spoof_name_menu")]
            ]
        ),
    )
    await callback.answer()


@router.message(SettingsInput.spoof_subject)
async def spoof_subject_save(message: Message, state: FSMContext) -> None:
    subj = (message.text or "").strip()
    if not subj:
        return await message.answer("Тема не может быть пустой.")
    await set_setting(message.from_user.id, SPOOF_SUBJECT_KEY, subj)
    await state.clear()
    await message.answer(f"✅ Тема сохранена: <b>{e(subj)}</b>", parse_mode="HTML")
    kb = await settings_kb_for(message.from_user.id)
    await message.answer(f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>", reply_markup=kb, parse_mode="HTML")


# ——— IMAP check (команда) ———

async def run_imap_check(bot: Bot, chat_id: int, user_id: int) -> None:
    from database import list_all_smtp_accounts
    from services.imap_check import check_accounts_imap, format_imap_report

    accounts = await list_all_smtp_accounts(user_id, with_secrets=True)
    active = [a for a in accounts if int(a.get("enabled", 1))]
    if not active:
        await bot.send_message(
            chat_id,
            "Нет активных аккаунтов для IMAP. «⚡ Быстрое добавление».",
            reply_markup=main_keyboard(),
        )
        return

    status = await bot.send_message(
        chat_id,
        f"📥 Проверяю входящие IMAP ({len(active)} ящ.)…",
        parse_mode="HTML",
    )
    results = await check_accounts_imap(active)
    text = format_imap_report(results)

    from services.incoming_worker import poll_incoming_for_user

    try:
        acc_n, cards = await poll_incoming_for_user(bot, user_id, catch_up=True)
        text += (
            f"\n\n📬 <b>Догон в бот:</b> опрошено {acc_n} ящ., новых карточек: <b>{cards}</b>"
        )
    except Exception:
        logger.exception("imap_check catch-up poll failed")

    try:
        await status.edit_text(text, parse_mode="HTML")
    except Exception:
        await bot.send_message(chat_id, text, parse_mode="HTML")


# Старые callback из простого меню
@router.callback_query(F.data == "set:close")
async def cb_close_legacy(cb: CallbackQuery) -> None:
    await ref_hide(cb)


@router.callback_query(F.data == "set:accounts")
async def cb_accounts_legacy(cb: CallbackQuery) -> None:
    await cb.answer()
    await render_accounts_menu(cb, cb.from_user.id, page=1)


@router.callback_query(F.data == "set:imap")
async def cb_imap_legacy(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    await run_imap_check(bot, cb.message.chat.id, cb.from_user.id)


@router.callback_query(F.data == "set:delay")
async def cb_delay_legacy(cb: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await settings_timings(cb, state, settings)

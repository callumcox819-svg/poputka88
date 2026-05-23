"""Меню настроек happy88 + подменю."""

from __future__ import annotations

import json
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Settings
from database import get_user_delay, get_user_sender_name, set_user_delay, set_user_sender_name
from handlers.settings_accounts import render_accounts_menu
from keyboards.main_menu import main_keyboard
from keyboards.settings_happy import back_settings_kb, settings_menu_kb
from services.mailing_timing import load_timing, save_timing
from services.user_settings import get_setting, get_toggle_flags, set_setting, toggle_bool
from utils.callback_edit import cq_edit_text
from utils.text_html import e

router = Router()

SETTINGS_MENU_TEXT = "Настройки"
DOMAIN_PRIORITY_KEY = "domain_priority"
GAG_API_KEY = "gag_api_key"
GAG_PROFILE_TITLE = "gag_profile_title"
GAG_PROFILE_NAME = "gag_profile_name"
GAG_PROFILE_ADDRESS = "gag_profile_address"


class SettingsInput(StatesGroup):
    priority = State()
    timings = State()
    spoof_name = State()
    api_key = State()
    profile_title = State()
    profile_name = State()
    profile_address = State()


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


async def open_settings_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    kb = await settings_kb_for(message.from_user.id)
    await message.answer(
        f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings_open")
async def settings_open_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    kb = await settings_kb_for(callback.from_user.id)
    await cq_edit_text(callback, f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>", reply_markup=kb)


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
    cur = await get_user_sender_name(callback.from_user.id) or "— не задано —"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Установить имя", callback_data="spoof_name_set")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
        ]
    )
    await cq_edit_text(
        callback,
        f"👤 <b>Имя для спуфинга</b>\n\n"
        f"Текущее: <b>{e(cur)}</b>\n\n"
        "Используется в поле From при 🟢 Спуфинг.\n"
        "Также задаётся в «⚡ Быстрое добавление».",
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
    await set_user_sender_name(message.from_user.id, name)
    await state.clear()
    await message.answer(f"✅ Имя сохранено: <b>{e(name)}</b>", parse_mode="HTML")
    kb = await settings_kb_for(message.from_user.id)
    await message.answer(f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>", reply_markup=kb, parse_mode="HTML")


# ——— Ключ API ———

@router.callback_query(F.data == "gag_show:key")
async def gag_show_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    cur = await get_setting(callback.from_user.id, GAG_API_KEY) or "—"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Установить", callback_data="gag_set:key")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
        ]
    )
    await cq_edit_text(
        callback,
        f"🔑 <b>API-ключ</b>\n\nТекущий: <code>{e(cur)}</code>",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "gag_set:key")
async def gag_set_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsInput.api_key)
    await cq_edit_text(
        callback,
        "Отправьте API-ключ одним сообщением (или <code>-</code> чтобы очистить):",
        reply_markup=back_settings_kb(),
    )
    await callback.answer()


@router.message(SettingsInput.api_key)
async def gag_key_save(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if val == "-":
        val = ""
    await set_setting(message.from_user.id, GAG_API_KEY, val)
    await state.clear()
    await message.answer("✅ Ключ сохранён." if val else "✅ Ключ очищен.")
    kb = await settings_kb_for(message.from_user.id)
    await message.answer(f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>", reply_markup=kb, parse_mode="HTML")


# ——— Профиль ———

def _profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать профиль", callback_data="gag_profile_create")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
        ]
    )


@router.callback_query(F.data == "gag_show:profile")
async def gag_show_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    uid = callback.from_user.id
    title = (await get_setting(uid, GAG_PROFILE_TITLE) or "").strip() or "—"
    name = (await get_setting(uid, GAG_PROFILE_NAME) or "").strip() or "—"
    addr = (await get_setting(uid, GAG_PROFILE_ADDRESS) or "").strip() or "—"
    await cq_edit_text(
        callback,
        "🧾 <b>Профиль</b>\n\n"
        f"Название: <code>{e(title)}</code>\n"
        f"Имя: <code>{e(name)}</code>\n"
        f"Адрес: <code>{e(addr)}</code>",
        reply_markup=_profile_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "gag_profile_create")
async def gag_profile_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsInput.profile_title)
    await cq_edit_text(
        callback,
        "Отправьте <b>название профиля</b>:",
        reply_markup=back_settings_kb(),
    )
    await callback.answer()


@router.message(SettingsInput.profile_title)
async def profile_title(message: Message, state: FSMContext) -> None:
    t = (message.text or "").strip()
    if not t:
        return await message.answer("Пустое значение.")
    await state.update_data(profile_title=t)
    await state.set_state(SettingsInput.profile_name)
    await message.answer("Отправьте <b>имя покупателя</b>:", parse_mode="HTML")


@router.message(SettingsInput.profile_name)
async def profile_name(message: Message, state: FSMContext) -> None:
    n = (message.text or "").strip()
    if not n:
        return await message.answer("Пустое значение.")
    await state.update_data(profile_name=n)
    await state.set_state(SettingsInput.profile_address)
    await message.answer("Отправьте <b>адрес</b>:", parse_mode="HTML")


@router.message(SettingsInput.profile_address)
async def profile_address(message: Message, state: FSMContext) -> None:
    addr = (message.text or "").strip()
    if not addr:
        return await message.answer("Пустое значение.")
    data = await state.get_data()
    uid = message.from_user.id
    await set_setting(uid, GAG_PROFILE_TITLE, data.get("profile_title", ""))
    await set_setting(uid, GAG_PROFILE_NAME, data.get("profile_name", ""))
    await set_setting(uid, GAG_PROFILE_ADDRESS, addr)
    await state.clear()
    await message.answer("✅ Профиль сохранён.", reply_markup=main_keyboard())


# ——— IMAP check (команда) ———

async def run_imap_check(bot: Bot, chat_id: int, user_id: int) -> None:
    from services.imap_check import check_accounts
    from database import list_smtp_accounts

    accounts = await list_smtp_accounts(user_id, with_secrets=True)
    if not accounts:
        await bot.send_message(
            chat_id,
            "Нет аккаунтов. «⚡ Быстрое добавление».",
            reply_markup=main_keyboard(),
        )
        return
    await bot.send_message(chat_id, f"Проверяю входящие ({len(accounts)} акк.)…")
    results = await check_accounts(accounts)
    lines = ["📥 <b>IMAP</b>\n"]
    for r in results:
        if r["ok"]:
            lines.append(f"✅ {r['email']}: непр. {r['unseen']}, всего {r['total']}")
        else:
            lines.append(f"❌ {r['email']}: {r.get('error', 'ошибка')}")
    await bot.send_message(chat_id, "\n".join(lines), reply_markup=main_keyboard(), parse_mode="HTML")


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

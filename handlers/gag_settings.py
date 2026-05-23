"""GAG Team: API-ключ и профиль (как happy88, только CH/GAG)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.settings import SETTINGS_MENU_TEXT, settings_kb_for
from keyboards.main_menu import main_keyboard
from services.gag_keys import (
    GAG_API_KEY,
    GAG_DOMAIN_SLOT_KEY,
    GAG_PROFILE_ADDRESS_KEY,
    GAG_PROFILE_NAME_KEY,
    GAG_PROFILE_TITLE_KEY,
    GAG_SERVICE_KEY,
    gag_service_label,
    gag_service_matches,
    normalize_gag_service,
    parse_gag_domain_slot,
)
from services.gag_user import load_gag_profile
from services.user_settings import get_setting, set_setting
from utils.callback_edit import cq_edit_text
from utils.secrets import clean_secret
from utils.text_html import e

router = Router(name="gag_settings")

GAG_API_DOCS = (
    "📖 <b>Документация GAG API</b>\n\n"
    "<b>Генерация ссылки</b>\n"
    "<code>POST https://imgbeoxo.com/generate</code>\n"
    "• <code>apikey</code> — ваш ключ\n"
    "• <code>title</code>, <code>price</code>, <code>service</code>\n"
    "• <code>name</code>, <code>address</code>, <code>image</code>\n"
    "• <code>domain</code> 1–8 · <code>version</code> 1 / 2 / lk\n\n"
    "<b>Отправка письма через GAG</b>\n"
    "<code>POST https://imgbeoxo.com/send-email</code>\n"
    "• <code>adId</code>, <code>email</code>, <code>mailer</code>, <code>status</code>\n\n"
    "🧩 Команда <b>GAG</b> · 🇨🇭 Швейцария"
)


class GagKeyState(StatesGroup):
    waiting = State()


class GagProfileState(StatesGroup):
    title = State()
    name = State()
    address = State()


def _back_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")]
        ]
    )


def _profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Создать / изменить профиль",
                    callback_data="gag_profile_create",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧭 Выбор сервиса", callback_data="gag_service_menu"
                )
            ],
            [InlineKeyboardButton(text="🌐 Домен", callback_data="gag_domain_menu")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
        ]
    )


def _key_kb(*, has_key: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🛠 Установить ключ", callback_data="gag_set:key")],
        [InlineKeyboardButton(text="📖 Документация API", callback_data="gag_api_docs")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")],
    ]
    if has_key:
        rows.insert(1, [InlineKeyboardButton(text="🟢 Скрыть ключ", callback_data="gag_hide:key")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_profile(callback: CallbackQuery) -> None:
    uid = callback.from_user.id
    p = await load_gag_profile(uid)
    slot = p.domain_slot
    if slot is None:
        domain_text = "Домен команды (по умолчанию)"
    else:
        domain_text = f"Личный домен {slot} → API domain {slot + 4}"

    svc_code = normalize_gag_service(p.service) or (p.service or "—")
    text = (
        "🧾 <b>Профиль GAG</b>\n\n"
        f"Название: <code>{e(p.title or '—')}</code>\n"
        f"Имя покупателя: <code>{e(p.name or '—')}</code>\n"
        f"Адрес: <code>{e(p.address or '—')}</code>\n"
        f"Сервис: <b>{e(p.service_label)}</b> (<code>{e(svc_code)}</code>)\n\n"
        f"🌐 {domain_text}\n\n"
        "Для <code>/generate</code> нужны заполненные поля и выбранный сервис."
    )
    await cq_edit_text(callback, text, reply_markup=_profile_kb())


async def _render_key(callback: CallbackQuery) -> None:
    uid = callback.from_user.id
    key = (await get_setting(uid, GAG_API_KEY) or "").strip()
    status = "✅ установлен" if key else "❌ не установлен"
    shown = f"<code>{e(key)}</code>" if key else "—"
    text = (
        "🔑 <b>API-ключ GAG</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Ваш ключ: {shown}\n\n"
        "Личный ключ команды GAG (imgbeoxo.com).\n"
        "Используется для генерации ссылок и send-email."
    )
    await cq_edit_text(callback, text, reply_markup=_key_kb(has_key=bool(key)))


@router.callback_query(F.data == "gag_show:profile")
async def gag_show_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _render_profile(callback)


@router.callback_query(F.data == "gag_show:key")
async def gag_show_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _render_key(callback)


@router.callback_query(F.data == "gag_hide:key")
async def gag_hide_key(callback: CallbackQuery) -> None:
    await cq_edit_text(callback, "✅ Ключ скрыт с экрана.", reply_markup=_back_settings())
    await callback.answer()


@router.callback_query(F.data == "gag_api_docs")
async def gag_api_docs(callback: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К ключу", callback_data="gag_show:key")]
        ]
    )
    await cq_edit_text(callback, GAG_API_DOCS, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "gag_set:key")
async def gag_set_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GagKeyState.waiting)
    await cq_edit_text(
        callback,
        "✍️ Отправьте <b>API-ключ GAG</b> одним сообщением.\n"
        "Или <code>-</code> чтобы очистить.",
        reply_markup=_back_settings(),
    )
    await callback.answer()


@router.message(GagKeyState.waiting)
async def gag_key_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw == "-":
        val = ""
    else:
        val = clean_secret(raw)
        if not val:
            return await message.answer("❌ Пустой ключ. Отправьте ещё раз.")
    await set_setting(message.from_user.id, GAG_API_KEY, val)
    await state.clear()
    await message.answer("✅ Ключ сохранён." if val else "✅ Ключ очищен.")
    kb = await settings_kb_for(message.from_user.id)
    await message.answer(f"⚙️ <b>{SETTINGS_MENU_TEXT}</b>", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "gag_profile_create")
async def gag_profile_create(callback: CallbackQuery, state: FSMContext) -> None:
    uid = callback.from_user.id
    p = await load_gag_profile(uid)
    await state.clear()
    await state.set_state(GagProfileState.title)
    await cq_edit_text(
        callback,
        "➕ <b>Профиль GAG</b>\n\n"
        f"Сейчас:\n"
        f"• Название: <code>{e(p.title or '—')}</code>\n"
        f"• Имя: <code>{e(p.name or '—')}</code>\n"
        f"• Адрес: <code>{e(p.address or '—')}</code>\n\n"
        "Отправьте <b>название объявления</b> (title для API):",
        reply_markup=_back_settings(),
    )
    await callback.answer()


@router.message(GagProfileState.title)
async def gag_profile_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        return await message.answer("❌ Пустое значение.")
    await state.update_data(profile_title=title)
    await state.set_state(GagProfileState.name)
    await message.answer("Отправьте <b>имя покупателя</b> (name):", parse_mode="HTML")


@router.message(GagProfileState.name)
async def gag_profile_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        return await message.answer("❌ Пустое значение.")
    await state.update_data(profile_name=name)
    await state.set_state(GagProfileState.address)
    await message.answer("Отправьте <b>адрес</b> (address):", parse_mode="HTML")


@router.message(GagProfileState.address)
async def gag_profile_address(message: Message, state: FSMContext) -> None:
    addr = (message.text or "").strip()
    if not addr:
        return await message.answer("❌ Пустое значение.")
    data = await state.get_data()
    uid = message.from_user.id
    await set_setting(uid, GAG_PROFILE_TITLE_KEY, data.get("profile_title", ""))
    await set_setting(uid, GAG_PROFILE_NAME_KEY, data.get("profile_name", ""))
    await set_setting(uid, GAG_PROFILE_ADDRESS_KEY, addr)
    await state.clear()
    await message.answer("✅ Профиль GAG сохранён.", reply_markup=main_keyboard())


@router.callback_query(F.data == "gag_service_menu")
async def gag_service_menu(callback: CallbackQuery) -> None:
    cur = (await get_setting(callback.from_user.id, GAG_SERVICE_KEY) or "").strip()

    def mark(service: str, label: str) -> str:
        return ("🟩 " if gag_service_matches(cur, service) else "⬜️ ") + label

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=mark("tutti_ch", "ТУТТИ"),
                    callback_data="gag_service_set:tutti_ch",
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark("posta_ch", "ПОСТ"),
                    callback_data="gag_service_set:posta_ch",
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark("ricardo_ch", "Ricardo.ch"),
                    callback_data="gag_service_set:ricardo_ch",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="gag_show:profile")],
        ]
    )
    await cq_edit_text(
        callback,
        "🧭 <b>Выбор сервиса</b>\n\n"
        "Код для <code>service</code> в API:\n"
        "<code>tutti_ch</code>, <code>posta_ch</code>, <code>ricardo_ch</code>",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gag_service_set:"))
async def gag_service_set(callback: CallbackQuery) -> None:
    try:
        _, service = (callback.data or "").split(":", 1)
    except ValueError:
        return await callback.answer("Неверные данные", show_alert=True)
    canonical = normalize_gag_service(service)
    if not canonical:
        return await callback.answer("Неизвестный сервис", show_alert=True)
    await set_setting(callback.from_user.id, GAG_SERVICE_KEY, canonical)
    await callback.answer(f"Сервис: {gag_service_label(canonical)}", show_alert=False)
    cur = canonical
    # refresh menu marks
    def mark(service: str, label: str) -> str:
        return ("🟩 " if gag_service_matches(cur, service) else "⬜️ ") + label

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=mark("tutti_ch", "ТУТТИ"),
                    callback_data="gag_service_set:tutti_ch",
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark("posta_ch", "ПОСТ"),
                    callback_data="gag_service_set:posta_ch",
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark("ricardo_ch", "Ricardo.ch"),
                    callback_data="gag_service_set:ricardo_ch",
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="gag_show:profile")],
        ]
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        await gag_service_menu(callback)


@router.callback_query(F.data == "gag_domain_menu")
async def gag_domain_menu(callback: CallbackQuery) -> None:
    cur_slot = parse_gag_domain_slot(
        await get_setting(callback.from_user.id, GAG_DOMAIN_SLOT_KEY)
    )

    def mark_slot(slot: int) -> str:
        return ("✅ " if cur_slot == slot else "⬜️ ") + f"Домен {slot}"

    team_mark = "✅ Домен команды" if cur_slot is None else "⬜️ Домен команды"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=team_mark, callback_data="gag_domain_team"
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark_slot(1), callback_data="gag_domain_set:1"
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark_slot(2), callback_data="gag_domain_set:2"
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark_slot(3), callback_data="gag_domain_set:3"
                )
            ],
            [
                InlineKeyboardButton(
                    text=mark_slot(4), callback_data="gag_domain_set:4"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="gag_show:profile")],
        ]
    )
    text = (
        "🌐 <b>Домен GAG</b>\n\n"
        "• <b>Домен команды</b> — без поля domain в API\n"
        "• <b>Домен 1–4</b> — в API: 5, 6, 7, 8 (слот + 4)"
    )
    await cq_edit_text(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "gag_domain_team")
async def gag_domain_team(callback: CallbackQuery) -> None:
    await set_setting(callback.from_user.id, GAG_DOMAIN_SLOT_KEY, "")
    await gag_domain_menu(callback)


@router.callback_query(F.data.startswith("gag_domain_set:"))
async def gag_domain_set(callback: CallbackQuery) -> None:
    try:
        _, raw = (callback.data or "").split(":", 1)
        slot = int((raw or "").strip())
    except (ValueError, IndexError):
        return await callback.answer("Неверные данные", show_alert=True)
    if slot not in (1, 2, 3, 4):
        return await callback.answer("Неизвестный домен", show_alert=True)
    await set_setting(callback.from_user.id, GAG_DOMAIN_SLOT_KEY, str(slot))
    await gag_domain_menu(callback)

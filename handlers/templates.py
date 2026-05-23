"""🧾 Пресеты и 📄 Умные пресеты — логика happy88."""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from keyboards.main_menu import is_main_menu_text
from services.presets import (
    MAX_TEXT_LEN,
    MAX_TITLE_LEN,
    TemplateItem,
    load_smart_texts,
    load_templates,
    parse_preset_name_dash_text,
    save_smart_texts,
    save_templates,
    template_named_pairs,
)
from utils.callback_edit import cq_edit_text
from utils.preset_list_ui import (
    NOTE_REGULAR_PRESETS,
    NOTE_SMART_PRESETS,
    REGULAR_PRESETS_EMPTY_HINT,
    named_presets_pick_kb,
    render_named_presets_page,
    render_text_presets_page,
    text_presets_manage_kb,
    text_presets_pick_kb,
)

router = Router()


class PresetAdd(StatesGroup):
    name = State()
    text = State()


class PresetEdit(StatesGroup):
    idx = State()
    name = State()
    text = State()


class SmartTmplAdd(StatesGroup):
    text = State()


class SmartTmplEdit(StatesGroup):
    idx = State()
    text = State()


def _regular_presets_kb(has_any: bool) -> InlineKeyboardMarkup:
    return text_presets_manage_kb(
        add_cb="tmpl_add",
        edit_cb="tmpl_preset_edit",
        del_cb="tmpl_preset_del",
        del_all_cb="tmpl_delall",
        back_cb="settings_open",
        hide_cb="tmpl_preset_hide",
        has_any=has_any,
    )


def _smart_presets_kb(has_any: bool) -> InlineKeyboardMarkup:
    return text_presets_manage_kb(
        add_cb="stmpl_add",
        edit_cb="stmpl_edit",
        del_cb="stmpl_del",
        del_all_cb="stmpl_delall",
        back_cb="settings_open",
        hide_cb="stmpl_hide",
        has_any=has_any,
    )


async def _delete_message_safe(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _hide_old_menu_markup(bot, state_data: dict) -> None:
    chat_id = state_data.get("_menu_chat_id")
    msg_id = state_data.get("_menu_msg_id")
    if not chat_id or not msg_id:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=int(chat_id), message_id=int(msg_id), reply_markup=None
        )
    except Exception:
        pass


async def _send_presets_menu_message(message: Message, user_id: int) -> None:
    pairs = template_named_pairs(await load_templates(user_id))
    await message.answer(
        render_named_presets_page(
            "🧾 <b>Ваши пресеты:</b>",
            pairs,
            empty_hint=REGULAR_PRESETS_EMPTY_HINT,
            footer_note=NOTE_REGULAR_PRESETS,
        ),
        reply_markup=_regular_presets_kb(bool(pairs)),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _send_smart_menu_message(message: Message, user_id: int) -> None:
    texts = await load_smart_texts(user_id)
    await message.answer(
        render_text_presets_page(
            "📄 <b>Ваши умные пресеты:</b>",
            texts,
            footer_note=NOTE_SMART_PRESETS,
        ),
        reply_markup=_smart_presets_kb(bool(texts)),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _finish_presets_add(message: Message, state_data: dict, user_id: int) -> None:
    prompt_id = state_data.get("_prompt_msg_id")
    if prompt_id:
        await _delete_message_safe(message.bot, message.chat.id, int(prompt_id))
    await _hide_old_menu_markup(message.bot, state_data)
    await message.answer("✅ Добавлено.")
    await _send_presets_menu_message(message, user_id)


async def _finish_smart_add(message: Message, state_data: dict, user_id: int) -> None:
    prompt_id = state_data.get("_prompt_msg_id")
    if prompt_id:
        await _delete_message_safe(message.bot, message.chat.id, int(prompt_id))
    await _hide_old_menu_markup(message.bot, state_data)
    await message.answer("✅ Добавлено.")
    await _send_smart_menu_message(message, user_id)


# ——— Пресеты (ответы на письма) ———

@router.callback_query(F.data == "presets_menu")
async def presets_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    uid = call.from_user.id
    await state.update_data(
        _menu_chat_id=call.message.chat.id,
        _menu_msg_id=call.message.message_id,
    )
    pairs = template_named_pairs(await load_templates(uid))
    await cq_edit_text(
        call,
        render_named_presets_page(
            "🧾 <b>Ваши пресеты:</b>",
            pairs,
            empty_hint=REGULAR_PRESETS_EMPTY_HINT,
            footer_note=NOTE_REGULAR_PRESETS,
        ),
        reply_markup=_regular_presets_kb(bool(pairs)),
    )
    await call.answer()


@router.callback_query(F.data == "tmpl_delall")
async def presets_delete_all(call: CallbackQuery, state: FSMContext) -> None:
    await save_templates(call.from_user.id, [])
    await call.answer("Удалено")
    await presets_menu(call, state)


@router.callback_query(F.data == "tmpl_preset_hide")
async def tmpl_preset_hide(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Скрыто")


@router.callback_query(F.data == "tmpl_add")
async def tmpl_add_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        _menu_chat_id=call.message.chat.id,
        _menu_msg_id=call.message.message_id,
    )
    await state.set_state(PresetAdd.name)
    prompt = await call.message.answer(
        "➕ <b>Шаг 1/2.</b> Отправь <b>имя пресета</b> — оно будет на кнопке при ответе на письмо.\n\n"
        "Пример: <code>новый пресет</code>\n"
        "Или сразу: <code>имя - текст письма</code>",
        parse_mode="HTML",
    )
    await state.update_data(_prompt_msg_id=prompt.message_id)
    await call.answer()


@router.message(PresetAdd.name)
async def tmpl_add_name(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return
    parsed = parse_preset_name_dash_text(message.text or "")
    if parsed:
        title, body = parsed
        data = await state.get_data()
        await state.clear()
        uid = message.from_user.id
        items = await load_templates(uid)
        items.append(TemplateItem(title=title, text=body))
        await save_templates(uid, items)
        await _finish_presets_add(message, data, uid)
        return
    title = (message.text or "").strip()[:MAX_TITLE_LEN]
    if not title:
        return await message.answer("Имя не может быть пустым.")
    await state.update_data(preset_name=title)
    await state.set_state(PresetAdd.text)
    await message.answer(
        "➕ <b>Шаг 2/2.</b> Отправь <b>текст пресета</b> — его получит адресат.",
        parse_mode="HTML",
    )


@router.message(PresetAdd.text)
async def tmpl_add_text(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return
    body = (message.text or "").strip()[:MAX_TEXT_LEN]
    if len(body) < 2:
        return await message.answer("Текст слишком короткий.")
    data = await state.get_data()
    title = str(data.get("preset_name") or "").strip()[:MAX_TITLE_LEN]
    if not title:
        await state.clear()
        return await message.answer("Имя потеряно. Начни с «➕ Добавить пресет».")
    await state.clear()
    uid = message.from_user.id
    items = await load_templates(uid)
    items.append(TemplateItem(title=title, text=body))
    await save_templates(uid, items)
    await _finish_presets_add(message, data, uid)


@router.callback_query(F.data == "tmpl_preset_del")
async def tmpl_preset_del_pick(call: CallbackQuery) -> None:
    uid = call.from_user.id
    pairs = template_named_pairs(await load_templates(uid))
    if not pairs:
        return await call.answer("Пусто")
    await cq_edit_text(
        call,
        "🗑 Выбери пресет для удаления:",
        reply_markup=named_presets_pick_kb(pairs, "tmpl_preset_del", "presets_menu"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("tmpl_preset_del:"))
async def tmpl_preset_del_idx(call: CallbackQuery, state: FSMContext) -> None:
    idx = int(call.data.split(":")[1])
    uid = call.from_user.id
    items = await load_templates(uid)
    if idx < 0 or idx >= len(items):
        return await call.answer("Не найден", show_alert=True)
    items.pop(idx)
    await save_templates(uid, items)
    await call.answer("Удалено")
    await presets_menu(call, state)


@router.callback_query(F.data == "tmpl_preset_edit")
async def tmpl_preset_edit_pick(call: CallbackQuery, state: FSMContext) -> None:
    uid = call.from_user.id
    items = await load_templates(uid)
    if not items:
        return await call.answer("Пусто")
    await state.update_data(
        _menu_chat_id=call.message.chat.id, _menu_msg_id=call.message.message_id
    )
    pairs = template_named_pairs(items)
    await cq_edit_text(
        call,
        "✏️ Выбери пресет для изменения:",
        reply_markup=named_presets_pick_kb(pairs, "tmpl_preset_edit", "presets_menu"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("tmpl_preset_edit:"))
async def tmpl_preset_edit_choose(call: CallbackQuery, state: FSMContext) -> None:
    idx = int(call.data.split(":")[1])
    uid = call.from_user.id
    items = await load_templates(uid)
    if idx < 0 or idx >= len(items):
        return await call.answer("Не найден", show_alert=True)
    await state.update_data(idx=idx)
    await state.set_state(PresetEdit.name)
    old = items[idx]
    await call.message.answer(
        f"✏️ <b>Шаг 1/2.</b> Новое имя (сейчас: <code>{escape(old.title)}</code>):",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(PresetEdit.name)
async def tmpl_preset_edit_name(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return
    title = (message.text or "").strip()[:MAX_TITLE_LEN]
    if not title:
        return await message.answer("Имя не может быть пустым.")
    await state.update_data(preset_name=title)
    await state.set_state(PresetEdit.text)
    await message.answer("✏️ <b>Шаг 2/2.</b> Новый текст пресета:", parse_mode="HTML")


@router.message(PresetEdit.text)
async def tmpl_preset_edit_text(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return
    body = (message.text or "").strip()[:MAX_TEXT_LEN]
    if len(body) < 2:
        return await message.answer("Текст слишком короткий.")
    data = await state.get_data()
    idx = int(data.get("idx", -1))
    title = str(data.get("preset_name") or "").strip()[:MAX_TITLE_LEN]
    await state.clear()
    uid = message.from_user.id
    items = await load_templates(uid)
    if idx < 0 or idx >= len(items):
        return await message.answer("Пресет не найден.")
    items[idx] = TemplateItem(title=title, text=body)
    await save_templates(uid, items)
    await _hide_old_menu_markup(message.bot, data)
    await message.answer("✅ Сохранено.")
    await _send_presets_menu_message(message, uid)


# ——— Умные пресеты (рассылка /send) ———

@router.callback_query(F.data == "smart_presets_menu")
async def smart_presets_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    uid = call.from_user.id
    await state.update_data(
        _menu_chat_id=call.message.chat.id,
        _menu_msg_id=call.message.message_id,
    )
    texts = await load_smart_texts(uid)
    await cq_edit_text(
        call,
        render_text_presets_page(
            "📄 <b>Ваши умные пресеты:</b>",
            texts,
            footer_note=NOTE_SMART_PRESETS,
        ),
        reply_markup=_smart_presets_kb(bool(texts)),
    )
    await call.answer()


@router.callback_query(F.data == "stmpl_hide")
async def stmpl_hide(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Скрыто")


@router.callback_query(F.data == "stmpl_add")
async def stmpl_add_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        _menu_chat_id=call.message.chat.id,
        _menu_msg_id=call.message.message_id,
    )
    await state.set_state(SmartTmplAdd.text)
    prompt = await call.message.answer(
        "➕ Отправь текст пресета одним сообщением.\n"
        "Можно <code>OFFER</code> / <code>{{OFFER}}</code> и спинтаксис <code>{a|b|c}</code>.",
        parse_mode="HTML",
    )
    await state.update_data(_prompt_msg_id=prompt.message_id)
    await call.answer()


@router.message(SmartTmplAdd.text)
async def stmpl_add_text(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return
    text = (message.text or "").strip()[:MAX_TEXT_LEN]
    if len(text) < 2:
        return await message.answer("Текст слишком короткий.")
    data = await state.get_data()
    await state.clear()
    uid = message.from_user.id
    items = await load_smart_texts(uid)
    items.append(text)
    await save_smart_texts(uid, items)
    await _finish_smart_add(message, data, uid)


@router.callback_query(F.data == "stmpl_delall")
async def stmpl_delete_all(call: CallbackQuery, state: FSMContext) -> None:
    await save_smart_texts(call.from_user.id, [])
    await call.answer("Удалено")
    await smart_presets_menu(call, state)


@router.callback_query(F.data == "stmpl_del")
async def stmpl_del_pick(call: CallbackQuery) -> None:
    uid = call.from_user.id
    items = await load_smart_texts(uid)
    if not items:
        return await call.answer("Пусто")
    await cq_edit_text(
        call,
        "🗑 Выбери пресет для удаления:",
        reply_markup=text_presets_pick_kb(len(items), "stmpl_del", "smart_presets_menu"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("stmpl_del:"))
async def stmpl_del_idx(call: CallbackQuery, state: FSMContext) -> None:
    idx = int(call.data.split(":")[1])
    uid = call.from_user.id
    items = await load_smart_texts(uid)
    if idx < 0 or idx >= len(items):
        return await call.answer("Не найден", show_alert=True)
    items.pop(idx)
    await save_smart_texts(uid, items)
    await call.answer("Удалено")
    await smart_presets_menu(call, state)


@router.callback_query(F.data == "stmpl_edit")
async def stmpl_edit_pick(call: CallbackQuery, state: FSMContext) -> None:
    uid = call.from_user.id
    items = await load_smart_texts(uid)
    if not items:
        return await call.answer("Пусто")
    await state.update_data(
        _menu_chat_id=call.message.chat.id, _menu_msg_id=call.message.message_id
    )
    await cq_edit_text(
        call,
        "✏️ Выбери пресет для изменения:",
        reply_markup=text_presets_pick_kb(len(items), "stmpl_edit", "smart_presets_menu"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("stmpl_edit:"))
async def stmpl_edit_choose(call: CallbackQuery, state: FSMContext) -> None:
    idx = int(call.data.split(":")[1])
    uid = call.from_user.id
    items = await load_smart_texts(uid)
    if idx < 0 or idx >= len(items):
        return await call.answer("Не найден", show_alert=True)
    await state.update_data(idx=idx)
    await state.set_state(SmartTmplEdit.text)
    await call.message.answer("✏️ Отправь новый текст пресета одним сообщением.")
    await call.answer()


@router.message(SmartTmplEdit.text)
async def stmpl_edit_text(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        await state.clear()
        return
    text = (message.text or "").strip()[:MAX_TEXT_LEN]
    if len(text) < 2:
        return await message.answer("Текст слишком короткий.")
    data = await state.get_data()
    idx = int(data.get("idx", -1))
    await state.clear()
    uid = message.from_user.id
    items = await load_smart_texts(uid)
    if idx < 0 or idx >= len(items):
        return await message.answer("Пресет не найден.")
    items[idx] = text
    await save_smart_texts(uid, items)
    await _hide_old_menu_markup(message.bot, data)
    await message.answer("✅ Сохранено.")
    await _send_smart_menu_message(message, uid)

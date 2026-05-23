from __future__ import annotations

import os
import sys

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from keyboards.main_menu import main_menu_kb_for
from middlewares.bot_access import invalidate_access_cache
from services.bot_roles import user_is_admin as is_admin
from services.bot_users import (
    count_bot_users,
    get_or_create_bot_user,
    list_admin_telegram_ids,
    list_bot_user_ids,
    set_bot_user_flags,
    user_stats_for_telegram,
)

router = Router(name="admin_panel")


class AdminState(StatesGroup):
    waiting_grant_admin = State()
    waiting_revoke_admin = State()
    waiting_allow = State()
    waiting_deny = State()
    waiting_stats = State()


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика пользователей",
                    callback_data="admin_user_stats",
                )
            ],
            [InlineKeyboardButton(text="✅ Выдать доступ", callback_data="admin_allow")],
            [InlineKeyboardButton(text="⛔ Удалить доступ", callback_data="admin_deny")],
            [
                InlineKeyboardButton(
                    text="👑 Выдать админ права",
                    callback_data="admin_grant_admin",
                )
            ],
            [InlineKeyboardButton(text="🔄 Рестарт", callback_data="admin_restart")],
        ]
    )


@router.message(F.text.in_({"/admin", "👑 Админ-панель", "🔥 Админ-панель"}))
async def open_admin(message: Message) -> None:
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к админ-панели.")
        return
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await callback.message.edit_text(
            "👑 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()


@router.callback_query(F.data == "admin_allow")
async def admin_allow_begin(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminState.waiting_allow)
    await callback.message.edit_text(
        "✅ <b>Выдать доступ</b>\n\nОтправь Telegram ID пользователя.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_allow)
async def admin_allow_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    try:
        tid = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Это не число. Отправь Telegram ID.")
        return
    await get_or_create_bot_user(tid)
    await set_bot_user_flags(tid, access_granted=True, is_banned=False)
    invalidate_access_cache(tid)
    await state.clear()
    await message.answer(f"✅ Доступ выдан: <code>{tid}</code>", parse_mode="HTML")
    try:
        await message.bot.send_message(
            tid,
            "✅ Вам выдан доступ к боту. Нажмите /start.",
            reply_markup=await main_menu_kb_for(tid),
        )
    except Exception:
        pass
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_deny")
async def admin_deny_begin(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminState.waiting_deny)
    await callback.message.edit_text(
        "⛔ <b>Удалить доступ</b>\n\nОтправь Telegram ID пользователя.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_deny)
async def admin_deny_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    try:
        tid = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Это не число. Отправь Telegram ID.")
        return
    await get_or_create_bot_user(tid)
    await set_bot_user_flags(tid, access_granted=False, is_banned=False)
    invalidate_access_cache(tid)
    await state.clear()
    await message.answer(f"⛔ Доступ удалён: <code>{tid}</code>", parse_mode="HTML")
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_user_stats")
async def admin_stats_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    rows = await list_bot_user_ids(limit=500)
    ids = [str(x) for x in rows[:30]]
    text = "📊 <b>Статистика пользователей</b>\n\n"
    text += f"Всего пользователей в БД: <b>{await count_bot_users()}</b>\n\n"
    if ids:
        text += "Последние Telegram ID:\n" + "\n".join(f"• <code>{i}</code>" for i in ids)
        if len(rows) > 30:
            text += f"\n… и ещё {len(rows) - 30}"
    else:
        text += "Пока нет пользователей в БД."
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 Проверить", callback_data="admin_user_stats_check"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_user_stats_check")
async def admin_stats_begin(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminState.waiting_stats)
    await callback.message.edit_text(
        "📊 <b>Статистика пользователя</b>\n\nОтправь Telegram ID пользователя.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="admin_user_stats"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_stats)
async def admin_stats_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    try:
        tid = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Это не число. Отправь Telegram ID.")
        return
    st = await user_stats_for_telegram(tid)
    await state.clear()
    access = "✅ есть" if st["has_access"] else "⛔ нет"
    await message.answer(
        "📊 <b>Статистика</b>\n"
        f"Telegram ID: <code>{tid}</code>\n"
        f"Доступ: <b>{access}</b>\n"
        f"Админ: <b>{'да' if st['is_admin'] else 'нет'}</b>\n\n"
        f"📮 Почтовых аккаунтов: <b>{st['accounts']}</b>\n"
        f"📧 Валидных лидов: <b>{st['validated']}</b>\n"
        f"✉️ Отправлено писем: <b>{st['sent']}</b>",
        parse_mode="HTML",
    )
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=admin_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_grant_admin")
async def admin_admins_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    rows = await list_admin_telegram_ids()
    ids = [str(x) for x in rows[:30]]
    text = "👑 <b>Админ-права</b>\n\n"
    text += f"Админов в БД: <b>{len(rows)}</b>\n\n"
    if ids:
        text += "Админы (Telegram ID):\n" + "\n".join(f"• <code>{i}</code>" for i in ids)
        if len(rows) > 30:
            text += f"\n… и ещё {len(rows) - 30}"
    else:
        text += "В БД админов нет (кроме ADMIN_IDS в config)."
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Выдать", callback_data="admin_admin_grant_begin")],
            [InlineKeyboardButton(text="➖ Забрать", callback_data="admin_admin_revoke_begin")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_admin_grant_begin")
async def admin_grant_admin_begin(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminState.waiting_grant_admin)
    await callback.message.edit_text(
        "➕ <b>Выдать админ права</b>\n\nОтправь Telegram ID пользователя.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="admin_grant_admin"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_admin_revoke_begin")
async def admin_revoke_admin_begin(callback: CallbackQuery, state: FSMContext) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminState.waiting_revoke_admin)
    await callback.message.edit_text(
        "➖ <b>Забрать админ права</b>\n\nОтправь Telegram ID пользователя.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data="admin_grant_admin"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminState.waiting_grant_admin)
async def admin_grant_admin_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    try:
        tid = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Неверный ID. Отправь число.")
        return
    await get_or_create_bot_user(tid)
    await set_bot_user_flags(tid, is_admin=True, access_granted=True, is_banned=False)
    invalidate_access_cache(tid)
    await state.clear()
    await message.answer(
        f"✅ Админ права выданы пользователю <code>{tid}</code>.",
        parse_mode="HTML",
    )
    try:
        await message.bot.send_message(
            tid,
            "👑 Вам выданы права администратора.\n"
            "Меню обновлено — доступна «👑 Админ-панель».",
            reply_markup=await main_menu_kb_for(tid),
        )
    except Exception:
        await message.answer(
            f"⚠️ Не удалось отправить меню пользователю <code>{tid}</code>. "
            "Пусть нажмёт /start.",
            parse_mode="HTML",
        )
    await open_admin(message)


@router.message(AdminState.waiting_revoke_admin)
async def admin_revoke_admin_finish(message: Message, state: FSMContext) -> None:
    if not await is_admin(message.from_user.id):
        return
    try:
        tid = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Неверный ID. Отправь число.")
        return
    await get_or_create_bot_user(tid)
    await set_bot_user_flags(tid, is_admin=False)
    invalidate_access_cache(tid)
    await state.clear()
    await message.answer(
        f"➖ Админ права сняты у <code>{tid}</code>.",
        parse_mode="HTML",
    )
    await open_admin(message)


@router.callback_query(F.data == "admin_restart")
async def admin_restart(callback: CallbackQuery) -> None:
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Рестарт…")
    os.execv(sys.executable, [sys.executable] + sys.argv)

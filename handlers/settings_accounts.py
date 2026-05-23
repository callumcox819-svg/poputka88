"""📧 E-mail — список аккаунтов из настроек (упрощённо от happy88)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database import count_smtp_accounts, delete_smtp_account, list_smtp_accounts
from utils.callback_edit import cq_edit_text

router = Router()

PAGE_SIZE = 10


def _accounts_kb(accounts: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for acc in accounts:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📧 {acc['email']}",
                    callback_data=f"acc_info:{acc['id']}",
                ),
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"acc_del:{acc['id']}:{page}",
                ),
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"acc_page:{page - 1}")
        )
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(
            InlineKeyboardButton(text="След. ➡️", callback_data=f"acc_page:{page + 1}")
        )
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_accounts_menu(target: CallbackQuery, user_id: int, page: int = 1) -> None:
    all_acc = await list_smtp_accounts(user_id)
    total = len(all_acc)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_accounts = all_acc[start : start + PAGE_SIZE]

    if total:
        text = (
            f"📬 <b>Почтовые аккаунты</b>\n\n"
            f"Всего: <b>{total}</b> · страница <b>{page}/{total_pages}</b>\n\n"
            "🗑 — удалить аккаунт.\n"
            "Добавить: «⚡ Быстрое добавление» на главной."
        )
    else:
        text = (
            "📬 <b>Почтовые аккаунты</b>\n\n"
            "Пока пусто. Нажмите «⚡ Быстрое добавление» на главной клавиатуре."
        )

    kb = _accounts_kb(page_accounts, page, total_pages)

    await cq_edit_text(target, text, reply_markup=kb)


@router.callback_query(F.data == "settings_accounts")
async def open_accounts(callback: CallbackQuery) -> None:
    await callback.answer()
    await render_accounts_menu(callback, callback.from_user.id, page=1)


@router.callback_query(F.data.startswith("acc_page:"))
async def acc_page(callback: CallbackQuery) -> None:
    try:
        page = int((callback.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        return await callback.answer("Ошибка страницы", show_alert=True)
    await render_accounts_menu(callback, callback.from_user.id, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("acc_del:"))
async def acc_del(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    try:
        acc_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 1
    except (IndexError, ValueError):
        return await callback.answer("Ошибка", show_alert=True)
    ok = await delete_smtp_account(callback.from_user.id, acc_id)
    await callback.answer("Удалено" if ok else "Не найдено", show_alert=not ok)
    await render_accounts_menu(callback, callback.from_user.id, page=page)


@router.callback_query(F.data.startswith("acc_info:"))
async def acc_info(callback: CallbackQuery) -> None:
    await callback.answer("Нажмите 🗑 справа, чтобы удалить.", show_alert=False)


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()

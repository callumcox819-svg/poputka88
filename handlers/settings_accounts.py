"""📧 Почтовые аккаунты — список и обслуживание."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database import (
    delete_all_smtp_accounts,
    delete_inactive_smtp_accounts,
    delete_smtp_account,
    list_all_smtp_accounts,
)
from services.account_status_check import check_accounts_status_parallel
from utils.bg_jobs import is_running as bg_is_running, start as bg_start
from utils.callback_edit import cq_edit_text
from utils.text_html import e

router = Router()
logger = logging.getLogger(__name__)

PAGE_SIZE = 10


def _account_emoji(acc: dict) -> str:
    if not int(acc.get("enabled", 1)):
        return "🔴"
    if not int(acc.get("smtp_enabled", 1)):
        return "🟡"
    return "📧"


def _accounts_kb(accounts: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for acc in accounts:
        tag = _account_emoji(acc)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{tag} {acc['email']}",
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
        [
            InlineKeyboardButton(
                text="📥 Проверить входящие (IMAP)",
                callback_data="acc_imap_check",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 Удалить неактивные",
                callback_data="acc_delete_inactive",
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="🗑 Удалить все почты", callback_data="acc_delete_all")]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔍 Проверить статус почт",
                callback_data="acc_check_status",
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_accounts_menu(target: CallbackQuery, user_id: int, page: int = 1) -> None:
    all_acc = await list_all_smtp_accounts(user_id)
    total = len(all_acc)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_accounts = all_acc[start : start + PAGE_SIZE]

    active = sum(1 for a in all_acc if int(a.get("enabled", 1)))
    smtp_ok = sum(
        1 for a in all_acc if int(a.get("enabled", 1)) and int(a.get("smtp_enabled", 1))
    )

    if total:
        text = (
            f"📬 <b>Почтовые аккаунты</b>\n\n"
            f"Всего: <b>{total}</b> · активных IMAP: <b>{active}</b> · SMTP OK: <b>{smtp_ok}</b>\n"
            f"Страница <b>{page}/{total_pages}</b>\n\n"
            "🔴 — отключён (неверный пароль)\n"
            "🟡 — только IMAP (SMTP заблокирован)\n"
            "📧 — рассылка и входящие\n\n"
            "🗑 справа — удалить один ящик."
        )
    else:
        text = (
            "📬 <b>Почтовые аккаунты</b>\n\n"
            "Пока пусто. Нажмите «⚡ Быстрое добавление» на главной клавиатуре."
        )

    await cq_edit_text(target, text, reply_markup=_accounts_kb(page_accounts, page, total_pages))


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


@router.callback_query(F.data == "acc_delete_inactive")
async def acc_delete_inactive(callback: CallbackQuery) -> None:
    n = await delete_inactive_smtp_accounts(callback.from_user.id)
    if not n:
        await callback.answer(
            "Нет неактивных (🔴). Ящики с 🟡 SMTP-block не удаляются.",
            show_alert=True,
        )
    else:
        await callback.answer(f"Удалено неактивных: {n}")
    await render_accounts_menu(callback, callback.from_user.id, page=1)


@router.callback_query(F.data == "acc_delete_all")
async def acc_delete_all_confirm(callback: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, удалить ВСЕ",
                    callback_data="acc_delete_all_yes",
                )
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="settings_accounts")],
        ]
    )
    await callback.message.edit_text(
        "⚠️ <b>Удалить все почтовые аккаунты?</b>\n\n"
        "Будут удалены все ящики из списка. Это нельзя отменить.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "acc_delete_all_yes")
async def acc_delete_all_yes(callback: CallbackQuery) -> None:
    n = await delete_all_smtp_accounts(callback.from_user.id)
    await callback.answer(f"Удалено: {n}")
    await render_accounts_menu(callback, callback.from_user.id, page=1)


@router.callback_query(F.data == "acc_imap_check")
async def acc_imap_check(callback: CallbackQuery, bot: Bot) -> None:
    from handlers.settings import run_imap_check

    await callback.answer("Проверяю IMAP…")
    await run_imap_check(bot, callback.message.chat.id, callback.from_user.id)


@router.callback_query(F.data == "acc_check_status")
async def acc_check_status(callback: CallbackQuery, bot: Bot) -> None:
    uid = callback.from_user.id
    if bg_is_running(uid, "accounts_status_check"):
        return await callback.answer("Проверка уже идёт…", show_alert=True)

    accounts = await list_all_smtp_accounts(uid, with_secrets=True)
    if not accounts:
        return await callback.answer("Нет аккаунтов.", show_alert=True)

    await callback.answer("Запускаю проверку SMTP + IMAP…")
    status_msg = await callback.message.answer(
        f"⏳ <b>Проверка почт</b>\n\n0/{len(accounts)}",
        parse_mode="HTML",
    )

    async def _job() -> None:
        last_edit = 0.0

        async def on_progress(done: int, total: int, email: str | None) -> None:
            nonlocal last_edit
            now = asyncio.get_running_loop().time()
            if done < total and (now - last_edit) < 0.5:
                return
            last_edit = now
            em = f"\n<code>{e(email or '')}</code>" if email else ""
            try:
                await status_msg.edit_text(
                    f"⏳ <b>Проверка почт</b> (SMTP + IMAP)\n\n{done}/{total}{em}",
                    parse_mode="HTML",
                )
            except TelegramBadRequest as ex:
                if "message is not modified" not in str(ex).lower():
                    raise

        try:
            results = await check_accounts_status_parallel(
                uid,
                accounts,
                on_progress=on_progress,
                update_db=True,
            )
            ok_smtp = sum(1 for r in results if r.get("smtp_status") == "active")
            blocked = sum(1 for r in results if r.get("smtp_status") == "smtp_blocked")
            invalid = sum(1 for r in results if r.get("smtp_status") == "invalid")
            imap_ok = sum(1 for r in results if r.get("imap_ok"))

            lines = [
                "✅ <b>Проверка завершена</b>\n",
                f"🟢 SMTP OK: <b>{ok_smtp}</b>",
                f"🟡 SMTP блок: <b>{blocked}</b>",
                f"🔴 неверный пароль (отключены): <b>{invalid}</b>",
                f"✅ IMAP OK: <b>{imap_ok}</b>\n",
            ]
            for r in results[:20]:
                lines.append(r.get("line") or "")
                for d in r.get("details") or []:
                    lines.append(f"   {d}")
            if len(results) > 20:
                lines.append(f"\n… и ещё {len(results) - 20}")

            text = "\n".join(lines)
            try:
                await status_msg.edit_text(text, parse_mode="HTML")
            except TelegramBadRequest:
                await bot.send_message(callback.message.chat.id, text, parse_mode="HTML")

            await render_accounts_menu(callback, uid, page=1)
        except Exception as exc:
            logger.exception("acc_check_status failed")
            await status_msg.edit_text(f"❌ Ошибка: {e(str(exc))[:300]}", parse_mode="HTML")

    if not bg_start(uid, "accounts_status_check", _job()):
        await callback.answer("Проверка уже идёт…", show_alert=True)


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()

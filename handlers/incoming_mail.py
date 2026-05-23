"""Кнопки под карточкой входящего письма."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Settings
from database import get_incoming_mail, save_incoming_gag_link
from handlers.states import MailReply
from services.gag_link import create_gag_link_for_incoming
from services.gag_user import GagNotConfiguredError
from services.html_incoming_send import send_incoming_html
from services.reply_notify import (
    ReplyNotifyCtx,
    html_attachment_filename,
    notify_reply_sent,
)
from services.incoming_card import build_card_from_mail_row, clean_mail_body_for_card
from services.translate import strip_html, translate_to_ru
from utils.bg_jobs import is_running as bg_is_running, start as bg_start

logger = logging.getLogger(__name__)
router = Router()

REPLY_CHOICE_TEXT = (
    "Что отправить?\n\n"
    "<i>HTML: прокси + GAG-ссылка. Имя (From) и тема — строго из "
    "⚙️ → 👤 Имя для спуфинга (не из входящего письма).</i>"
)


def _kb_reply_choice(mail_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🧩 Отправить HTML", callback_data=f"mail_reply_mode:html:{mail_id}")
    b.button(text="🚫 Отмена", callback_data=f"mail_reply_mode:cancel:{mail_id}")
    b.adjust(1)
    return b.as_markup()


def _kb_html_pick(mail_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 GO", callback_data=f"mail_reply_html:go:{mail_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📣 PUSH", callback_data=f"mail_reply_html:push:{mail_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 SMS", callback_data=f"mail_reply_html:sms:{mail_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 BACK", callback_data=f"mail_reply_html:back:{mail_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Отмена", callback_data=f"mail_reply_mode:cancel:{mail_id}"
                )
            ],
        ]
    )


@router.callback_query(F.data.startswith("mail_translate_stub:"))
async def cb_mail_translate_stub(callback: CallbackQuery) -> None:
    await callback.answer("Дождитесь нового входящего письма.", show_alert=True)


@router.callback_query(F.data.startswith("goo_link_stub:"))
async def cb_goo_link_stub(callback: CallbackQuery) -> None:
    await callback.answer("Дождитесь нового входящего письма.", show_alert=True)


@router.callback_query(F.data.startswith("mail_reply_stub:"))
async def cb_mail_reply_stub(callback: CallbackQuery) -> None:
    await callback.answer("Дождитесь нового входящего письма.", show_alert=True)


@router.callback_query(F.data.startswith("mail_html_menu:"))
async def cb_mail_html_menu(callback: CallbackQuery) -> None:
    try:
        mail_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    mail = await get_incoming_mail(mail_id, uid)
    if not mail:
        return await callback.answer("Письмо не найдено", show_alert=True)
    if not (mail.get("generated_link") or "").strip():
        return await callback.answer(
            "Сначала нажмите «🔗 Создать ссылку»", show_alert=True
        )

    await callback.message.answer(
        "🧩 <b>HTML-шаблон</b>\nСсылка GAG подставится в кнопку письма.",
        parse_mode="HTML",
        reply_markup=_kb_html_pick(mail_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mail_reply:"))
async def cb_mail_reply(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        mail_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    mail = await get_incoming_mail(mail_id, uid)
    if not mail:
        return await callback.answer("Письмо не найдено", show_alert=True)

    anchor = mail.get("tg_message_id") or callback.message.message_id
    await state.set_state(MailReply.waiting_choice)
    ui = await callback.message.answer(
        REPLY_CHOICE_TEXT,
        parse_mode="HTML",
        reply_markup=_kb_reply_choice(mail_id),
    )
    await state.update_data(
        mail_id=mail_id,
        ui_message_id=ui.message_id,
        anchor_message_id=int(anchor),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mail_reply_mode:"))
async def cb_mail_reply_mode(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        _, mode, mail_id_s = (callback.data or "").split(":", 2)
        mail_id = int(mail_id_s)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    data = await state.get_data()

    if mode == "cancel":
        ui_id = data.get("ui_message_id")
        if ui_id:
            try:
                await callback.bot.delete_message(callback.message.chat.id, int(ui_id))
            except Exception:
                pass
        await state.clear()
        return await callback.answer("Отменено")

    if mode == "html":
        mail = await get_incoming_mail(mail_id, uid)
        if not mail:
            return await callback.answer("Письмо не найдено", show_alert=True)
        if not (mail.get("generated_link") or "").strip():
            return await callback.answer(
                "Сначала «🔗 Создать ссылку» — без неё HTML не отправляется.",
                show_alert=True,
            )
        try:
            await callback.message.edit_text(
                "🧩 <b>Выберите шаблон HTML</b>",
                parse_mode="HTML",
                reply_markup=_kb_html_pick(mail_id),
            )
        except Exception:
            ui = await callback.message.answer(
                "🧩 <b>Выберите шаблон HTML</b>",
                parse_mode="HTML",
                reply_markup=_kb_html_pick(mail_id),
            )
            await state.update_data(ui_message_id=ui.message_id)
        return await callback.answer()

    await callback.answer()


@router.callback_query(F.data.startswith("mail_reply_html:"))
async def cb_mail_reply_html(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    try:
        _, kind, mail_id_s = (callback.data or "").split(":", 2)
        mail_id = int(mail_id_s)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    mail = await get_incoming_mail(mail_id, uid)
    if not mail:
        return await callback.answer("Письмо не найдено", show_alert=True)
    if not (mail.get("generated_link") or "").strip():
        return await callback.answer(
            "Сначала «🔗 Создать ссылку»", show_alert=True
        )

    if bg_is_running(uid, "smtp"):
        return await callback.answer("⏳ Отправка уже идёт…", show_alert=True)

    await callback.answer(f"⏳ Отправляю HTML ({kind.upper()})…", show_alert=False)
    msg = callback.message
    bot = callback.bot
    data = await state.get_data()
    anchor = int(
        data.get("anchor_message_id")
        or mail.get("tg_message_id")
        or msg.message_id
    )
    cleanup: list[int] = []
    ui_id = data.get("ui_message_id")
    if ui_id:
        cleanup.append(int(ui_id))
    if msg.message_id and int(msg.message_id) not in cleanup:
        cleanup.append(int(msg.message_id))

    async def _job() -> None:
        result = await send_incoming_html(
            settings, uid, mail_id=mail_id, kind=kind
        )
        if result.ok and result.html_body:
            ctx = ReplyNotifyCtx(
                anchor_message_id=anchor,
                to_email=result.to_email,
                account_email=result.account_email,
                is_html=True,
                html_attachment=result.html_body,
                html_filename=html_attachment_filename(result.subject),
                cleanup_message_ids=cleanup,
            )
            await notify_reply_sent(bot, msg.chat.id, ctx)
        else:
            err = result.error or "Ошибка отправки"
            try:
                await bot.send_message(
                    msg.chat.id,
                    f"❌ {err}",
                    parse_mode="HTML",
                    reply_to_message_id=anchor,
                )
            except Exception:
                await bot.send_message(msg.chat.id, f"❌ {err}", parse_mode="HTML")
        await state.clear()

    if not bg_start(uid, "smtp", _job()):
        await callback.answer("⏳ Отправка уже идёт…", show_alert=True)


@router.callback_query(F.data.startswith("mail_translate:"))
async def cb_mail_translate(callback: CallbackQuery) -> None:
    try:
        mail_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    mail = await get_incoming_mail(mail_id, uid)
    if not mail:
        return await callback.answer("Письмо не найдено", show_alert=True)

    body_full = (mail.get("body") or "").strip()
    shown = strip_html(clean_mail_body_for_card(body_full))
    if not shown:
        return await callback.answer("Нет текста для перевода", show_alert=True)

    if bg_is_running(uid, "translate"):
        return await callback.answer("⏳ Перевод уже выполняется…", show_alert=True)
    await callback.answer("Перевожу…", show_alert=False)

    msg = callback.message
    bot = callback.bot

    async def _job() -> None:
        translated = await translate_to_ru(shown, preserve_blocks=True)
        if not translated:
            try:
                await bot.send_message(
                    msg.chat.id,
                    "❌ Не удалось перевести. Проверьте DEEPL_API_KEY или попробуйте позже.",
                    reply_to_message_id=msg.message_id,
                )
            except Exception:
                pass
            return
        mail2 = await get_incoming_mail(mail_id, uid)
        if not mail2 or not msg:
            return
        text, kb = build_card_from_mail_row(mail2, translation=translated)
        try:
            await msg.edit_text(
                text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            await bot.send_message(
                msg.chat.id,
                text,
                reply_markup=kb,
                parse_mode="HTML",
                reply_to_message_id=msg.message_id,
                disable_web_page_preview=True,
            )

    if not bg_start(uid, "translate", _job()):
        await callback.answer("⏳ Перевод уже выполняется…", show_alert=True)


@router.callback_query(F.data.startswith("goo_mail:"))
async def cb_goo_mail(callback: CallbackQuery) -> None:
    try:
        mail_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    if bg_is_running(uid, "gag_link"):
        return await callback.answer("⏳ Ссылка уже создаётся…", show_alert=True)
    await callback.answer("⏳ Создаю ссылку…", show_alert=False)

    msg = callback.message
    bot = callback.bot

    async def _job() -> None:
        mail = await get_incoming_mail(mail_id, uid)
        if not mail or not msg:
            return
        contact = (mail.get("from_email") or "").strip().lower()
        try:
            await create_gag_link_for_incoming(
                uid,
                contact_email=contact,
                lead_id=mail.get("lead_id"),
                incoming_mail_id=mail_id,
            )
        except GagNotConfiguredError as exc:
            await bot.send_message(
                msg.chat.id,
                f"❌ {exc}",
                parse_mode="HTML",
                reply_to_message_id=msg.message_id,
            )
            return
        except Exception as exc:
            logger.exception("goo_mail mail_id=%s", mail_id)
            await save_incoming_gag_link(
                mail_id, uid, url="", error=str(exc)[:400]
            )
            await bot.send_message(
                msg.chat.id,
                f"❌ Ошибка: {str(exc)[:400]}",
                reply_to_message_id=msg.message_id,
            )
            return

        mail2 = await get_incoming_mail(mail_id, uid)
        if not mail2:
            return
        text, kb = build_card_from_mail_row(mail2)
        try:
            await msg.edit_text(
                text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            await bot.send_message(
                msg.chat.id,
                text,
                reply_markup=kb,
                parse_mode="HTML",
                reply_to_message_id=msg.message_id,
                disable_web_page_preview=True,
            )

    if not bg_start(uid, "gag_link", _job()):
        await callback.answer("⏳ Ссылка уже создаётся…", show_alert=True)

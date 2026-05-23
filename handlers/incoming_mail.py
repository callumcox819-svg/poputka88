"""Кнопки под карточкой входящего письма."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from database import get_incoming_mail, save_incoming_gag_link
from services.gag_link import create_gag_link_for_incoming
from services.gag_user import GagNotConfiguredError
from services.incoming_card import build_card_from_mail_row, clean_mail_body_for_card
from services.translate import strip_html, translate_to_ru
from utils.bg_jobs import is_running as bg_is_running, start as bg_start
logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("mail_translate_stub:"))
async def cb_mail_translate_stub(callback: CallbackQuery) -> None:
    await callback.answer("Дождитесь нового входящего письма.", show_alert=True)


@router.callback_query(F.data.startswith("goo_link_stub:"))
async def cb_goo_link_stub(callback: CallbackQuery) -> None:
    await callback.answer("Дождитесь нового входящего письма.", show_alert=True)


@router.callback_query(F.data.startswith("mail_reply:"))
async def cb_mail_reply(callback: CallbackQuery) -> None:
    await callback.answer(
        "Ответ через рассылку — выберите шаблон в меню «Рассылка».",
        show_alert=True,
    )


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
            result = await create_gag_link_for_incoming(
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

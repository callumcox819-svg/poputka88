"""Кнопки под карточкой входящего письма."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Settings
from database import (
    get_gag_generated_link,
    get_incoming_mail,
    get_validated_lead_by_id,
    inherit_incoming_gag_link,
    save_incoming_gag_link,
    update_incoming_mail_lead_snapshot,
)
from handlers.states import LeadPrice, MailReply
from services.gag_link import (
    create_gag_link_for_incoming,
    regenerate_gag_link_for_lead,
)
from services.gag_link_card import (
    build_link_card_caption,
    build_link_card_keyboard,
    send_generated_link_card,
)
from services.gag_user import GagNotConfiguredError, load_gag_profile
from services.html_incoming_send import send_incoming_html
from services.incoming_reply_send import send_incoming_text_reply
from services.outbound_lang import seller_outbound_text_error
from services.presets import TemplateItem, load_templates
from services.reply_notify import (
    ReplyNotifyCtx,
    html_attachment_filename,
    notify_reply_sent,
)
from services.incoming_card import build_card_from_mail_row, clean_mail_body_for_card
from services.translate import strip_html, translate_to_ru
from utils.bg_jobs import is_running as bg_is_running, start as bg_start
from utils.text_html import e

logger = logging.getLogger(__name__)
router = Router()


def _format_gag_error(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return (
            "Таймаут GAG API (сервер не ответил вовремя). "
            "Попробуйте «Создать ссылку» ещё раз через 10–20 с."
        )
    if isinstance(exc, asyncio.CancelledError):
        return (
            "Запрос прерван (перезапуск бота на сервере). "
            "Нажмите «Создать ссылку» снова."
        )
    text = str(exc).strip()
    if not text:
        text = type(exc).__name__
    return text[:400]


def _gag_recreate_keyboard(mail_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да", callback_data=f"gag_recreate:yes:{mail_id}")
    b.button(text="❌ Нет", callback_data=f"gag_recreate:no:{mail_id}")
    b.adjust(2)
    return b.as_markup()


async def _refresh_incoming_card(msg: Message, mail_id: int, user_id: int) -> None:
    mail = await get_incoming_mail(mail_id, user_id)
    if not mail:
        return
    text, kb = build_card_from_mail_row(mail)
    try:
        await msg.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        pass


async def _show_gag_link_card(
    bot,
    msg: Message,
    mail_id: int,
    user_id: int,
) -> None:
    mail = await get_incoming_mail(mail_id, user_id)
    if not mail:
        return
    link = (mail.get("generated_link") or "").strip()
    if not link:
        return

    await _refresh_incoming_card(msg, mail_id, user_id)

    profile = await load_gag_profile(user_id)
    item_link = ""
    lead_id = mail.get("lead_id")
    if lead_id:
        lead = await get_validated_lead_by_id(user_id, int(lead_id))
        if lead:
            item_link = (lead.get("item_link") or "").strip()
    await send_generated_link_card(
        bot,
        msg.chat.id,
        offer_title=(mail.get("product_title") or "").strip(),
        offer_price=(mail.get("offer_price") or "").strip(),
        photo_url=(mail.get("photo_url") or "").strip(),
        profile_title=profile.title,
        service_label=(mail.get("service_label") or "").strip(),
        item_link=item_link,
        link=link,
        anchor_message_id=int(msg.message_id),
        lead_id=int(lead_id) if lead_id else None,
    )


async def _create_gag_link_job(
    bot,
    msg: Message,
    mail_id: int,
    user_id: int,
    *,
    force_recreate: bool = False,
) -> None:
    mail = await get_incoming_mail(mail_id, user_id)
    if not mail:
        return
    contact = (mail.get("from_email") or "").strip().lower()

    if not force_recreate:
        existing = await get_gag_generated_link(
            user_id, incoming_id=mail_id, seller_email=contact
        )
        if (existing or "").strip():
            await inherit_incoming_gag_link(mail_id, user_id, contact)
            await _refresh_incoming_card(msg, mail_id, user_id)
            await bot.send_message(
                msg.chat.id,
                "ℹ️ Ссылка для этого продавца уже есть.\n\n"
                "Пересоздать ссылку? (текущий сервис из 👤 Профиль)",
                reply_markup=_gag_recreate_keyboard(mail_id),
                reply_to_message_id=msg.message_id,
            )
            return

    try:
        lead_id = mail.get("lead_id")
        if force_recreate and lead_id:
            await regenerate_gag_link_for_lead(user_id, int(lead_id))
        else:
            await create_gag_link_for_incoming(
                user_id,
                contact_email=contact,
                lead_id=lead_id,
                incoming_mail_id=mail_id,
                subject=(mail.get("subject") or ""),
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
        err_text = _format_gag_error(exc)
        logger.exception("gag link mail_id=%s force=%s", mail_id, force_recreate)
        await save_incoming_gag_link(mail_id, user_id, url="", error=err_text[:400])
        await bot.send_message(
            msg.chat.id,
            f"❌ {err_text}",
            reply_to_message_id=msg.message_id,
        )
        return

    await _show_gag_link_card(bot, msg, mail_id, user_id)
    if force_recreate:
        await bot.send_message(
            msg.chat.id,
            "✅ Ссылка пересоздана (сервис из профиля).",
            reply_to_message_id=msg.message_id,
        )


REPLY_CHOICE_TEXT = (
    "Введите текст сообщением (DE/EN) или выберите пресет / HTML.\n\n"
    "<i>HTML: прокси + GAG-ссылка. Имя (From) и тема — строго из "
    "⚙️ → 👤 Имя для спуфинга (не из входящего письма).</i>\n"
    "<i>На русском продавцам писать нельзя.</i>"
)


def _kb_reply_choice(mail_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 Отправить пресет",
                    callback_data=f"mail_reply_mode:preset:{mail_id}",
                ),
                InlineKeyboardButton(
                    text="🧩 Отправить HTML",
                    callback_data=f"mail_reply_mode:html:{mail_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Отмена",
                    callback_data=f"mail_reply_mode:cancel:{mail_id}",
                )
            ],
        ]
    )


def _kb_preset_pick(items: list[TemplateItem], mail_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, t in enumerate(items[:30]):
        label = (t.title or f"Пресет #{i + 1}").strip()[:40]
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"mail_tmpl_send:{i}:{mail_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"mail_reply_mode:back:{mail_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
                    text="🚫 Отмена", callback_data=f"mail_reply_mode:back:{mail_id}"
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
    await state.set_state(MailReply.waiting_text)
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

    if mode == "back":
        await state.set_state(MailReply.waiting_text)
        try:
            await callback.message.edit_text(
                REPLY_CHOICE_TEXT,
                parse_mode="HTML",
                reply_markup=_kb_reply_choice(mail_id),
            )
        except Exception:
            ui = await callback.message.answer(
                REPLY_CHOICE_TEXT,
                parse_mode="HTML",
                reply_markup=_kb_reply_choice(mail_id),
            )
            await state.update_data(ui_message_id=ui.message_id)
        return await callback.answer()

    if mode == "preset":
        items = await load_templates(uid)
        if not items:
            return await callback.answer(
                "Нет шаблонов. Добавьте в ⚡ Шаблоны", show_alert=True
            )
        try:
            await callback.message.edit_text(
                "🧾 <b>Ваши шаблоны</b>\n\nНажмите пресет для отправки:",
                parse_mode="HTML",
                reply_markup=_kb_preset_pick(items, mail_id),
            )
        except Exception:
            ui = await callback.message.answer(
                "🧾 <b>Ваши шаблоны</b>\n\nНажмите пресет для отправки:",
                parse_mode="HTML",
                reply_markup=_kb_preset_pick(items, mail_id),
            )
            await state.update_data(ui_message_id=ui.message_id)
        return await callback.answer()

    if mode == "html":
        mail = await get_incoming_mail(mail_id, uid)
        if not mail:
            return await callback.answer("Письмо не найдено", show_alert=True)
        gag_link = await get_gag_generated_link(
            uid,
            incoming_id=mail_id,
            seller_email=mail.get("from_email"),
        )
        if not (gag_link or "").strip():
            return await callback.answer(
                "Сначала «🔗 Создать ссылку» — без неё HTML не отправляется.",
                show_alert=True,
            )
        if not (mail.get("generated_link") or "").strip():
            await inherit_incoming_gag_link(mail_id, uid, mail.get("from_email") or "")
        to_em = (mail.get("from_email") or "").strip()
        html_text = (
            "🧩 <b>HTML</b>\n\n"
            f"Кому: <code>{to_em or '—'}</code>\n"
            f"От ящика: <code>{(mail.get('account_email') or '—')}</code>\n\n"
            "Выберите шаблон:"
        )
        try:
            await callback.message.edit_text(
                html_text,
                parse_mode="HTML",
                reply_markup=_kb_html_pick(mail_id),
            )
        except Exception:
            ui = await callback.message.answer(
                html_text,
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
    gag_link = await get_gag_generated_link(
        uid,
        incoming_id=mail_id,
        seller_email=mail.get("from_email"),
    )
    if not (gag_link or "").strip():
        return await callback.answer(
            "Сначала «🔗 Создать ссылку»", show_alert=True
        )
    if not (mail.get("generated_link") or "").strip():
        await inherit_incoming_gag_link(mail_id, uid, mail.get("from_email") or "")

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


@router.callback_query(F.data.startswith("mail_tmpl_send:"))
async def cb_mail_tmpl_send(
    callback: CallbackQuery, settings: Settings, state: FSMContext
) -> None:
    try:
        _, idx_s, mail_id_s = (callback.data or "").split(":", 2)
        idx = int(idx_s)
        mail_id = int(mail_id_s)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    items = await load_templates(uid)
    if idx < 0 or idx >= len(items):
        return await callback.answer("Пресет не найден", show_alert=True)

    if bg_is_running(uid, "smtp"):
        return await callback.answer("⏳ Отправка уже идёт…", show_alert=True)

    mail = await get_incoming_mail(mail_id, uid)
    if not mail:
        return await callback.answer("Письмо не найдено", show_alert=True)

    await callback.answer("⏳ Отправляю пресет…", show_alert=False)
    msg = callback.message
    bot = callback.bot
    data = await state.get_data()
    anchor = int(
        data.get("anchor_message_id") or mail.get("tg_message_id") or msg.message_id
    )
    cleanup: list[int] = []
    ui_id = data.get("ui_message_id")
    if ui_id:
        cleanup.append(int(ui_id))

    body = items[idx].text

    async def _job() -> None:
        ok, err, ctx = await send_incoming_text_reply(
            settings,
            uid,
            mail_id=mail_id,
            body=body,
            bot=bot,
            chat_id=msg.chat.id,
        )
        if ok and ctx:
            ctx.anchor_message_id = anchor
            ctx.cleanup_message_ids = cleanup
            await notify_reply_sent(bot, msg.chat.id, ctx)
        else:
            await bot.send_message(
                msg.chat.id,
                f"❌ {err or 'Ошибка'}",
                parse_mode="HTML",
                reply_to_message_id=anchor,
            )
        await state.clear()

    if not bg_start(uid, "smtp", _job()):
        await callback.answer("⏳ Отправка уже идёт…", show_alert=True)


@router.message(MailReply.waiting_text)
async def mail_reply_manual_text(
    message: Message, state: FSMContext, settings: Settings
) -> None:
    if message.photo or (
        message.document
        and (message.document.mime_type or "").lower().startswith("image/")
    ):
        return await message.answer(
            "📷 Отправка фото продавцу отключена. Только текст (DE/EN), пресет или HTML."
        )

    text = (message.text or "").strip()
    if text in {"-", "cancel"}:
        await state.clear()
        return await message.answer("Отменено.")
    if not text:
        return await message.answer(
            "Нужен текст (DE/EN) или кнопка пресет/HTML. «-» — отмена."
        )
    if err := seller_outbound_text_error(text):
        return await message.answer(f"❌ {err}")

    uid = message.from_user.id
    data = await state.get_data()
    mail_id = int(data.get("mail_id") or 0)
    if not mail_id:
        await state.clear()
        return await message.answer("❌ Нет письма. «Написать ещё» с карточки.")

    if bg_is_running(uid, "smtp"):
        return await message.answer("⏳ Отправка уже идёт…")

    mail = await get_incoming_mail(mail_id, uid)
    anchor = int(
        data.get("anchor_message_id") or (mail or {}).get("tg_message_id") or 0
    )
    cleanup: list[int] = []
    ui_id = data.get("ui_message_id")
    if ui_id:
        cleanup.append(int(ui_id))

    async def _job() -> None:
        ok, err, ctx = await send_incoming_text_reply(
            settings,
            uid,
            mail_id=mail_id,
            body=text,
            bot=message.bot,
            chat_id=message.chat.id,
        )
        if ok and ctx:
            ctx.anchor_message_id = anchor
            ctx.cleanup_message_ids = cleanup
            await notify_reply_sent(message.bot, message.chat.id, ctx)
        else:
            await message.answer(f"❌ {err or 'Ошибка'}")
        await state.clear()

    if not bg_start(uid, "smtp", _job()):
        await message.answer("⏳ Отправка уже идёт…")


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
                    "❌ Не удалось перевести. Проверьте DEEPSEEK_API_KEY или попробуйте позже.",
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


@router.callback_query(F.data.regexp(r"^goo_mail:\d+$"))
async def cb_goo_mail(callback: CallbackQuery) -> None:
    try:
        mail_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    if bg_is_running(uid, "gag_link"):
        return await callback.answer("⏳ Ссылка уже создаётся…", show_alert=True)

    msg = callback.message
    if not msg:
        return await callback.answer("Нет сообщения", show_alert=True)

    mail = await get_incoming_mail(mail_id, uid)
    if not mail:
        return await callback.answer("Письмо не найдено", show_alert=True)

    contact = (mail.get("from_email") or "").strip().lower()
    existing = await get_gag_generated_link(
        uid, incoming_id=mail_id, seller_email=contact
    )
    if (existing or "").strip():
        await inherit_incoming_gag_link(mail_id, uid, contact)
        await _refresh_incoming_card(msg, mail_id, uid)
        await callback.answer()
        await callback.bot.send_message(
            msg.chat.id,
            "ℹ️ Ссылка для этого продавца уже есть.\n\n"
            "Пересоздать ссылку? (текущий сервис из 👤 Профиль)",
            reply_markup=_gag_recreate_keyboard(mail_id),
            reply_to_message_id=msg.message_id,
        )
        return

    await callback.answer("⏳ Создаю ссылку…", show_alert=False)
    bot = callback.bot

    async def _job() -> None:
        await _create_gag_link_job(bot, msg, mail_id, uid, force_recreate=False)

    if not bg_start(uid, "gag_link", _job()):
        await callback.answer("⏳ Ссылка уже создаётся…", show_alert=True)


@router.callback_query(F.data.startswith("gag_recreate:"))
async def cb_gag_recreate(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        return await callback.answer("Неверные данные", show_alert=True)
    action, mail_id_s = parts[1], parts[2]
    try:
        mail_id = int(mail_id_s)
    except ValueError:
        return await callback.answer("Неверные данные", show_alert=True)

    uid = callback.from_user.id
    msg = callback.message
    if not msg:
        return await callback.answer("Нет сообщения", show_alert=True)

    if action == "no":
        mail = await get_incoming_mail(mail_id, uid)
        if mail:
            contact = (mail.get("from_email") or "").strip().lower()
            await inherit_incoming_gag_link(mail_id, uid, contact)
            await _refresh_incoming_card(msg, mail_id, uid)
        await callback.answer("Оставляю текущую ссылку", show_alert=False)
        return

    if action != "yes":
        return await callback.answer("Неверные данные", show_alert=True)

    if bg_is_running(uid, "gag_link"):
        return await callback.answer("⏳ Ссылка уже создаётся…", show_alert=True)

    await callback.answer("⏳ Пересоздаю ссылку…", show_alert=False)
    bot = callback.bot

    async def _job() -> None:
        await _create_gag_link_job(bot, msg, mail_id, uid, force_recreate=True)

    if not bg_start(uid, "gag_link", _job()):
        await callback.answer("⏳ Ссылка уже создаётся…", show_alert=True)


@router.callback_query(F.data.startswith("lead_price:"))
async def cb_lead_price(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        lead_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверный ID", show_alert=True)

    uid = callback.from_user.id
    lead = await get_validated_lead_by_id(uid, lead_id)
    if not lead:
        return await callback.answer("Лид не найден", show_alert=True)

    anchor = None
    if callback.message and callback.message.reply_to_message:
        anchor = callback.message.reply_to_message.message_id

    await state.set_state(LeadPrice.waiting_price)
    await state.update_data(
        lead_id=lead_id,
        link_card_message_id=callback.message.message_id if callback.message else None,
        anchor_message_id=anchor,
    )
    current = (lead.get("item_price") or "").strip() or "—"
    await callback.message.answer(
        "💶 <b>Цена</b>\n\n"
        f"Текущая: <code>{e(current)}</code>\n\n"
        "Отправьте новую цену (например <code>500</code> или <code>65.00 CHF</code>).\n"
        "GAG-ссылка пересоздастся и обновится в карточке.\n\n"
        "«-» — отмена.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(LeadPrice.waiting_price)
async def lead_price_set(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "-":
        await state.clear()
        return await message.answer("Отменено.")

    if not text:
        return await message.answer("Введите цену или «-» для отмены.")

    uid = message.from_user.id
    data = await state.get_data()
    lead_id = int(data.get("lead_id") or 0)
    if not lead_id:
        await state.clear()
        return await message.answer("❌ Нет лида.")

    lead = await get_validated_lead_by_id(uid, lead_id)
    if not lead:
        await state.clear()
        return await message.answer("❌ Лид не найден.")

    from database import upsert_validated_lead
    from services.fixture_fields import normalize_fixture_fields
    import json

    raw = lead.get("raw_json") or "{}"
    try:
        fx = json.loads(raw)
        if not isinstance(fx, dict):
            fx = {}
    except json.JSONDecodeError:
        fx = {}
    fx["item_price"] = text
    fields = normalize_fixture_fields(fx)
    email = (lead.get("email") or "").strip().lower()
    person = (lead.get("person_name") or "").strip()

    await upsert_validated_lead(
        uid,
        email=email,
        person_name=person,
        email_local=(lead.get("email_local") or email.split("@")[0]),
        email_domain=(lead.get("email_domain") or email.split("@")[-1]),
        item_title=fields["item_title"] or (lead.get("item_title") or ""),
        item_price=text,
        item_link=fields["item_link"] or (lead.get("item_link") or ""),
        person_link=(lead.get("person_link") or ""),
        location=fields["location"] or (lead.get("location") or ""),
        item_photo=fields["item_photo"] or (lead.get("item_photo") or ""),
        raw_json=json.dumps(fx, ensure_ascii=False),
        email_norm=lead.get("email_norm") or "",
        seller_key=lead.get("seller_key") or "",
        title_key=lead.get("title_key") or "",
    )

    card_msg_id = data.get("link_card_message_id")
    anchor = data.get("anchor_message_id")
    profile = await load_gag_profile(uid)

    try:
        result = await regenerate_gag_link_for_lead(
            uid, lead_id, offer_price=text
        )
        new_link = result.url
    except GagNotConfiguredError as exc:
        await state.clear()
        return await message.answer(f"❌ {exc}", parse_mode="HTML")
    except Exception as exc:
        await state.clear()
        return await message.answer(f"❌ {str(exc)[:350]}")

    from services.imap_fetch import service_label_from_link

    svc = service_label_from_link(fields["item_link"] or "") or ""
    cap = build_link_card_caption(
        offer_title=fields["item_title"] or (lead.get("item_title") or ""),
        offer_price=text,
        profile_title=profile.title,
        service_label=svc,
        item_link=fields["item_link"] or (lead.get("item_link") or ""),
        gag_link=new_link,
    )
    kb = build_link_card_keyboard(lead_id=lead_id)

    if card_msg_id:
        try:
            await message.bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=int(card_msg_id),
                caption=cap,
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            pass

    await state.clear()
    await message.answer(
        f"✅ Цена обновлена: <code>{e(text)}</code>\n"
        "GAG-ссылка пересоздана — в HTML будет эта цена.",
        parse_mode="HTML",
        reply_to_message_id=int(anchor) if anchor else None,
    )

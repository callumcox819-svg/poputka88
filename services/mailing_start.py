"""Запуск рассылки по validated_leads из БД (/send, кнопка меню)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database import (
    add_recipients,
    create_campaign,
    get_running_campaign,
    list_smtp_mailing_accounts,
    list_validated_emails,
)
from handlers.mailing import launch_campaign
from keyboards.main_menu import main_keyboard
from services.presets import load_smart_texts
from services.subject_offer import MAILING_SUBJECT_OFFER


async def _default_campaign_body(user_id: int) -> str:
    texts = await load_smart_texts(user_id)
    if texts:
        return texts[0]
    return (
        "Guten Tag! Ich interessiere mich für OFFER. "
        "Ist der Artikel noch verfügbar?"
    )


async def start_mailing_from_validated_db(
    message: Message,
    state: FSMContext,
    settings: Settings,
    bot: Bot,
) -> None:
    """Создать кампанию из validated_leads и сразу запустить."""
    await state.clear()
    uid = message.from_user.id

    running = await get_running_campaign(uid)
    if running:
        await message.answer(
            f"Уже идёт рассылка #{running['id']}. /stop — остановить.",
            reply_markup=main_keyboard(),
        )
        return

    emails = await list_validated_emails(uid)
    if not emails:
        await message.answer(
            "📭 <b>Нет валидных email в БД</b>\n\n"
            "Загрузите JSON void-parser — подбор сохранит адреса.\n"
            "Потом снова /send или ▶️ Запустить рассылку.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    accounts = await list_smtp_mailing_accounts(uid)
    if not accounts:
        await message.answer(
            "❌ <b>Нет SMTP для рассылки</b>\n\n"
            "Добавьте почты: ⚡ Быстрое добавление\n"
            "или включите ящики в ⚙️ → Почтовые аккаунты.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    if len(emails) > settings.max_recipients:
        await message.answer(
            f"⚠️ В БД <b>{len(emails)}</b> email, лимит кампании "
            f"<b>{settings.max_recipients}</b>.\n"
            "Будут взяты первые по дате валидации.",
            parse_mode="HTML",
        )
        emails = emails[: settings.max_recipients]

    body = await _default_campaign_body(uid)
    cid = await create_campaign(
        uid,
        MAILING_SUBJECT_OFFER,
        body,
        is_html=False,
        encoding="auto",
    )
    n = await add_recipients(cid, emails)

    await message.answer(
        f"▶️ <b>Рассылка #{cid}</b>\n"
        f"Получателей из БД: <b>{n}</b>\n"
        f"Тема: название товара из валидации\n"
        f"SMTP-аккаунтов: <b>{len(accounts)}</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
    await launch_campaign(message, settings, bot, cid, user_id=uid)

"""Запуск рассылки по validated_leads из БД (/send, кнопка меню)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database import (
    add_recipients,
    clear_mailing_reset_since,
    count_already_sent_mailing_emails,
    count_pending_recipients,
    count_validated_leads,
    create_campaign,
    get_latest_paused_campaign,
    get_mailing_reset_since,
    get_running_campaign,
    list_smtp_mailing_accounts,
    list_validated_emails_pending_mailing,
)
from handlers.mailing import launch_campaign
from keyboards.main_menu import main_keyboard
from services.campaign_runner import campaign_task_active, campaign_task_stuck
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
    *,
    full_database: bool = False,
) -> None:
    """Продолжить paused-кампанию или новая только по ещё не отправленным адресам."""
    await state.clear()
    uid = message.from_user.id
    reset_since = await get_mailing_reset_since(uid)
    batch_only = bool(reset_since) and not full_database

    running = await get_running_campaign(uid)
    if running:
        rid = int(running["id"])
        if campaign_task_active(rid):
            await message.answer(
                f"Уже идёт рассылка #{rid}. /stop — остановить.",
                reply_markup=main_keyboard(),
            )
            return
        if campaign_task_stuck(rid, running.get("status")):
            pending_n = await count_pending_recipients(rid)
            if pending_n > 0:
                await message.answer(
                    f"⚠️ Рассылка #{rid} зависла (в статусе running, фон молчит).\n"
                    f"Продолжаю: в очереди <b>{pending_n}</b>.",
                    parse_mode="HTML",
                    reply_markup=main_keyboard(),
                )
                await launch_campaign(message, settings, bot, rid, user_id=uid)
                return
        await message.answer(
            f"Уже идёт рассылка #{rid}. /stop — остановить.",
            reply_markup=main_keyboard(),
        )
        return

    paused = await get_latest_paused_campaign(uid)
    if paused:
        pending_n = await count_pending_recipients(int(paused["id"]))
        if pending_n > 0:
            sent_before = int(paused.get("sent") or 0)
            total = int(paused.get("total") or 0)
            await message.answer(
                f"▶️ <b>Продолжаю рассылку #{paused['id']}</b>\n"
                f"Уже отправлено: <b>{sent_before}</b> / {total}\n"
                f"Осталось в очереди: <b>{pending_n}</b>\n"
                f"<i>Повторно на уже получивших не шлём.</i>",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
            await launch_campaign(
                message, settings, bot, int(paused["id"]), user_id=uid
            )
            return

    total_leads = await count_validated_leads(uid)
    already_sent = await count_already_sent_mailing_emails(uid)
    if batch_only:
        emails = await list_validated_emails_pending_mailing(
            uid, since_created_at=reset_since
        )
    else:
        if full_database and reset_since:
            await clear_mailing_reset_since(uid)
        emails = await list_validated_emails_pending_mailing(uid)

    if not emails:
        if batch_only:
            await message.answer(
                "📭 <b>Нет новых адресов после /reset</b>\n\n"
                "Сначала загрузите JSON — подбор добавит лиды в БД.\n"
                "Потом <code>/send</code> (только они).\n"
                "Вся накопленная база: <code>/sendall</code>.",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
            return
        if total_leads > 0 and already_sent >= total_leads:
            await message.answer(
                f"✅ Всем <b>{total_leads}</b> валидным адресам из БД уже отправляли.\n"
                "Новый JSON / подбор — чтобы добавить новых получателей.",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
        else:
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
            f"⚠️ К отправке <b>{len(emails)}</b> новых адресов, лимит кампании "
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

    skip_line = ""
    if already_sent > 0 and not batch_only:
        skip_line = (
            f"\n⏭ Уже получали письмо ранее: <b>{already_sent}</b> "
            f"(из {total_leads} в БД) — в эту кампанию не включены."
        )
    batch_line = ""
    if batch_only:
        batch_line = (
            f"\n🔒 Режим после <code>/reset</code>: только лиды, "
            f"добавленные в БД с момента сброса."
        )

    await message.answer(
        f"▶️ <b>Рассылка #{cid}</b>\n"
        f"Новых получателей: <b>{n}</b>\n"
        f"Тема: название товара из валидации\n"
        f"SMTP-аккаунтов: <b>{len(accounts)}</b>{skip_line}{batch_line}",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
    await launch_campaign(message, settings, bot, cid, user_id=uid, quiet=True)

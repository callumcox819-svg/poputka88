from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from services.campaign_runner import campaign_task_stuck
from services.mailing_timing import load_timing
from database import (
    count_pending_recipients,
    count_smtp_accounts,
    count_smtp_mailing_accounts,
    count_total_sent_mails,
    count_validated_leads,
    get_active_mailing_campaign,
    get_last_campaign,
    get_mailing_sender_display,
)
from keyboards.main_menu import BTN_STATUS, main_keyboard

router = Router()


@router.message(Command("stat", "status", "statussend"))
@router.message(F.text == BTN_STATUS)
async def cmd_status(message: Message, settings: Settings) -> None:
    uid = message.from_user.id
    active = await get_active_mailing_campaign(uid)
    last = await get_last_campaign(uid)
    accounts = await count_smtp_accounts(uid)
    mailing = await count_smtp_mailing_accounts(uid)
    sender = await get_mailing_sender_display(uid)
    total_sent = await count_total_sent_mails(uid)

    lines = ["📊 <b>Статус</b>\n"]

    if sender:
        lines.append(f"Имя для рассылки: <b>{sender}</b>")

    if accounts != mailing:
        lines.append(
            f"Почт: <b>{accounts}</b> · для рассылки SMTP: <b>{mailing}</b>"
        )
    else:
        lines.append(f"SMTP-аккаунтов: <b>{accounts}</b>")

    if active:
        cid = int(active["id"])
        pending = await count_pending_recipients(cid)
        sent = int(active.get("sent") or 0)
        queue_total = sent + pending
        st = (active.get("status") or "").strip()
        icon = "▶️" if st == "running" else "⏸"
        lines.append(
            f"\n{icon} Рассылка <b>#{cid}</b> — {st}\n"
            f"Отправлено: <b>{sent}</b> / {queue_total}\n"
            f"В очереди: <b>{pending}</b>\n"
            f"Ошибок: <b>{int(active.get('failed') or 0)}</b>"
        )
        if campaign_task_stuck(cid, st):
            lines.append(
                "\n⚠️ <b>Фон остановился</b>, в БД ещё «running». "
                "Нажмите /send — продолжит очередь."
            )
    else:
        lines.append("\nОтправлено: <b>0</b> / 0")
        if last:
            st = (last.get("status") or "").strip()
            lines.append(
                f"Последняя кампания <b>#{last['id']}</b> — {st}"
            )
        else:
            lines.append("Рассылок ещё не было. /send — начать.")

    lines.append(f"\n📨 Всего отправлено: <b>{total_sent}</b>")

    leads = await count_validated_leads(uid)
    if leads:
        lines.append(f"📧 Валидированных продавцов: <b>{leads}</b>")
    timing = await load_timing(uid, settings.send_delay_sec)
    mn, mx = float(timing["min"]), float(timing["max"])
    batch = int(timing["batch_size"])
    if abs(mn - mx) < 0.05:
        pace = f"<b>{mn:g}</b> сек"
    else:
        pace = f"<b>{mn:g}–{mx:g}</b> сек"
    lines.append(
        f"\n⏱ Пауза между пачками: {pace} · пачка: <b>{batch}</b> писем/ящик"
    )
    lines.append(
        "<i>Меню: ⚙️ Настройки → ⏱ Тайминги (MIN MAX ПАЧКА, напр. 1 2 5)</i>"
    )
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=main_keyboard())

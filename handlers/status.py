from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from database import (
    count_smtp_accounts,
    count_validated_leads,
    get_last_campaign,
    get_running_campaign,
    get_user_sender_name,
)
from keyboards.main_menu import BTN_STATUS, main_keyboard

router = Router()


@router.message(Command("stat", "status", "statussend"))
@router.message(F.text == BTN_STATUS)
async def cmd_status(message: Message, settings: Settings) -> None:
    uid = message.from_user.id
    running = await get_running_campaign(uid)
    last = await get_last_campaign(uid)
    accounts = await count_smtp_accounts(uid)
    sender = await get_user_sender_name(uid)

    lines = ["📊 <b>Статус</b>\n"]

    if sender:
        lines.append(f"Имя отправителя: <b>{sender}</b>")

    lines.append(f"SMTP-аккаунтов: <b>{accounts}</b>")

    if running:
        lines.append(
            f"\n▶️ Рассылка <b>#{running['id']}</b> — {running['status']}\n"
            f"Отправлено: <b>{running['sent']}</b> / {running['total']}\n"
            f"Ошибок: <b>{running['failed']}</b>"
        )
    elif last:
        lines.append(
            f"\nПоследняя кампания <b>#{last['id']}</b> — {last['status']}\n"
            f"Отправлено: <b>{last['sent']}</b> / {last['total']}\n"
            f"Ошибок: <b>{last['failed']}</b>"
        )
    else:
        lines.append("\nРассылок ещё не было. /send — начать.")

    leads = await count_validated_leads(uid)
    if leads:
        lines.append(f"📧 Валидированных продавцов: <b>{leads}</b>")
    lines.append(f"\nЗадержка между письмами: <b>{settings.send_delay_sec}</b> сек.")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=main_keyboard())

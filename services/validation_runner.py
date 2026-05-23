import asyncio
import logging

from aiogram import Bot

from services.email_validate import validate_one
from services.task_control import (
    clear_stop_validation,
    request_stop_validation,
    should_stop_validation,
)
from utils.email_list import parse_emails

logger = logging.getLogger(__name__)

_active_users: set[int] = set()


def stop_validation(user_id: int) -> bool:
    if user_id not in _active_users:
        return False
    request_stop_validation(user_id)
    return True


async def run_validation(bot: Bot, user_id: int, chat_id: int, text: str) -> None:
    if user_id in _active_users:
        await bot.send_message(chat_id, "Проверка уже идёт. /stopcheck — остановить.")
        return

    emails = parse_emails(text)
    if not emails:
        await bot.send_message(chat_id, "Не найдено email для проверки.")
        return

    _active_users.add(user_id)
    clear_stop_validation(user_id)

    valid: list[str] = []
    invalid: list[tuple[str, str]] = []

    try:
        await bot.send_message(chat_id, f"Проверка {len(emails)} адресов…")
        for i, email in enumerate(emails, 1):
            if should_stop_validation(user_id):
                await bot.send_message(
                    chat_id,
                    f"Остановлено на {i}/{len(emails)}.\n"
                    f"Валидных: {len(valid)}, невалидных: {len(invalid)}.",
                )
                return

            ok, reason = await validate_one(email)
            if ok:
                valid.append(email)
            else:
                invalid.append((email, reason))

            if i % 25 == 0:
                await bot.send_message(chat_id, f"… {i}/{len(emails)}")

            await asyncio.sleep(0.05)

        lines = [
            f"Готово. Валидных: {len(valid)}, невалидных: {len(invalid)}.",
        ]
        if valid[:20]:
            lines.append("\n✅ Примеры валидных:\n" + "\n".join(valid[:20]))
        if invalid[:15]:
            lines.append(
                "\n❌ Невалидные:\n"
                + "\n".join(f"{e} — {r}" for e, r in invalid[:15])
            )
        await bot.send_message(chat_id, "\n".join(lines))
    finally:
        _active_users.discard(user_id)
        clear_stop_validation(user_id)

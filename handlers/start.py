from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Mass Mailer Bot — рассылка по SMTP с правильной MIME-кодировкой.\n\n"
        "/new — новая кампания\n"
        "/status <id> — прогресс\n\n"
        "Кодировки:\n"
        "• 7bit — идеально для чистого ASCII\n"
        "• quoted-printable — лучше для UTF-8 и HTML\n"
        "• base64 — тяжёлый контент\n"
        "• auto — подбор автоматически"
    )

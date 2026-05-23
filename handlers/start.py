from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from keyboards.main_menu import main_keyboard

router = Router()

WELCOME = (
    "Poputka88 — бот массовой рассылки.\n\n"
    "Команды:\n"
    "/start — меню\n"
    "/send — запустить рассылку\n"
    "/stop — остановить рассылку\n"
    "/stopcheck — остановить проверку почт\n"
    "/imap_check — входящие по IMAP\n\n"
    "Или используйте кнопки ниже."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME, reply_markup=main_keyboard())

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from keyboards.main_menu import main_keyboard
from services.bot_commands import BOTFATHER_COMMANDS_TEXT, register_bot_commands

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
async def cmd_start(message: Message, bot: Bot) -> None:
    try:
        await register_bot_commands(bot, chat_id=message.chat.id)
    except Exception:
        pass
    await message.answer(WELCOME, reply_markup=main_keyboard())


@router.message(Command("commands_help"))
async def cmd_commands_help(message: Message) -> None:
    """Если API не сработал — вставьте список в @BotFather вручную."""
    await message.answer(
        "Если слэш-команды не видны в меню «/», откройте @BotFather:\n"
        "1) /mybots → ваш бот → Edit Bot → Edit Commands\n"
        "2) Вставьте текст ниже целиком:\n\n"
        f"<pre>{BOTFATHER_COMMANDS_TEXT}</pre>\n\n"
        "3) Перезапустите Telegram или закройте чат с ботом.",
        parse_mode="HTML",
    )

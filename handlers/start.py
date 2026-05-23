from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from config import Settings
from keyboards.main_menu import main_keyboard
from services.bot_commands import BOTFATHER_COMMANDS_TEXT

router = Router()

WELCOME = (
    "👋 Привет! Это бот для массовой рассылки по email.\n\n"
    "Основные команды:\n"
    "/send — запустить рассылку\n"
    "/stop — остановить рассылку\n"
    "/stat — статус рассылки\n"
    "/imap_check — входящие по IMAP\n"
    "/stopcheck — остановить проверку почт\n\n"
    "⚙️ Настройки — аккаунты, задержка.\n"
    "⚡ Быстрое добавление — имя отправителя и почты <code>email:пароль</code>."
)


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings) -> None:
    show_admin = message.from_user.id in settings.admin_ids
    await message.answer(
        WELCOME,
        reply_markup=main_keyboard(show_admin=show_admin),
        parse_mode="HTML",
    )


@router.message(Command("commands_help"))
async def cmd_commands_help(message: Message) -> None:
    await message.answer(
        "Вставьте в @BotFather → Edit Commands:\n\n"
        f"<pre>{BOTFATHER_COMMANDS_TEXT}</pre>",
        parse_mode="HTML",
    )

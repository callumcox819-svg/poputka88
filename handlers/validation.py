import asyncio

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.states import EmailValidation
from keyboards.main_menu import MENU_BUTTONS
from services.validation_runner import run_validation

router = Router()


@router.message(EmailValidation.waiting_list)
async def on_validation_list(message: Message, state: FSMContext, bot) -> None:
    if message.text in MENU_BUTTONS:
        await state.clear()
        return
    text = message.text or ""
    if message.document and message.document.file_name and message.document.file_name.endswith(".txt"):
        file = await bot.get_file(message.document.file_id)
        buf = await bot.download_file(file.file_path)
        text = buf.read().decode("utf-8", errors="replace")

    await state.clear()
    asyncio.create_task(
        run_validation(bot, message.from_user.id, message.chat.id, text)
    )
    await message.answer("Проверка запущена. /stopcheck — остановить.")

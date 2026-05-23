import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database import get_latest_ready_campaign, get_running_campaign
from handlers.mailing import begin_new_campaign, launch_campaign
from handlers.states import EmailValidation
from keyboards.main_menu import (
    BTN_CHECK_EMAILS,
    BTN_QUICK_ADD,
    BTN_SETTINGS,
    BTN_START_MAIL,
    BTN_STOP_MAIL,
    main_keyboard,
)
from services.campaign_runner import stop_user_mailings
from services.validation_runner import stop_validation

router = Router()


@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    ids = await stop_user_mailings(message.from_user.id)
    if ids:
        await message.answer(
            f"Рассылка остановлена (кампании: {', '.join(map(str, ids))}).",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer("Нет активной рассылки.", reply_markup=main_keyboard())


@router.message(Command("stopcheck"))
async def cmd_stopcheck(message: Message) -> None:
    if stop_validation(message.from_user.id):
        await message.answer("Остановка проверки…", reply_markup=main_keyboard())
    else:
        await message.answer("Проверка не запущена.", reply_markup=main_keyboard())


@router.message(Command("send"))
async def cmd_send(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    running = await get_running_campaign(message.from_user.id)
    if running:
        await message.answer(
            f"Уже идёт рассылка #{running['id']}. /stop — остановить.",
            reply_markup=main_keyboard(),
        )
        return

    ready = await get_latest_ready_campaign(message.from_user.id)
    if ready:
        await launch_campaign(message, settings, bot, ready["id"])
        return

    await begin_new_campaign(message, state)


@router.message(Command("imap_check"))
async def cmd_imap_check(message: Message, bot) -> None:
    from handlers.settings import run_imap_check

    await run_imap_check(bot, message.chat.id, message.from_user.id)


@router.message(F.text == BTN_STOP_MAIL)
async def btn_stop_mail(message: Message) -> None:
    await cmd_stop(message)


@router.message(F.text == BTN_START_MAIL)
async def btn_start_mail(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    await cmd_send(message, state, settings, bot)


@router.message(F.text == BTN_SETTINGS)
async def btn_settings(message: Message) -> None:
    from handlers.settings import show_settings_menu

    await show_settings_menu(message)


@router.message(F.text == BTN_QUICK_ADD)
async def btn_quick_add(message: Message, state: FSMContext) -> None:
    from handlers.accounts import start_quick_add

    await start_quick_add(message, state)


@router.message(F.text == BTN_CHECK_EMAILS)
async def btn_check_emails(message: Message, state: FSMContext) -> None:
    await state.set_state(EmailValidation.waiting_list)
    await message.answer(
        "Пришлите список email для проверки (по строке или через запятую).\n"
        "/stopcheck — остановить проверку.",
        reply_markup=main_keyboard(),
    )

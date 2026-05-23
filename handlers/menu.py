from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database import get_latest_ready_campaign, get_running_campaign
from handlers.mailing import begin_new_campaign, launch_campaign
from handlers.settings import match_settings_menu_text, open_settings_menu
from keyboards.main_menu import BTN_START_MAIL, BTN_STOP_MAIL, main_keyboard
from services.campaign_runner import stop_user_mailings
from services.validation_runner import stop_validation

router = Router()


@router.message(Command("stop", "stopsend"))
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


@router.message(Command("imap_check", "imap_diag"))
async def cmd_imap_check(message: Message, bot) -> None:
    from handlers.settings import run_imap_check

    await run_imap_check(bot, message.chat.id, message.from_user.id)


@router.message(F.text.in_({BTN_STOP_MAIL, "/stop", "/stopsend"}))
async def btn_stop_mail(message: Message) -> None:
    await cmd_stop(message)


@router.message(F.text == BTN_START_MAIL)
async def btn_start_mail(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    await cmd_send(message, state, settings, bot)


@router.message(F.func(lambda m: match_settings_menu_text(getattr(m, "text", None))))
async def btn_settings(message: Message, state: FSMContext) -> None:
    await open_settings_menu(message, state)

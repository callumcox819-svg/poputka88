from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import add_smtp_account, count_smtp_accounts
from handlers.states import QuickAdd
from keyboards.main_menu import main_keyboard
from utils.account_parse import parse_account_block

router = Router()


async def start_quick_add(message: Message, state: FSMContext) -> None:
    await state.set_state(QuickAdd.sender_name)
    await message.answer(
        "Задайте имя отправителя:",
        reply_markup=main_keyboard(),
    )


@router.message(QuickAdd.sender_name)
async def on_sender_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Имя не может быть пустым.")
        return
    await state.update_data(sender_name=name)
    await state.set_state(QuickAdd.accounts)
    await message.answer(
        "Введите почты — по одной на строку:\n"
        "<code>email:password</code>\n"
        "или <code>email:password:smtp_host:port</code>",
        parse_mode="HTML",
    )


@router.message(QuickAdd.accounts)
async def on_accounts(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    sender_name = data.get("sender_name", "")
    accounts = parse_account_block(message.text or "")
    if not accounts:
        await message.answer("Не распознано ни одного аккаунта. Формат: email:password")
        return

    added = 0
    for acc in accounts:
        await add_smtp_account(
            message.from_user.id,
            sender_name=sender_name,
            email=acc["email"],
            password=acc["password"],
            smtp_host=acc["smtp_host"],
            smtp_port=acc["smtp_port"],
            imap_host=acc["imap_host"],
            imap_port=acc["imap_port"],
        )
        added += 1

    await state.clear()
    total = await count_smtp_accounts(message.from_user.id)
    await message.answer(
        f"Добавлено аккаунтов: {added}\n"
        f"Всего в базе: {total}\n"
        f"Имя отправителя: {sender_name}",
        reply_markup=main_keyboard(),
    )

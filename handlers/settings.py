from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Settings
from database import count_smtp_accounts, get_user_delay, list_smtp_accounts, set_user_delay
from handlers.states import SettingsEdit
from keyboards.main_menu import main_keyboard
from keyboards.settings_menu import settings_inline
from services.imap_check import check_accounts

router = Router()


async def show_settings_menu(message: Message) -> None:
    uid = message.from_user.id
    n = await count_smtp_accounts(uid)
    await message.answer(
        f"⚙️ Настройки\n\nSMTP-аккаунтов: {n}\nВыберите пункт:",
        reply_markup=settings_inline(),
    )


async def run_imap_check(bot: Bot, chat_id: int, user_id: int) -> None:
    accounts = await list_smtp_accounts(user_id, with_secrets=True)
    if not accounts:
        await bot.send_message(
            chat_id,
            "Нет сохранённых аккаунтов. «Быстрое добавление» или .env.",
            reply_markup=main_keyboard(),
        )
        return

    await bot.send_message(chat_id, f"Проверяю входящие ({len(accounts)} акк.)…")
    results = await check_accounts(accounts)
    lines = ["📥 IMAP проверка:\n"]
    for r in results:
        if r["ok"]:
            lines.append(
                f"✅ {r['email']}: непрочитанных {r['unseen']}, всего {r['total']}"
            )
        else:
            lines.append(f"❌ {r['email']}: {r.get('error', 'ошибка')}")
    await bot.send_message(chat_id, "\n".join(lines), reply_markup=main_keyboard())


@router.callback_query(F.data == "set:close")
async def cb_close(cb: CallbackQuery) -> None:
    await cb.message.delete()
    await cb.answer()


@router.callback_query(F.data == "set:accounts")
async def cb_accounts(cb: CallbackQuery) -> None:
    accounts = await list_smtp_accounts(cb.from_user.id)
    if not accounts:
        await cb.message.answer("Аккаунтов нет. Кнопка «Быстрое добавление».")
    else:
        lines = ["📬 SMTP-аккаунты:\n"]
        for a in accounts:
            lines.append(
                f"• #{a['id']} {a['email']} ({a['sender_name'] or '—'})\n"
                f"  SMTP {a['smtp_host']}:{a['smtp_port']}"
            )
        await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.callback_query(F.data == "set:imap")
async def cb_imap(cb: CallbackQuery, bot: Bot) -> None:
    await cb.answer()
    await run_imap_check(bot, cb.message.chat.id, cb.from_user.id)


@router.callback_query(F.data == "set:delay")
async def cb_delay(cb: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    cur = await get_user_delay(cb.from_user.id, settings.send_delay_sec)
    await state.set_state(SettingsEdit.delay)
    await cb.message.answer(f"Текущая задержка: {cur} сек.\nОтправьте новое число (0.5–120):")
    await cb.answer()


@router.message(SettingsEdit.delay)
async def on_delay_value(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        val = float(raw)
    except ValueError:
        await message.answer("Введите число, например 2 или 1.5")
        return
    if val < 0.5 or val > 120:
        await message.answer("Задержка от 0.5 до 120 секунд.")
        return
    await set_user_delay(message.from_user.id, val)
    await state.clear()
    await message.answer(f"Задержка установлена: {val} сек.", reply_markup=main_keyboard())

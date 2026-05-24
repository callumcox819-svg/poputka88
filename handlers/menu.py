from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import Settings
from database import get_running_campaign, reset_user_mailing_queue
from services.mailing_start import start_mailing_from_validated_db
from handlers.settings import match_settings_menu_text, open_settings_menu
from keyboards.main_menu import BTN_START_MAIL, BTN_STOP_MAIL, main_keyboard
from services.campaign_runner import stop_user_mailings
from services.validation_session import stop_void_validation

router = Router()


@router.message(Command("stop", "stopsend"))
async def cmd_stop(message: Message) -> None:
    from database import get_latest_paused_campaign, get_running_campaign

    uid = message.from_user.id
    ids = await stop_user_mailings(uid)
    if ids:
        await message.answer(
            f"⏹ Рассылка остановлена (кампании: {', '.join(map(str, ids))}).\n"
            f"<i>Дойдёт до конца текущего письма (если оно отправлялось), "
            f"дальше — пауза. /send продолжит с того же места.</i>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    paused = await get_latest_paused_campaign(uid)
    if paused and int(paused.get("sent") or 0) > 0:
        await message.answer(
            f"Активной рассылки нет. Последняя #{paused['id']} на паузе "
            f"({paused['sent']}/{paused['total']} отправлено). /send — продолжить.",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer("Нет активной рассылки.", reply_markup=main_keyboard())


@router.message(Command("stopcheck"))
async def cmd_stopcheck(message: Message) -> None:
    if stop_void_validation(message.from_user.id):
        await message.answer(
            "⏹ Останавливаю подбор… Найденное сохранится в БД и в статистике.",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer("Проверка не запущена.", reply_markup=main_keyboard())


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    uid = message.from_user.id
    await stop_user_mailings(uid)
    result = await reset_user_mailing_queue(uid)
    removed = int(result.get("removed") or 0)
    stopped = int(result.get("stopped_running") or 0)
    lines = [
        "🔄 <b>Очередь рассылки обнулена</b>",
        f"Убрано из очереди: <b>{removed}</b> адресов (pending).",
        "📧 <b>Валидированные лиды в БД</b> — без изменений.",
        "✉️ Уже <b>отправленные</b> (sent) — в истории; /send снова на них не пойдёт.",
        "📨 Следующий <code>/send</code> — <b>только</b> лиды из подбора после сброса.",
        "📨 Вся база (как раньше): <code>/sendall</code>.",
        "📊 /stat — счётчик очереди должен быть <b>0 / 0</b>.",
    ]
    if stopped:
        lines.insert(1, f"⏹ Остановлено рассылок: <b>{stopped}</b>.")
    if removed == 0 and stopped == 0:
        lines = [
            "🔄 <b>Очередь рассылки пуста</b>",
            "Нет адресов со статусом pending — сбрасывать нечего.",
            "📧 Лиды в БД на месте. /send — собрать новую очередь из БД.",
        ]
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=main_keyboard())


@router.message(Command("send"))
async def cmd_send(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    await start_mailing_from_validated_db(message, state, settings, bot)


@router.message(Command("sendall"))
async def cmd_sendall(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    await start_mailing_from_validated_db(
        message, state, settings, bot, full_database=True
    )


@router.message(Command("imap_check", "imap_diag"))
async def cmd_imap_check(message: Message, bot) -> None:
    from handlers.settings import run_imap_check

    await run_imap_check(bot, message.chat.id, message.from_user.id)


@router.message(F.text.in_({BTN_STOP_MAIL, "/stop", "/stopsend"}))
async def btn_stop_mail(message: Message) -> None:
    await cmd_stop(message)


@router.message(F.text == BTN_START_MAIL)
async def btn_start_mail(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    from database import get_mailing_reset_since

    if await get_mailing_reset_since(message.from_user.id):
        await cmd_send(message, state, settings, bot)
    else:
        await cmd_sendall(message, state, settings, bot)


@router.message(F.func(lambda m: match_settings_menu_text(getattr(m, "text", None))))
async def btn_settings(message: Message, state: FSMContext) -> None:
    await open_settings_menu(message, state)


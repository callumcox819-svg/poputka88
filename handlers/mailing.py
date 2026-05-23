import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Settings
from database import add_recipients, create_campaign, get_campaign, get_running_campaign
from handlers.states import NewCampaign
from keyboards.main_menu import is_main_menu_text, main_keyboard
from services.campaign_runner import run_campaign
from services.encoding import can_use_7bit, recommend_encoding

router = Router()


def _encoding_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="Auto (рекомендуется)", callback_data="enc:auto")
    b.button(text="7bit (чистый ASCII)", callback_data="enc:7bit")
    b.button(text="quoted-printable", callback_data="enc:quoted-printable")
    b.button(text="base64", callback_data="enc:base64")
    b.adjust(1)
    return b.as_markup()


def _format_keyboard():
    b = InlineKeyboardBuilder()
    b.button(text="Текст (plain)", callback_data="fmt:text")
    b.button(text="HTML", callback_data="fmt:html")
    b.adjust(2)
    return b.as_markup()


async def begin_new_campaign(message: Message, state: FSMContext) -> None:
    from services.subject_offer import MAILING_SUBJECT_OFFER

    await state.clear()
    await state.update_data(subject=MAILING_SUBJECT_OFFER)
    await state.set_state(NewCampaign.body)
    await message.answer(
        "Новая рассылка.\n"
        "Тема при отправке: <code>OFFER</code> — название товара продавца из валидации.\n\n"
        "Текст письма:",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def launch_campaign(
    message: Message,
    settings: Settings,
    bot,
    campaign_id: int,
    *,
    user_id: int | None = None,
    quiet: bool = False,
) -> bool:
    """Запускает фоновую рассылку. quiet=True — без «Кампания запущена» (ответ уже был выше)."""
    from services.campaign_runner import campaign_task_active, run_campaign

    uid = user_id if user_id is not None else message.from_user.id
    cid = int(campaign_id)

    if campaign_task_active(cid):
        if not quiet:
            await message.answer(
                f"Рассылка #{cid} уже выполняется в фоне.",
                reply_markup=main_keyboard(),
            )
        return False

    running = await get_running_campaign(uid)
    if running and int(running["id"]) != cid:
        await message.answer(
            f"Уже идёт рассылка #{running['id']}. /stop — остановить.",
            reply_markup=main_keyboard(),
        )
        return False

    asyncio.create_task(run_campaign(bot, settings, cid, message.chat.id, uid))
    if not quiet:
        await message.answer(
            f"Кампания #{cid} запущена.",
            reply_markup=main_keyboard(),
        )
    return True


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await begin_new_campaign(message, state)


@router.message(NewCampaign.body)
async def on_body(message: Message, state: FSMContext) -> None:
    if is_main_menu_text(message.text):
        return
    body = message.text or message.caption or ""
    await state.update_data(body=body)
    await state.set_state(NewCampaign.format_choice)
    rec = recommend_encoding(body, is_html=False)
    hint = f"Для этого текста auto выберет: {rec}"
    if can_use_7bit(body):
        hint += " (подходит 7bit)"
    await message.answer(f"Формат письма?\n{hint}", reply_markup=_format_keyboard())


@router.callback_query(NewCampaign.format_choice, F.data.startswith("fmt:"))
async def on_format(cb: CallbackQuery, state: FSMContext) -> None:
    is_html = cb.data == "fmt:html"
    await state.update_data(is_html=is_html)
    await state.set_state(NewCampaign.encoding)
    data = await state.get_data()
    body = data.get("body", "")
    rec = recommend_encoding(body, is_html=is_html)
    html_hint = ""
    if is_html:
        html_hint = (
            "\n\n📄 HTML: шаблон из <code>data/HTMLch/</code> по выбранному сервису GAG "
            "(ТУТТИ / ПОСТ / Ricardo).\n"
            "В поле «текст» укажите имя файла, например <code>confirmation.html</code> "
            "или <code>-</code> по умолчанию.\n"
            "Имя (From) и тема — только из 👤 Имя для спуфинга.\n"
            "Переменные: <code>{{LINK}}</code> (GAG), <code>{{NICK}}</code>, "
            "<code>{{ITEM_TITLE}}</code> и др."
        )
    await cb.message.edit_text(
        f"Кодировка (Content-Transfer-Encoding):\nРекомендация: {rec}{html_hint}",
        reply_markup=_encoding_keyboard(),
    )
    await cb.answer()


@router.callback_query(NewCampaign.encoding, F.data.startswith("enc:"))
async def on_encoding(cb: CallbackQuery, state: FSMContext) -> None:
    enc = cb.data.split(":", 1)[1]
    await state.update_data(encoding=enc)
    await state.set_state(NewCampaign.recipients)
    await cb.message.edit_text(
        "Список получателей — по строке или .txt файл."
    )
    await cb.answer()


@router.message(NewCampaign.recipients, F.document)
async def on_recipients_file(
    message: Message, state: FSMContext, settings: Settings, bot
) -> None:
    doc = message.document
    if not doc or not doc.file_name or not doc.file_name.endswith(".txt"):
        await message.answer("Нужен .txt файл.")
        return
    file = await bot.get_file(doc.file_id)
    buf = await bot.download_file(file.file_path)
    text = buf.read().decode("utf-8", errors="replace")
    await _finish_recipients(message, state, settings, bot, text)


@router.message(NewCampaign.recipients)
async def on_recipients_text(
    message: Message, state: FSMContext, settings: Settings, bot
) -> None:
    if is_main_menu_text(message.text):
        return
    await _finish_recipients(message, state, settings, bot, message.text or "")


async def _finish_recipients(
    message: Message,
    state: FSMContext,
    settings: Settings,
    bot,
    text: str,
) -> None:
    from utils.email_list import parse_emails

    emails = parse_emails(text)
    if not emails:
        await message.answer("Не найдено валидных email.")
        return
    if len(emails) > settings.max_recipients:
        await message.answer(f"Лимит: {settings.max_recipients} адресов.")
        return

    data = await state.get_data()
    cid = await create_campaign(
        message.from_user.id,
        data["subject"],
        data["body"],
        is_html=data.get("is_html", False),
        encoding=data.get("encoding", "auto"),
    )
    n = await add_recipients(cid, emails)
    await state.clear()

    b = InlineKeyboardBuilder()
    b.button(text="▶ Запустить", callback_data=f"run:{cid}")
    b.button(text="📊 Статус", callback_data=f"stat:{cid}")
    b.adjust(2)

    await message.answer(
        f"Кампания #{cid} готова.\nПолучателей: {n}\n"
        "Нажмите «Запустить» или /send",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("run:"))
async def on_run(cb: CallbackQuery, settings: Settings, bot) -> None:
    cid = int(cb.data.split(":", 1)[1])
    await launch_campaign(
        cb.message, settings, bot, cid, user_id=cb.from_user.id
    )
    await cb.answer("Запущено")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /status <id>")
        return
    camp = await get_campaign(int(parts[1]), message.from_user.id)
    if not camp:
        await message.answer("Кампания не найдена.")
        return
    await message.answer(
        f"#{camp['id']} — {camp['status']}\n"
        f"Всего: {camp['total']}\n"
        f"Отправлено: {camp['sent']}\n"
        f"Ошибок: {camp['failed']}"
    )


@router.callback_query(F.data.startswith("stat:"))
async def on_stat(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":", 1)[1])
    camp = await get_campaign(cid, cb.from_user.id)
    if not camp:
        await cb.answer("Не найдена", show_alert=True)
        return
    await cb.message.answer(
        f"#{camp['id']}: {camp['sent']}/{camp['total']} ok, {camp['failed']} fail"
    )
    await cb.answer()

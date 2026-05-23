import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Settings
from database import add_recipients, create_campaign, get_campaign
from handlers.states import NewCampaign
from services.campaign_runner import run_campaign
from services.encoding import TransferEncoding, can_use_7bit, recommend_encoding
from utils.email_list import parse_emails

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


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewCampaign.subject)
    await message.answer("Тема письма:")


@router.message(NewCampaign.subject)
async def on_subject(message: Message, state: FSMContext) -> None:
    await state.update_data(subject=message.text or "")
    await state.set_state(NewCampaign.body)
    await message.answer("Текст письма (можно HTML позже):")


@router.message(NewCampaign.body)
async def on_body(message: Message, state: FSMContext) -> None:
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
    await cb.message.edit_text(
        f"Кодировка передачи (Content-Transfer-Encoding):\n"
        f"Рекомендация: {rec}\n\n"
        "7bit — максимум совместимости для ASCII.\n"
        "quoted-printable — лучше для UTF-8/HTML.\n"
        "base64 — тяжёлый Unicode.",
        reply_markup=_encoding_keyboard(),
    )
    await cb.answer()


@router.callback_query(NewCampaign.encoding, F.data.startswith("enc:"))
async def on_encoding(cb: CallbackQuery, state: FSMContext) -> None:
    enc = cb.data.split(":", 1)[1]
    await state.update_data(encoding=enc)
    await state.set_state(NewCampaign.recipients)
    await cb.message.edit_text(
        "Пришли список email — по одному на строку или через запятую.\n"
        "Можно отправить .txt файл."
    )
    await cb.answer()


@router.message(NewCampaign.recipients, F.document)
async def on_recipients_file(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    doc = message.document
    if not doc or not doc.file_name or not doc.file_name.endswith(".txt"):
        await message.answer("Нужен .txt файл со списком email.")
        return
    file = await bot.get_file(doc.file_id)
    buf = await bot.download_file(file.file_path)
    text = buf.read().decode("utf-8", errors="replace")
    await _finish_recipients(message, state, settings, bot, text)


@router.message(NewCampaign.recipients)
async def on_recipients_text(message: Message, state: FSMContext, settings: Settings, bot) -> None:
    await _finish_recipients(message, state, settings, bot, message.text or "")


async def _finish_recipients(
    message: Message,
    state: FSMContext,
    settings: Settings,
    bot,
    text: str,
) -> None:
    emails = parse_emails(text)
    if not emails:
        await message.answer("Не найдено ни одного валидного email.")
        return
    if len(emails) > settings.max_recipients:
        await message.answer(
            f"Слишком много адресов ({len(emails)}). Лимит: {settings.max_recipients}."
        )
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
        f"Кампания #{cid} создана.\n"
        f"Получателей: {n}\n"
        f"Кодировка: {data.get('encoding', 'auto')}\n"
        f"Формат: {'HTML' if data.get('is_html') else 'text'}",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("run:"))
async def on_run(cb: CallbackQuery, settings: Settings, bot) -> None:
    cid = int(cb.data.split(":", 1)[1])
    asyncio.create_task(run_campaign(bot, settings, cid, cb.message.chat.id))
    await cb.answer("Рассылка запущена")
    await cb.message.answer(f"Кампания #{cid} запущена. /status {cid} — прогресс.")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /status <id кампании>")
        return
    camp = await get_campaign(int(parts[1]))
    if not camp:
        await message.answer("Кампания не найдена.")
        return
    await message.answer(
        f"#{camp['id']} — {camp['status']}\n"
        f"Всего: {camp['total']}\n"
        f"Отправлено: {camp['sent']}\n"
        f"Ошибок: {camp['failed']}\n"
        f"Кодировка: {camp['encoding']}"
    )


@router.callback_query(F.data.startswith("stat:"))
async def on_stat(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":", 1)[1])
    camp = await get_campaign(cid)
    if not camp:
        await cb.answer("Не найдена", show_alert=True)
        return
    await cb.message.answer(
        f"#{camp['id']}: {camp['sent']}/{camp['total']} ok, {camp['failed']} fail"
    )
    await cb.answer()

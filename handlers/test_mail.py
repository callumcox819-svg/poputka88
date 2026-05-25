"""🧪 Тест маил — отправка с OFFER и симуляция входящего с фото."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import List

logger = logging.getLogger(__name__)

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Settings
from database import get_user_sender_name, list_smtp_mailing_accounts
from services.incoming_worker import poll_incoming_for_user
from services.mail_outbound import (
    NoLiveProxyError,
    live_proxy_count,
    send_mail,
    user_has_proxies,
)
from services.offer_text import apply_offer_to_text
from services.presets import pick_random_smart_preset
from services.test_mail_fixtures import (
    fixture_label,
    get_test_fixture,
    load_test_fixtures,
    pick_random_test_fixture,
)
from services.test_mail_lead import register_test_mail_lead
from services.test_mail_simulate import simulate_seller_reply
from services.user_json_store import load_json_blob, save_json_blob
from utils.bg_jobs import is_running as bg_is_running, start as bg_start
from utils.text_html import e

router = Router()

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
TEST_MAIL_BLOB = "test_mail_recipients"
MAX_TEST_RECIPIENTS = 20


class TestMailStates(StatesGroup):
    waiting_add = State()
    waiting_oneoff = State()


def _canon_email(addr: str) -> str:
    return (addr or "").strip().lower()


def _parse_emails(text: str) -> List[str]:
    raw = (text or "").replace(";", "\n").replace(",", "\n")
    out: List[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        em = _canon_email(line)
        if not em or not EMAIL_RE.match(em):
            continue
        if em in seen:
            continue
        seen.add(em)
        out.append(em)
    return out


async def _load_recipients(user_id: int) -> List[str]:
    data = await load_json_blob(user_id, TEST_MAIL_BLOB, default=[])
    out: List[str] = []
    seen: set[str] = set()
    for item in data if isinstance(data, list) else []:
        em = _canon_email(str(item))
        if em and EMAIL_RE.match(em) and em not in seen:
            seen.add(em)
            out.append(em)
    return out


async def _save_recipients(user_id: int, emails: List[str]) -> None:
    clean: List[str] = []
    seen: set[str] = set()
    for em in emails:
        c = _canon_email(em)
        if c and EMAIL_RE.match(c) and c not in seen:
            seen.add(c)
            clean.append(c)
    await save_json_blob(user_id, TEST_MAIL_BLOB, clean[:MAX_TEST_RECIPIENTS])


async def _sender_account_emails(user_id: int) -> set[str]:
    accs = await list_smtp_mailing_accounts(user_id, with_secrets=False)
    return {_canon_email(a.get("email") or "") for a in accs if a.get("email")}


async def _proxy_hint(user_id: int) -> str:
    if not await user_has_proxies(user_id):
        return "🌐 <b>Прокси обязательны</b> для любой отправки — добавьте SOCKS5.\n"
    live = await live_proxy_count(user_id)
    if live < 1:
        return "⚠️ Прокси есть, но <b>нет живых</b> — отправка не пойдёт.\n"
    return f"🌐 Прокси: <b>{live}</b> живых (вся отправка через SOCKS5).\n"


async def _imap_hint(user_id: int) -> str:
    from database import list_imap_poll_accounts

    accs = await list_smtp_mailing_accounts(user_id, with_secrets=False)
    poll = [
        a
        for a in await list_imap_poll_accounts()
        if int(a.get("user_id") or 0) == int(user_id)
    ]
    if not accs:
        return "📬 IMAP: нет SMTP-ящиков.\n"
    if not poll:
        return (
            "📬 IMAP: ящики есть, но нет пароля/IMAP — входящие не придут.\n"
            "Перепроверьте ⚡ Быстрое добавление или /imap_check.\n"
        )
    return f"📬 IMAP: <b>{len(poll)}</b> ящ., авто-опрос ~20 с (как в happy88).\n"


def _menu_text(
    emails: List[str],
    *,
    sender_name: str | None,
    proxy_line: str,
    imap_line: str,
) -> str:
    fixtures = load_test_fixtures()
    fx_lines = ""
    if fixtures:
        fx_lines = "\n<b>Тест-товары (OFFER / фото / GAG):</b>\n"
        for i, fx in enumerate(fixtures[:5]):
            fx_lines += f"{i + 1}. <code>{e(fixture_label(fx))}</code>\n"

    from_line = ""
    sn = (sender_name or "").strip()
    if sn:
        from_line = f"<b>From:</b> <code>{e(sn)}</code>\n"
    else:
        from_line = "⚠️ Задайте имя в ⚡ Быстрое добавление.\n"

    if not emails:
        return (
            "🧪 <b>Тест маил</b>\n\n"
            f"{from_line}{proxy_line}{imap_line}\n"
            "Тема = <code>OFFER</code> (название товара из фикстуры).\n"
            f"{fx_lines}\n"
            "Список получателей пуст — «➕ Добавить email».\n"
            "Ответ в бот: реальный IMAP или «📥 Симуляция ответа»."
        )
    lines = "\n".join(
        f"{i + 1}. <code>{e(em)}</code>" for i, em in enumerate(emails)
    )
    return (
        "🧪 <b>Тест маил</b>\n\n"
        f"{from_line}{proxy_line}{imap_line}\n"
        "▶️ Отправка: тема = товар из JSON, лид на email получателя (GAG/фото).\n"
        f"{fx_lines}\n"
        f"<b>Получатели ({len(emails)}):</b>\n{lines}\n"
        "Ответ в Gmail → карточка в боте только через IMAP (тот же ящик, что слал письмо)."
    )


def _menu_kb(emails: List[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    fixtures = load_test_fixtures()

    if emails:
        rows.append(
            [
                InlineKeyboardButton(
                    text="▶️ Отправить на все", callback_data="tm_send:all"
                )
            ]
        )
        for i, em in enumerate(emails[:8]):
            label = em if len(em) <= 28 else em[:25] + "…"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"📤 {label}", callback_data=f"tm_send:{i}"
                    )
                ]
            )

    if fixtures:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📥 Симуляция ответа продавца",
                    callback_data="tm_sim_menu",
                )
            ]
        )

    rows.append(
        [InlineKeyboardButton(text="➕ Добавить email", callback_data="tm_add")]
    )
    if emails:
        rows.append(
            [InlineKeyboardButton(text="🗑 Очистить список", callback_data="tm_clear")]
        )
    rows.append(
        [InlineKeyboardButton(text="✏️ Разовый email", callback_data="tm_oneoff")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sim_menu_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, fx in enumerate(load_test_fixtures()[:5]):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📥 {i + 1}. {fixture_label(fx, max_len=28)}",
                    callback_data=f"tm_sim:{i}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tm_back_menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_menu(message: Message, user_id: int, *, edit: bool = False) -> None:
    emails = await _load_recipients(user_id)
    sn = await get_user_sender_name(user_id)
    text = _menu_text(
        emails,
        sender_name=sn,
        proxy_line=await _proxy_hint(user_id),
        imap_line=await _imap_hint(user_id),
    )
    kb = _menu_kb(emails)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


async def _send_test_one(
    settings: Settings,
    user_id: int,
    *,
    to_email: str,
    fixture: dict,
) -> tuple[bool, str]:
    accounts = await list_smtp_mailing_accounts(user_id, with_secrets=True)
    if not accounts:
        return False, "Нет SMTP-аккаунтов"
    account = accounts[0]

    offer_title = (fixture.get("item_title") or "").strip()
    subject = offer_title or "OFFER"

    body = await pick_random_smart_preset(user_id, offer_title)
    if not (body or "").strip():
        body = f"Hallo! Ist «{offer_title or 'OFFER'}» noch verfügbar?"
    else:
        body = apply_offer_to_text(body, offer_title)

    send_timeout = float(os.getenv("TEST_MAIL_SEND_TIMEOUT_SEC", "50"))
    try:
        await asyncio.wait_for(
            send_mail(
                settings,
                user_id,
                to_addr=to_email,
                subject=subject,
                body=body,
                is_html=False,
                account=account,
            ),
            timeout=send_timeout,
        )
    except asyncio.TimeoutError:
        return False, f"Таймаут отправки ({int(send_timeout)} с)"
    except NoLiveProxyError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, str(exc)[:200]

    try:
        lead_id = await register_test_mail_lead(user_id, to_email, fixture)
    except Exception as exc:
        lead_id = None
        lead_err = str(exc)[:120]
    else:
        lead_err = ""
    lead_hint = ""
    if lead_id:
        photo = "📷" if (fixture.get("item_photo") or "").strip() else ""
        price = (fixture.get("item_price") or "").strip()
        lead_hint = (
            f"\n🧾 Лид #{lead_id} (фото/цена/GAG из JSON) {photo}"
            + (f" · <code>{e(price)}</code>" if price else "")
        )
    elif lead_err:
        lead_hint = f"\n⚠️ Лид не сохранён: {e(lead_err)}"

    return True, (
        f"✅ <code>{e(to_email)}</code>\n"
        f"Тема: <code>{e(subject)}</code>{lead_hint}"
    )


async def _run_test_batch(
    *,
    bot,
    settings: Settings,
    chat_id: int,
    user_id: int,
    targets: List[str],
    status_message: Message,
) -> None:
    ok_n = 0
    fail_n = 0
    lines: list[str] = []
    fixtures = load_test_fixtures()

    for i, to_email in enumerate(targets):
        if i > 0:
            await asyncio.sleep(3)
        fx = fixtures[i % len(fixtures)] if fixtures else {}
        if not fx:
            fx = pick_random_test_fixture() or {}
        ok, line = await _send_test_one(settings, user_id, to_email=to_email, fixture=fx)
        if ok:
            ok_n += 1
        else:
            fail_n += 1
        lines.append(line)
        try:
            await status_message.edit_text(
                f"⏳ {i + 1}/{len(targets)}\n\n" + "\n".join(lines[-6:]),
                parse_mode="HTML",
            )
        except Exception:
            pass

    summary = (
        f"<b>Тест завершён</b> — OK: {ok_n}, ошибок: {fail_n}\n\n"
        + "\n".join(lines)
    )
    if ok_n > 0:
        summary += (
            "\n\n📬 <i>IMAP опрашивается в фоне (~1 мин). "
            "Ответ продавца придёт карточкой или через «📥 Симуляция».</i>"
        )
    try:
        await status_message.edit_text(summary, parse_mode="HTML")
    except Exception:
        await bot.send_message(chat_id, summary, parse_mode="HTML")

    if ok_n > 0:
        asyncio.create_task(
            _imap_after_test(bot, chat_id, user_id, status_message.message_id)
        )


async def _imap_after_test(
    bot, chat_id: int, user_id: int, reply_to_message_id: int
) -> None:
    """Не блокирует «Тест уже идёт» — отдельно от bg_jobs test_mail."""
    imap_timeout = float(os.getenv("TEST_MAIL_IMAP_TIMEOUT_SEC", "90"))
    try:
        acc_n, mail_n = await asyncio.wait_for(
            poll_incoming_for_user(bot, user_id, catch_up=True),
            timeout=imap_timeout,
        )
        text = f"📬 <b>IMAP после теста:</b> {acc_n} ящ., новых карточек: {mail_n}"
        if acc_n == 0:
            text += "\n⚠️ Нет ящиков с IMAP — /imap_check или ⚡ Быстрое добавление."
        elif mail_n == 0:
            text += (
                "\n<i>Новых писем нет (ответ ещё не пришёл). "
                "Подождите или «📥 Симуляция ответа».</i>"
            )
    except asyncio.TimeoutError:
        text = (
            f"📬 IMAP: опрос прерван через {int(imap_timeout)} с "
            "(много ящиков). Авто-опрос продолжит ловить ответ."
        )
    except Exception:
        logger.exception("test_mail IMAP follow-up failed user_id=%s", user_id)
        text = "📬 IMAP: не удалось опросить (см. логи Railway)."
    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_to_message_id=reply_to_message_id,
        )
    except Exception:
        await bot.send_message(chat_id, text, parse_mode="HTML")


@router.message(F.text == "🧪 Тест маил")
@router.message(Command("test_mail"))
async def test_mail_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_menu(message, message.from_user.id)


@router.callback_query(F.data == "tm_back_menu")
async def cb_tm_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show_menu(callback.message, callback.from_user.id, edit=True)
    await callback.answer()


@router.callback_query(F.data == "tm_sim_menu")
async def cb_tm_sim_menu(callback: CallbackQuery) -> None:
    if not load_test_fixtures():
        return await callback.answer("Нет test_mail_fixtures.json", show_alert=True)
    await callback.message.edit_text(
        "📥 <b>Симуляция ответа продавца</b>\n\n"
        "Выберите товар. Первое письмо от этого продавца — с 📷 под карточкой.\n"
        "Потом: «Создать ссылку» → «Написать ещё» → HTML.",
        parse_mode="HTML",
        reply_markup=_sim_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tm_sim:"))
async def cb_tm_sim(callback: CallbackQuery) -> None:
    try:
        idx = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    fx = get_test_fixture(idx)
    if not fx:
        return await callback.answer("Товар не найден", show_alert=True)

    uid = callback.from_user.id
    if bg_is_running(uid, "test_sim"):
        return await callback.answer("⏳ Уже идёт…", show_alert=True)

    await callback.answer("⏳ Создаю карточку…", show_alert=False)

    async def _job() -> None:
        ok, msg = await simulate_seller_reply(callback.bot, uid, fx)
        text = msg if ok else f"❌ {msg}"
        await callback.bot.send_message(
            callback.message.chat.id,
            text,
            parse_mode="HTML",
            reply_to_message_id=callback.message.message_id,
        )

    if not bg_start(uid, "test_sim", _job()):
        await callback.answer("⏳ Уже идёт…", show_alert=True)


@router.callback_query(F.data == "tm_add")
async def cb_tm_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TestMailStates.waiting_add)
    await callback.message.answer(
        "➕ Email (по строке или через запятую). «-» — отмена.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "tm_oneoff")
async def cb_tm_oneoff(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TestMailStates.waiting_oneoff)
    await callback.message.answer("✏️ Разовый email. «-» — отмена.", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "tm_clear")
async def cb_tm_clear(callback: CallbackQuery, state: FSMContext) -> None:
    uid = callback.from_user.id
    await _save_recipients(uid, [])
    await state.clear()
    await callback.answer("Очищено")
    await _show_menu(callback.message, uid, edit=True)


@router.callback_query(F.data.startswith("tm_send:"))
async def cb_tm_send(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    uid = callback.from_user.id
    key = (callback.data or "").split(":", 1)[1]
    emails = await _load_recipients(uid)
    if not emails:
        return await callback.answer("Список пуст", show_alert=True)

    if key == "all":
        targets = list(emails)
    else:
        try:
            targets = [emails[int(key)]]
        except (ValueError, IndexError):
            return await callback.answer("Неверный адрес", show_alert=True)

    own = await _sender_account_emails(uid)
    targets = [t for t in targets if _canon_email(t) not in own]
    if not targets:
        return await callback.answer("Нельзя слать на свой SMTP-ящик", show_alert=True)

    if bg_is_running(uid, "test_mail"):
        return await callback.answer("⏳ Тест уже идёт…", show_alert=True)

    if await user_has_proxies(uid) and await live_proxy_count(uid) < 1:
        return await callback.answer(
            "Нет живых прокси (HTML не уйдёт). Проверьте 🌐 Прокси.",
            show_alert=True,
        )

    await state.clear()
    await callback.answer("⏳ Отправляю…")
    status = await callback.message.answer(
        f"⏳ Тест на {len(targets)} адр…", parse_mode="HTML"
    )

    async def _job() -> None:
        await _run_test_batch(
            bot=callback.bot,
            settings=settings,
            chat_id=callback.message.chat.id,
            user_id=uid,
            targets=targets,
            status_message=status,
        )

    if not bg_start(uid, "test_mail", _job()):
        await callback.answer("⏳ Уже идёт…", show_alert=True)


@router.message(TestMailStates.waiting_add)
async def tm_add_emails(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text in {"-", "cancel"}:
        await state.clear()
        return await _show_menu(message, message.from_user.id)

    new_emails = _parse_emails(text)
    if not new_emails:
        return await message.answer("❌ Нет валидных email.")

    uid = message.from_user.id
    current = await _load_recipients(uid)
    merged = list(current)
    seen = set(current)
    added = 0
    for em in new_emails:
        if em in seen or len(merged) >= MAX_TEST_RECIPIENTS:
            continue
        merged.append(em)
        seen.add(em)
        added += 1

    await _save_recipients(uid, merged)
    await state.clear()
    await message.answer(f"✅ Добавлено: {added}. Всего: {len(merged)}.")
    await _show_menu(message, uid)


@router.message(TestMailStates.waiting_oneoff)
async def tm_oneoff(message: Message, state: FSMContext, settings: Settings) -> None:
    text = (message.text or "").strip()
    if text in {"-", "cancel"}:
        await state.clear()
        return

    targets = _parse_emails(text)
    if not targets:
        return await message.answer("❌ Нет валидных email.")

    uid = message.from_user.id
    own = await _sender_account_emails(uid)
    targets = [t for t in targets if _canon_email(t) not in own]
    if not targets:
        return await message.answer("Нельзя на свой SMTP-ящик.")

    if bg_is_running(uid, "test_mail"):
        return await message.answer("⏳ Тест уже идёт…")

    await state.clear()
    status = await message.answer(f"⏳ Разовый тест…", parse_mode="HTML")

    async def _job() -> None:
        await _run_test_batch(
            bot=message.bot,
            settings=settings,
            chat_id=message.chat.id,
            user_id=uid,
            targets=targets,
            status_message=status,
        )

    bg_start(uid, "test_mail", _job())

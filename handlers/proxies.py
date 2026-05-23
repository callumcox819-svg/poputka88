"""Прокси SOCKS5: добавление, проверка, удаление."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import (
    add_proxy,
    delete_all_proxies,
    delete_proxy,
    get_proxy,
    list_proxies,
    update_proxy_status,
)
from services.proxy_parse import parse_proxy_block, parse_proxy_string, reject_non_socks5
from services.proxy_pool import reset_round_robin
from services.proxy_refresh import refresh_user_proxies
from services.proxy_verify import apply_check_status, test_proxy_socks
from utils.bg_jobs import is_running as bg_is_running, start as bg_start
from utils.callback_edit import cq_edit_text

router = Router()
logger = logging.getLogger(__name__)

_bulk_check_tasks: dict[int, asyncio.Task] = {}


class ProxyAddStates(StatesGroup):
    waiting_for_list = State()


def _status_emoji(is_active: int | None) -> str:
    if is_active == 1:
        return "🟢"
    if is_active == 0:
        return "🔴"
    return "🟡"


def _proxy_counts(proxies: list[dict]) -> tuple[int, int, int]:
    ok = unk = bad = 0
    for p in proxies:
        st = p.get("is_active")
        if st == 1:
            ok += 1
        elif st == 0:
            bad += 1
        else:
            unk += 1
    return ok, unk, bad


def _proxies_kb(proxies: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in proxies:
        st = _status_emoji(p.get("is_active"))
        ptype = (p.get("proxy_type") or "socks5").lower()
        label = f"{st} {ptype} {p['host']}:{p['port']}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label, callback_data=f"proxy_info:{p['id']}"
                ),
                InlineKeyboardButton(text="🗑", callback_data=f"proxy_del:{p['id']}"),
                InlineKeyboardButton(text="🔄", callback_data=f"proxy_test:{p['id']}"),
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="➕ Добавить прокси", callback_data="proxy_add_menu")]
    )
    if proxies:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔍 Проверить прокси", callback_data="proxies_check_all"
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Удалить все прокси", callback_data="proxies_delete_all"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_proxy_menu(target: Message | CallbackQuery, user_id: int) -> None:
    proxies = await list_proxies(user_id)
    ok_n, unk_n, bad_n = _proxy_counts(proxies)
    text = (
        "🌐 <b>Прокси (SOCKS5)</b>\n\n"
        f"Всего: {len(proxies)}\n"
        f"🟢 OK: {ok_n} · 🟡 не проверен: {unk_n} · 🔴 мёртв: {bad_n}\n\n"
        "<i>Все исходящие письма (рассылка, ответы, HTML) идут только через "
        "живые SOCKS5 из этого списка — по очереди, без привязок.</i>\n"
        "<i>🟢 и 🟡 участвуют в пуле; 🔴 пропускается.</i>"
    )
    kb = _proxies_kb(proxies)
    if isinstance(target, CallbackQuery):
        await cq_edit_text(target, text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "settings_proxies")
async def open_proxies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    reset_round_robin(callback.from_user.id)
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass
    await render_proxy_menu(callback, callback.from_user.id)


@router.callback_query(F.data == "proxy_add_menu")
async def proxy_add_menu(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass
    await state.set_state(ProxyAddStates.waiting_for_list)
    await cq_edit_text(
        callback,
        "📝 <b>Только SOCKS5</b> (HTTP не поддерживается).\n"
        "Пришли список прокси (по одному на строку) или карточкой.\n\n"
        "<b>Примеры:</b>\n"
        "<code>socks5://user:pass@109.104.153.100:10811</code>\n"
        "<code>109.104.153.100:10811:user:pass:socks5</code>\n"
        "<code>user:pass@109.104.153.100:10811</code>\n\n"
        "Каждый прокси будет проверен перед добавлением.",
    )


def _split_proxy_input(raw_text: str) -> list[tuple[str, dict | None]]:
    blocks: list[str] = []
    cur: list[str] = []
    for ln in raw_text.splitlines():
        if not ln.strip():
            if cur:
                blocks.append("\n".join(cur).strip())
                cur = []
        else:
            cur.append(ln.strip())
    if cur:
        blocks.append("\n".join(cur).strip())

    def _has_kv(t: str) -> bool:
        s = t.lower()
        return any(
            k in s
            for k in (
                "тип прокси",
                "хост",
                "порт",
                "логин",
                "пароль",
                "username",
                "password",
                "type=",
            )
        )

    items: list[tuple[str, dict | None]] = []
    if len(blocks) == 1 and not _has_kv(blocks[0]):
        for line in [l.strip() for l in raw_text.splitlines() if l.strip()]:
            items.append((line, parse_proxy_string(line)))
    else:
        for b in blocks:
            if _has_kv(b):
                items.append((b, parse_proxy_block(b)))
            elif "\n" in b:
                for line in [l.strip() for l in b.splitlines() if l.strip()]:
                    items.append((line, parse_proxy_string(line)))
            else:
                items.append((b, parse_proxy_string(b)))
    return items


@router.message(ProxyAddStates.waiting_for_list)
async def proxy_add_process(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ Пусто. Пришли прокси строками или карточкой.")
        return

    user_id = message.from_user.id
    parsed_items = _split_proxy_input(raw)

    if bg_is_running(user_id, "proxy_add"):
        await message.answer("⏳ Добавление уже идёт. Подождите.")
        return

    status_msg = await message.answer(
        f"⏳ Проверяю <b>{len(parsed_items)}</b> прокси…",
        parse_mode="HTML",
    )

    async def _job() -> None:
        await _proxy_add_work(message, state, user_id, parsed_items, status_msg)

    if not bg_start(user_id, "proxy_add", _job()):
        await message.answer("⏳ Добавление уже идёт. Подождите.")


async def _proxy_add_work(
    message: Message,
    state: FSMContext,
    user_id: int,
    parsed_items: list[tuple[str, dict | None]],
    status_msg: Message,
) -> None:
    ok_count = fail_count = 0
    details: list[str] = []

    for raw_line, parsed in parsed_items:
        if not parsed:
            fail_count += 1
            details.append(f"❌ `{raw_line[:80]}` — не распознано")
            continue
        err = reject_non_socks5(parsed)
        if err:
            fail_count += 1
            details.append(f"❌ `{raw_line[:60]}` — {err}")
            continue

        pdata = {
            "host": parsed["host"],
            "port": parsed["port"],
            "username": parsed.get("username"),
            "password": parsed.get("password"),
            "type": "socks5",
        }
        ok, info = await test_proxy_socks(pdata)
        active, last_err = apply_check_status(None, ok, info)
        if not ok:
            fail_count += 1
            details.append(f"❌ `{parsed['host']}:{parsed['port']}` — {info[:120]}")
            continue

        await add_proxy(
            user_id,
            host=parsed["host"],
            port=int(parsed["port"]),
            username=parsed.get("username"),
            password=parsed.get("password"),
            proxy_type="socks5",
            is_active=active,
            last_error=last_err,
        )
        ok_count += 1
        details.append(f"✅ `{parsed['host']}:{parsed['port']}`")

    reset_round_robin(user_id)
    summary = (
        f"Готово.\n\nДобавлено: {ok_count}\nОшибок: {fail_count}\n\n"
        + "\n".join(details[:40])
    )
    if len(details) > 40:
        summary += f"\n…ещё {len(details) - 40}"
    try:
        await status_msg.edit_text(summary[:4000])
    except Exception:
        await message.answer(summary[:4000])
    await state.clear()
    await render_proxy_menu(message, user_id)


@router.callback_query(F.data.startswith("proxy_info:"))
async def proxy_info(callback: CallbackQuery) -> None:
    proxy_id = int(callback.data.split(":")[1])
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass
    p = await get_proxy(proxy_id, callback.from_user.id)
    if not p:
        return
    st = p.get("is_active")
    if st == 1:
        st_line = "🟢 Проверка OK"
    elif st == 0:
        st_line = "🔴 Мёртв"
    else:
        st_line = "🟡 Не проверен / в пуле рассылки"
    text = (
        "🧩 <b>Прокси</b>\n\n"
        f"Host: <code>{p['host']}</code>\n"
        f"Port: <code>{p['port']}</code>\n"
        f"Type: <code>{p.get('proxy_type') or 'socks5'}</code>\n"
        f"Login: <code>{p.get('username') or '—'}</code>\n"
        f"Статус: {st_line}\n"
        f"Ошибка: <code>{p.get('last_error') or '—'}</code>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Проверить", callback_data=f"proxy_test:{proxy_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data="settings_proxies"
                )
            ],
        ]
    )
    await cq_edit_text(callback, text, reply_markup=kb)


@router.callback_query(F.data.startswith("proxy_del:"))
async def proxy_delete_one(callback: CallbackQuery) -> None:
    proxy_id = int(callback.data.split(":")[1])
    try:
        await callback.answer("Удаляю…")
    except TelegramBadRequest:
        pass
    await delete_proxy(callback.from_user.id, proxy_id)
    reset_round_robin(callback.from_user.id)
    await render_proxy_menu(callback, callback.from_user.id)


@router.callback_query(F.data == "proxies_delete_all")
async def proxies_delete_all(callback: CallbackQuery) -> None:
    n = await delete_all_proxies(callback.from_user.id)
    reset_round_robin(callback.from_user.id)
    try:
        await callback.answer(f"Удалено: {n}", show_alert=True)
    except TelegramBadRequest:
        pass
    await render_proxy_menu(callback, callback.from_user.id)


@router.callback_query(F.data.startswith("proxy_test:"))
async def proxy_test_one(callback: CallbackQuery) -> None:
    proxy_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    p = await get_proxy(proxy_id, user_id)
    if not p:
        return
    try:
        await callback.answer("⏳ Проверяю…")
    except TelegramBadRequest:
        pass
    pdata = {
        "host": p["host"],
        "port": p["port"],
        "username": p.get("username"),
        "password": p.get("password"),
    }
    ok, info = await test_proxy_socks(pdata)
    active, err = apply_check_status(None, ok, info)
    await update_proxy_status(proxy_id, user_id, is_active=active, last_error=err)
    try:
        await callback.answer("✅ OK" if ok else f"❌ {info[:180]}", show_alert=not ok)
    except TelegramBadRequest:
        pass
    await render_proxy_menu(callback, user_id)


@router.callback_query(F.data == "proxies_check_all")
async def proxies_check_all(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    existing = _bulk_check_tasks.get(user_id)
    if existing and not existing.done():
        try:
            await callback.answer("⏳ Проверка уже идёт…", show_alert=True)
        except TelegramBadRequest:
            pass
        return

    proxies = await list_proxies(user_id)
    if not proxies:
        try:
            await callback.answer("Нет прокси", show_alert=True)
        except TelegramBadRequest:
            pass
        return

    try:
        await callback.answer("⏳ Запускаю проверку…")
    except TelegramBadRequest:
        pass

    await cq_edit_text(
        callback,
        f"⏳ <b>Проверяю {len(proxies)} прокси…</b>\n\n"
        "<i>SOCKS5 → smtp.gmail.com:587</i>",
    )

    async def _run() -> None:
        concurrency = max(1, min(5, int(os.getenv("PROXY_CHECK_CONCURRENCY", "3"))))
        timeout = max(15, min(40, int(os.getenv("PROXY_CHECK_TIMEOUT", "22"))))
        try:
            ok_n, fail_n, total = await refresh_user_proxies(
                user_id, concurrency=concurrency, timeout=timeout
            )
            await cq_edit_text(
                callback,
                f"✅ Проверка завершена.\n\n"
                f"Всего: {total}\n🟢 OK: {ok_n}\n❌ Ошибка: {fail_n}",
                reply_markup=_proxies_kb(await list_proxies(user_id)),
            )
        except Exception:
            logger.exception("bulk proxy check failed user_id=%s", user_id)
        finally:
            _bulk_check_tasks.pop(user_id, None)

    _bulk_check_tasks[user_id] = asyncio.create_task(_run())

"""Карточка GAG-ссылки — reply к входящему письму (как happy88)."""

from __future__ import annotations

from aiogram import Bot
from utils.text_html import e


def _service_label_for_card(service_label: str) -> str:
    s = (service_label or "").strip()
    return s or "Marketplace"


async def send_generated_link_card(
    bot: Bot,
    chat_id: int,
    *,
    offer_title: str,
    offer_price: str,
    photo_url: str,
    profile_title: str,
    service_label: str,
    link: str,
    anchor_message_id: int,
) -> None:
    """Фото + название + цена + ссылка — ответом на карточку письма."""
    svc = _service_label_for_card(service_label)
    card_text = (
        f"📣 <b>Объявления » {e(svc)}</b>\n\n"
        f"📌 <b>Название:</b> {e((offer_title or '').strip()) or '—'}\n"
        f"💰 <b>Цена:</b> {e((offer_price or '').strip()) or '—'}\n"
        f"👤 <b>Профиль:</b> <code>{e((profile_title or '').strip()) or '—'}</code>\n\n"
        f"🔗 <b>Ссылка:</b>\n{e(link)}"
    )
    reply_to = int(anchor_message_id)
    p = (photo_url or "").strip()

    if not p:
        await bot.send_message(
            chat_id,
            card_text + "\n\n<i>Фото объявления не найдено в БД.</i>",
            parse_mode="HTML",
            reply_to_message_id=reply_to,
        )
    else:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=p,
                caption=card_text,
                parse_mode="HTML",
                reply_to_message_id=reply_to,
            )
        except Exception:
            await bot.send_message(
                chat_id,
                card_text + "\n\n<i>Не удалось отправить фото объявления.</i>",
                parse_mode="HTML",
                reply_to_message_id=reply_to,
            )

    try:
        await bot.send_message(
            chat_id, "✅ Ссылка создана", reply_to_message_id=reply_to
        )
    except Exception:
        await bot.send_message(chat_id, "✅ Ссылка создана")

    try:
        await bot.pin_chat_message(chat_id, reply_to, disable_notification=True)
    except Exception:
        pass

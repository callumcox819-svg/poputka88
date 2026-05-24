"""Карточка входящего письма (как happy88): HTML + expandable blockquote + кнопки."""

from __future__ import annotations

import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.link_id import link_id_from_generated_url
from utils.text_html import e


def strip_html_to_text(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    t = re.sub(r"</p\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    return t


def clean_mail_body_for_card(raw: str) -> str:
    if not raw:
        return ""
    txt = raw
    low = txt.lower()
    if "<style" in low or "<html" in low or "<div" in low or "<span" in low:
        txt = re.sub(r"(?is)<style[^>]*>.*?</style>", "", txt)
        txt = strip_html_to_text(txt)
    lines: list[str] = []
    for line in txt.replace("\r", "\n").split("\n"):
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^[\.\#\@\w\-\s,\[\]:]+\{", s):
            continue
        if re.match(r"^[\}\s;]+$", s):
            continue
        if s.startswith("@media") or s.startswith("@font-face"):
            continue
        lines.append(line.rstrip())
    txt = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def ensure_multiline_for_expandable(text: str) -> str:
    if not text:
        return "—"
    if "\n" in text:
        return text
    if len(text) <= 120:
        return text
    return "\n".join(text[i : i + 100] for i in range(0, len(text), 100))


def service_html(label: str) -> str:
    s = (label or "").strip()
    if not s:
        return ""
    return f"<code>{e(s)}</code>"


def render_mail_text(
    *,
    account_email: str,
    inbox_label: str | None = None,
    from_name: str,
    from_email: str,
    subject: str,
    body: str,
    link_id: str | None = None,
    service_label: str | None = None,
    product_title: str | None = None,
    offer_price: str | None = None,
    translation: str | None = None,
) -> str:
    shown = ensure_multiline_for_expandable(clean_mail_body_for_card((body or "").strip()))

    extra = ""
    lid = (link_id or "").strip()
    if lid:
        extra += f"<b>ID:</b> <code>{e(lid)}</code>\n"
    if service_label:
        extra += f"<b>Сервис:</b> {service_html(service_label)}\n"
    if product_title:
        extra += f"<b>Товар:</b> <code>{e(product_title)}</code>\n"
    price = (offer_price or "").strip()
    if price:
        extra += f"<b>Цена:</b> <code>{e(price)}</code>\n"
    if extra:
        extra = "\n" + extra

    label = (inbox_label or "").strip()
    if label:
        label_line = f'⚡ Получено сообщение на "<b>{e(label)}</b>"'
    else:
        label_line = f"⚡ Получено сообщение на <code>{e(account_email)}</code>"

    from_disp = (from_name or "").strip() or from_email
    head = (
        f"{label_line}\n"
        f"<code>{e(account_email)}</code>\n"
        f'от "<code>{e(from_disp)}</code>" <code>{e(from_email)}</code>\n'
        f"{extra}\n"
        f"<b>Тема:</b>\n<blockquote><code>{e(subject or '—')}</code></blockquote>\n\n"
        f"<b>Текст:</b>\n"
    )

    body_limit = 1400 if translation else 3200
    body_text = e((shown[:body_limit] if shown else "—"))
    msg = head + f"<blockquote expandable><code>{body_text}</code></blockquote>"
    if translation:
        tr = ensure_multiline_for_expandable(str(translation)[:1400])
        msg += (
            "\n\n<b>Перевод:</b>\n"
            f"<blockquote expandable><code>{e(tr)}</code></blockquote>"
        )
    return msg


def build_incoming_kb(
    account_id: int,
    imap_uid: str,
    *,
    mail_id: int | None = None,
) -> InlineKeyboardMarkup:
    translate_cb = (
        f"mail_translate:{mail_id}" if mail_id else f"mail_translate_stub:{account_id}:{imap_uid}"
    )
    link_cb = f"goo_mail:{mail_id}" if mail_id else f"goo_link_stub:{account_id}:{imap_uid}"
    reply_cb = (
        f"mail_reply:{mail_id}"
        if mail_id
        else f"mail_reply_stub:{account_id}:{imap_uid}"
    )
    rows = [
        [InlineKeyboardButton(text="🌍 Перевести", callback_data=translate_cb)],
        [InlineKeyboardButton(text="🔗 Создать ссылку", callback_data=link_cb)],
        [InlineKeyboardButton(text="📝 Написать ещё", callback_data=reply_cb)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_card_from_mail_row(
    mail: dict,
    *,
    inbox_label: str | None = None,
    translation: str | None = None,
    include_product_extras: bool = True,
) -> tuple[str, InlineKeyboardMarkup]:
    gen = (mail.get("generated_link") or "").strip()
    link_id = link_id_from_generated_url(gen) if gen else None
    title = (mail.get("product_title") or "").strip() or None
    price = (mail.get("offer_price") or "").strip() or None
    if not include_product_extras:
        title = None
        price = None
    text = render_mail_text(
        account_email=(mail.get("account_email") or "").strip(),
        inbox_label=inbox_label,
        from_name=(mail.get("from_name") or "").strip(),
        from_email=(mail.get("from_email") or "").strip(),
        subject=(mail.get("subject") or "").strip(),
        body=(mail.get("body") or "").strip(),
        link_id=link_id,
        service_label=(mail.get("service_label") or "").strip() or None,
        product_title=title,
        offer_price=price,
        translation=translation,
    )
    kb = build_incoming_kb(
        int(mail["account_id"]),
        str(mail.get("imap_uid") or ""),
        mail_id=int(mail["id"]) if mail.get("id") else None,
    )
    return text, kb

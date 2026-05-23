"""HTML-рассылка: шаблоны data/HTMLch/<сервис>/ и переменные как в happy88."""

from __future__ import annotations

import re

from database import get_gag_generated_link, get_validated_lead_by_email
from services.gag_keys import GAG_PROFILE_ADDRESS_KEY, GAG_PROFILE_NAME_KEY
from services.html_templates import GO_FILENAME, load_html_template_for_user
from services.placeholders import apply_placeholders
from services.user_settings import get_setting

_INLINE_HTML_RE = re.compile(r"^\s*<(?:!DOCTYPE|html|body|table|div)\b", re.I)


def body_is_inline_html(body: str) -> bool:
    return bool(_INLINE_HTML_RE.match(body or ""))


def resolve_template_filename(body: str) -> str | None:
    """
    Имя файла в HTMLch или None, если в body уже вставлен полный HTML.
    Пусто / «-» → confirmation.html.
    """
    b = (body or "").strip()
    if not b or b in {"-", "—", "default"}:
        return GO_FILENAME
    if body_is_inline_html(b):
        return None
    name = b.split()[0].strip()
    if not name.lower().endswith(".html"):
        name = f"{name}.html"
    return name


def _format_chf_price(price: str) -> str:
    p = (price or "").strip()
    if not p:
        return ""
    if p.upper().startswith("CHF"):
        return p
    return f"CHF {p}"


async def build_lead_html_ctx(
    user_id: int, seller_email: str, lead: dict | None
) -> dict[str, str]:
    buyer = (await get_setting(user_id, GAG_PROFILE_NAME_KEY) or "").strip()
    address = (await get_setting(user_id, GAG_PROFILE_ADDRESS_KEY) or "").strip()
    if lead:
        title = (lead.get("item_title") or "").strip()
        price = _format_chf_price(str(lead.get("item_price") or ""))
        photo = (lead.get("item_photo") or "").strip()
    else:
        title = price = photo = ""
    return {
        "ITEM_TITLE": title,
        "PRICE": price,
        "IMAGE_URL": photo,
        "SELLER_EMAIL": seller_email.strip().lower(),
        "BUYER_NAME": buyer,
        "ADDRESS": address,
        "LINK": "",
    }


async def render_campaign_html(
    user_id: int,
    *,
    camp_body: str,
    to_email: str,
) -> tuple[str, str | None]:
    """Собрать HTML для одного получателя рассылки."""
    filename = resolve_template_filename(camp_body)
    if filename is None:
        html = camp_body
    else:
        html, err = await load_html_template_for_user(user_id, filename)
        if err:
            return "", err

    gag_link = await get_gag_generated_link(user_id, seller_email=to_email)
    if not gag_link:
        return (
            "",
            "Нет GAG-ссылки для этого продавца. Сначала «🔗 Создать ссылку» во входящем письме.",
        )

    lead = await get_validated_lead_by_email(user_id, to_email)
    ctx = await build_lead_html_ctx(user_id, to_email, lead)
    ctx["LINK"] = gag_link
    html = apply_placeholders(html, link=gag_link, ctx=ctx)

    sig = (await get_setting(user_id, "html_signature") or "").strip()
    if sig:
        html = html.replace("{{SIGNATURE}}", sig)

    return html, None

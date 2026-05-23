"""Поля товара из JSON-фикстуры (любые ключи void-parser / test_mail)."""

from __future__ import annotations

import json
from typing import Any


def _first_str(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def normalize_fixture_fields(fx: dict[str, Any]) -> dict[str, str]:
    """Канонические поля лида из любого JSON-объекта."""
    title = _first_str(fx, "item_title", "title", "product_title", "name")
    price = _first_str(fx, "item_price", "price", "offer_price")
    link = _first_str(fx, "item_link", "link", "url", "offer_link")
    photo = _first_str(fx, "item_photo", "photo", "image", "image_url", "item_image")
    person = _first_str(fx, "person_name", "seller_name", "name_seller", "seller")
    location = _first_str(fx, "location", "city", "place")
    reply = _first_str(fx, "reply_body", "body", "message")
    seller_email = _first_str(fx, "seller_email", "email", "contact_email").lower()
    return {
        "item_title": title,
        "item_price": price,
        "item_link": link,
        "item_photo": photo,
        "person_name": person,
        "location": location,
        "reply_body": reply,
        "seller_email": seller_email,
        "raw_json": json.dumps(fx, ensure_ascii=False),
    }


def subject_stripped_title(subject: str) -> str:
    s = (subject or "").strip()
    for _ in range(4):
        low = s.lower()
        for p in ("re:", "fwd:", "aw:", "wg:", "sv:", "antw:", "ré:", "fw:"):
            if low.startswith(p):
                s = s[len(p) :].strip()
                break
        else:
            break
    return s.strip()

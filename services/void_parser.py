"""Разбор JSON void-parser (items с объявлениями)."""

from __future__ import annotations

import json
from typing import Any


def parse_void_json_bytes(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    data = json.loads(text)
    return extract_items(data)


def parse_void_json_text(text: str) -> list[dict[str, Any]]:
    data = json.loads((text or "").strip())
    return extract_items(data)


def extract_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def seller_dedupe_key(item: dict[str, Any]) -> str:
    link = str(item.get("person_link") or "").strip().lower()
    if link:
        return f"link:{link}"
    from services.seller_name import normalize_seller_name, seller_name_from_item

    name = normalize_seller_name(seller_name_from_item(item)).lower()
    return f"name:{name}" if name else ""

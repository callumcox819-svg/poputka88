"""Пресеты и умные пресеты — хранение и подбор текста."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from services.offer_text import apply_offer_to_text
from services.spintax import expand_spintax
from services.user_json_store import load_json_blob, save_json_blob

MAX_TITLE_LEN = 40
MAX_TEXT_LEN = 4000


@dataclass
class TemplateItem:
    title: str
    text: str


def _items_from_json(data: object) -> list[TemplateItem]:
    out: list[TemplateItem] = []
    for x in data if isinstance(data, list) else []:
        if isinstance(x, str):
            text = x.strip()
            if text:
                short = text[:40] + ("…" if len(text) > 40 else "")
                out.append(TemplateItem(title=short, text=text))
            continue
        if not isinstance(x, dict):
            continue
        title = str(x.get("title", "")).strip()
        text = str(x.get("text", "")).strip()
        if not text and title:
            text = title
        if text:
            if not title:
                title = text[:40] + ("…" if len(text) > 40 else "")
            out.append(TemplateItem(title=title, text=text))
    return out


def parse_preset_name_dash_text(raw: str) -> tuple[str, str] | None:
    s = (raw or "").strip()
    if len(s) < 4:
        return None
    m = re.match(r"^(.+?)\s*[-–—]\s*(.+)$", s, flags=re.DOTALL)
    if not m:
        return None
    name, text = m.group(1).strip(), m.group(2).strip()
    if name and len(text) >= 2:
        return name[:MAX_TITLE_LEN], text[:MAX_TEXT_LEN]
    return None


async def load_templates(user_id: int) -> list[TemplateItem]:
    data = await load_json_blob(user_id, "templates", default=[])
    return _items_from_json(data)


async def save_templates(user_id: int, items: list[TemplateItem]) -> None:
    data = [{"title": it.title, "text": it.text} for it in items]
    await save_json_blob(user_id, "templates", data)


def template_named_pairs(items: list[TemplateItem]) -> list[tuple[str, str]]:
    return [
        ((it.title or "").strip(), (it.text or "").strip())
        for it in items
        if (it.text or "").strip()
    ]


def _smart_texts_from_json(data: object) -> list[str]:
    out: list[str] = []
    for x in data if isinstance(data, list) else []:
        if isinstance(x, str):
            txt = x.strip()
        elif isinstance(x, dict):
            txt = str(x.get("text", "")).strip() or str(x.get("title", "")).strip()
        else:
            txt = str(x).strip()
        if txt:
            out.append(txt[:MAX_TEXT_LEN])
    return out


async def load_smart_texts(user_id: int) -> list[str]:
    data = await load_json_blob(user_id, "smart_templates", default=[])
    return _smart_texts_from_json(data)


async def save_smart_texts(user_id: int, texts: list[str]) -> None:
    clean = [t.strip()[:MAX_TEXT_LEN] for t in texts if (t or "").strip()]
    await save_json_blob(user_id, "smart_templates", clean)


async def pick_random_smart_preset(user_id: int, offer_title: str) -> str:
    texts = await load_smart_texts(user_id)
    if not texts:
        return ""
    base = texts[random.randrange(len(texts))]
    txt = expand_spintax(base)
    return apply_offer_to_text(txt, offer_title)

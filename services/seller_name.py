"""Имя продавца из JSON → local-part для email (имя@домен)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

MIN_NAME_ALNUM = 3

_LATIN_FOLD = str.maketrans(
    {
        "ö": "o",
        "Ö": "O",
        "ä": "a",
        "Ä": "A",
        "ü": "u",
        "Ü": "U",
        "ë": "e",
        "Ë": "E",
        "é": "e",
        "è": "e",
        "ê": "e",
        "á": "a",
        "à": "a",
        "â": "a",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "ñ": "n",
        "ç": "c",
        "ø": "o",
        "Ø": "O",
        "å": "a",
        "Å": "A",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
        "ẞ": "SS",
    }
)


def seller_name_from_item(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("item_person_name")
        or item.get("person_name")
        or item.get("name")
        or ""
    ).strip()


def normalize_seller_name(raw: str) -> str:
    if not raw:
        return ""
    s = " ".join(str(raw).strip().split())
    s = s.translate(_LATIN_FOLD)
    normalized = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return s


def count_name_alnum(name: str) -> int:
    return sum(1 for c in normalize_seller_name(name) if c.isalnum())


def seller_name_eligible(name: str, *, min_alnum: int = MIN_NAME_ALNUM) -> bool:
    return count_name_alnum(name) >= min_alnum


def make_email_local(name: str) -> str:
    """
    Matthias Güne Kreis → matthias.gune.kreis
    Leona Barukcic → leona.barukcic
    BakkAir → bakkair
    """
    norm = normalize_seller_name(name)
    if not norm:
        return ""
    parts = [p for p in re.split(r"[\s\-']+", norm.strip()) if p.strip()]
    tokens: list[str] = []
    for p in parts:
        clean = re.sub(r"[^A-Za-z0-9]", "", p)
        if clean:
            tokens.append(clean.lower())
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return ".".join(tokens)


def display_local(name: str) -> str:
    """Для сообщений: Matthias.Gune.Kreis"""
    local = make_email_local(name)
    if not local:
        return ""
    if "." not in local:
        return local[:1].upper() + local[1:] if local else ""
    return ".".join(p.capitalize() for p in local.split("."))

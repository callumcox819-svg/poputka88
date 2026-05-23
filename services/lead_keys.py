"""Нормализация ключей для поиска лида (email / имя продавца)."""

from __future__ import annotations

import json
import re

from services.seller_name import normalize_seller_name, seller_name_from_item


def email_norm_key(email: str) -> str:
    """
    Maria.Johansen@gmail.com и MariaJohansen@gmail.com → mariajohansen@gmail.com
    """
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, domain = e.rsplit("@", 1)
    local = local.split("+")[0].replace(".", "")
    return f"{local}@{domain}"


def seller_match_key(name: str) -> str:
    n = normalize_seller_name(name or "")
    return re.sub(r"[^a-z0-9]", "", n.lower())


def title_match_key(title: str) -> str:
    return " ".join((title or "").strip().casefold().split())


def offer_id_from_item(item: dict) -> int | None:
    raw = item.get("offer_id")
    if raw is None or raw == "":
        return None
    try:
        v = int(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def offer_id_from_lead_row(lead: dict) -> int | None:
    oid = lead.get("offer_id")
    if oid is not None and str(oid).strip().isdigit():
        v = int(oid)
        return v if v > 0 else None
    raw = (lead.get("raw_json") or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return offer_id_from_item(data)
    except json.JSONDecodeError:
        pass
    return None


def seller_names_from_lead(lead: dict) -> list[str]:
    names: list[str] = []
    for key in ("person_name",):
        v = (lead.get(key) or "").strip()
        if v:
            names.append(v)
    raw = (lead.get("raw_json") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                sn = seller_name_from_item(data)
                if sn:
                    names.append(sn)
        except json.JSONDecodeError:
            pass
    return names

"""Подстановка OFFER в текст."""

from __future__ import annotations


def apply_offer_to_text(text: str, offer_title: str) -> str:
    txt = text or ""
    title = (offer_title or "").strip()
    if not title:
        return txt
    for needle in ('{{OFFER}}', '"OFFER"', "'OFFER'", "«OFFER»", "OFFER"):
        txt = txt.replace(needle, title)
    return txt

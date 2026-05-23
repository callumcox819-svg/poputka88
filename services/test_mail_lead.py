"""Лид для тест-письма: JSON-фикстура → validated_leads на email получателя ответа."""

from __future__ import annotations

import time
from typing import Any

from database import get_validated_lead_by_email, upsert_validated_lead
from services.fixture_fields import normalize_fixture_fields, subject_stripped_title
from services.lead_keys import email_norm_key, seller_match_key, title_match_key
from services.test_mail_fixtures import load_test_fixtures
from services.user_json_store import load_json_blob, save_json_blob

TEST_MAIL_LEADS_BLOB = "test_mail_leads"


async def _save_mapping(
    user_id: int, recipient_email: str, *, lead_id: int, fx: dict[str, Any]
) -> None:
    email = recipient_email.strip().lower()
    data = await load_json_blob(user_id, TEST_MAIL_LEADS_BLOB, default={})
    if not isinstance(data, dict):
        data = {}
    fields = normalize_fixture_fields(fx)
    data[email] = {
        "lead_id": int(lead_id),
        "fixture_id": fx.get("id"),
        "item_title": fields["item_title"],
        "item_price": fields["item_price"],
        "item_link": fields["item_link"],
        "item_photo": fields["item_photo"],
        "registered_at": int(time.time()),
    }
    await save_json_blob(user_id, TEST_MAIL_LEADS_BLOB, data)


async def register_test_mail_lead(
    user_id: int,
    recipient_email: str,
    fixture: dict[str, Any],
) -> int | None:
    """
    После тест-отправки: лид на email получателя (кто ответит) со всеми полями из JSON.
    """
    email = (recipient_email or "").strip().lower()
    if not email or not fixture:
        return None

    fields = normalize_fixture_fields(fixture)
    person = fields["person_name"] or email.split("@")[0]
    local, _, domain = email.partition("@")

    _created, lead_id, _em = await upsert_validated_lead(
        user_id,
        email=email,
        person_name=person,
        email_local=local,
        email_domain=domain,
        item_title=fields["item_title"],
        item_price=fields["item_price"],
        item_link=fields["item_link"],
        person_link="",
        location=fields["location"],
        item_photo=fields["item_photo"],
        raw_json=fields["raw_json"],
        email_norm=email_norm_key(email),
        seller_key=seller_match_key(person),
        title_key=title_match_key(fields["item_title"]),
    )
    if lead_id:
        await _save_mapping(user_id, email, lead_id=lead_id, fx=fixture)
    return lead_id


def find_fixture_by_subject(subject: str) -> dict[str, Any] | None:
    needle = subject_stripped_title(subject).lower()
    if not needle or len(needle) < 4:
        return None
    best: dict[str, Any] | None = None
    best_len = 0
    for fx in load_test_fixtures():
        title = (fx.get("item_title") or "").strip()
        if not title:
            continue
        tl = title.lower()
        if needle == tl or needle in tl or tl in needle:
            if len(title) > best_len:
                best = fx
                best_len = len(title)
    return best


async def get_test_mail_lead_by_email(user_id: int, email: str) -> dict | None:
    em = (email or "").strip().lower()
    if not em:
        return None
    return await get_validated_lead_by_email(user_id, em)


async def resolve_lead_for_test_reply(
    user_id: int,
    *,
    contact_email: str,
    subject: str = "",
) -> dict | None:
    """Лид для реального ответа на тест-письмо: email получателя или тема Re: <товар>."""
    lead = await get_test_mail_lead_by_email(user_id, contact_email)
    if lead:
        return lead
    fx = find_fixture_by_subject(subject)
    if not fx:
        return None
    fields = normalize_fixture_fields(fx)
    if not fields["item_title"]:
        return None
    lid = await register_test_mail_lead(user_id, contact_email, fx)
    if lid:
        return await get_validated_lead_by_email(user_id, contact_email)
    return None

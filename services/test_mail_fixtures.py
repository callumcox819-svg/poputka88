"""Тестовые товары для 🧪 Тест маил (5 штук из void-parser)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "data" / "test_mail_fixtures.json"
_cache: list[dict[str, Any]] | None = None


def load_test_fixtures() -> list[dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache
    if not _FIXTURES_PATH.is_file():
        _cache = []
        return _cache
    raw = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))
    items = raw.get("fixtures") if isinstance(raw, dict) else raw
    _cache = [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
    return _cache


def get_test_fixture(index: int) -> dict[str, Any] | None:
    fixtures = load_test_fixtures()
    if not fixtures:
        return None
    if 0 <= index < len(fixtures):
        return fixtures[index]
    return None


def pick_random_test_fixture() -> dict[str, Any] | None:
    fixtures = load_test_fixtures()
    if not fixtures:
        return None
    return random.choice(fixtures)


def fixture_label(fx: dict[str, Any], *, max_len: int = 36) -> str:
    title = (fx.get("item_title") or "").strip()
    if len(title) <= max_len:
        return title
    return title[: max_len - 1] + "…"

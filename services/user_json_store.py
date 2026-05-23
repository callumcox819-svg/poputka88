"""Пресеты и JSON-данные пользователя — в БД (user_blobs), per user_id."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from database import get_user_blob, set_user_blob
from services.db_backend import is_postgres

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "json_blobs"


async def load_json_blob(user_id: int, blob_key: str, *, default: Any = None) -> Any:
    if default is None:
        default = []
    data = await get_user_blob(user_id, blob_key)
    if data is not None:
        return data
    path = DATA_DIR / str(int(user_id)) / f"{blob_key}.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            await set_user_blob(user_id, blob_key, payload)
            return payload
        except (json.JSONDecodeError, OSError):
            pass
    return default


async def save_json_blob(user_id: int, blob_key: str, data: Any) -> None:
    await set_user_blob(user_id, blob_key, data)
    if not is_postgres():
        path = DATA_DIR / str(int(user_id)) / f"{blob_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

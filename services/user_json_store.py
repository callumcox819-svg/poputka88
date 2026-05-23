"""JSON-хранилище пользователя (файлы в data/json_blobs/)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "json_blobs"


def _path(user_id: int, blob_key: str) -> Path:
    return DATA_DIR / str(int(user_id)) / f"{blob_key}.json"


async def load_json_blob(user_id: int, blob_key: str, *, default: Any = None) -> Any:
    if default is None:
        default = []
    path = _path(user_id, blob_key)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


async def save_json_blob(user_id: int, blob_key: str, data: Any) -> None:
    path = _path(user_id, blob_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

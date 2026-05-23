"""Перевод входящих писем: DeepL (если ключ задан), иначе Google GTX."""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _deepl_key() -> str:
    try:
        import config as cfg

        hard = (getattr(cfg, "DEEPL_API_KEY", None) or "").strip()
        if hard:
            return hard
    except Exception:
        pass
    return os.getenv("DEEPL_API_KEY", "").strip()


def strip_html(text: str) -> str:
    t = _HTML_TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", t).strip()


async def _translate_deepl(text: str, api_key: str) -> Optional[str]:
    base = os.getenv("DEEPL_API_BASE", "https://api-free.deepl.com").rstrip("/")
    if api_key.endswith(":fx") or ":fx" in api_key:
        base = "https://api-free.deepl.com"
    url = f"{base}/v2/translate"
    data = {
        "auth_key": api_key.replace(":fx", ""),
        "text": text[:4500],
        "target_lang": "RU",
    }
    timeout = aiohttp.ClientTimeout(total=35)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data) as resp:
                if resp.status != 200:
                    raw = await resp.text()
                    logger.warning("DeepL HTTP %s: %s", resp.status, raw[:300])
                    return None
                payload = await resp.json(content_type=None)
                trs = (payload or {}).get("translations") or []
                if not trs:
                    return None
                out = (trs[0].get("text") or "").strip()
                return out or None
    except Exception:
        logger.exception("DeepL request failed")
        return None


async def _translate_gtx(text: str) -> Optional[str]:
    timeout = aiohttp.ClientTimeout(total=22)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": "auto",
                    "tl": "ru",
                    "dt": "t",
                    "q": text[:4200],
                },
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                if not isinstance(data, list) or not data or not isinstance(data[0], list):
                    return None
                parts = []
                for row in data[0]:
                    if isinstance(row, list) and row and isinstance(row[0], str):
                        parts.append(row[0])
                out = "".join(parts).strip()
                return out or None
    except Exception:
        return None
    return None


async def translate_to_ru(text: str, *, preserve_blocks: bool = False) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None

    async def _one(block: str) -> Optional[str]:
        key = _deepl_key()
        if key:
            out = await _translate_deepl(block, key)
            if out:
                return out
        return await _translate_gtx(block)

    if preserve_blocks:
        blocks = [
            b.strip()
            for b in re.split(r"\n(?:-{5,}|-{3,})\n|\n{2,}", raw)
            if b.strip()
        ]
        if len(blocks) > 1:
            parts: list[str] = []
            for block in blocks:
                part = await _one(block)
                if not part:
                    return None
                parts.append(part)
            return "\n\n".join(parts)

    return await _one(raw)

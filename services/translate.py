"""Перевод входящих писем: DeepSeek (если ключ задан), иначе Google GTX."""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _deepseek_key() -> str:
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def strip_html(text: str) -> str:
    t = _HTML_TAG_RE.sub(" ", text or "")
    return _WS_RE.sub(" ", t).strip()


async def _translate_deepseek(text: str, api_key: str) -> Optional[str]:
    base = (os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com").rstrip("/")
    url = f"{base}/chat/completions"
    payload = {
        "model": (os.getenv("DEEPSEEK_TRANSLATE_MODEL") or "deepseek-v4-flash").strip(),
        "thinking": {"type": "disabled"},
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Translate the user text into Russian. "
                    "Return ONLY the translated text, without quotes or explanations."
                ),
            },
            {"role": "user", "content": text[:4200]},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=45)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    raw = await resp.text()
                    logger.warning("DeepSeek HTTP %s: %s", resp.status, raw[:300])
                    return None
                payload = await resp.json(content_type=None)
                choices = (payload or {}).get("choices") or []
                if not choices:
                    return None
                msg = choices[0].get("message") or {}
                out = (msg.get("content") or "").strip()
                return out or None
    except Exception:
        logger.exception("DeepSeek request failed")
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
                    raw = await resp.text()
                    logger.warning("GTX HTTP %s: %s", resp.status, raw[:300])
                    return None
                data = await resp.json(content_type=None)
                if not isinstance(data, list) or not data or not isinstance(data[0], list):
                    logger.warning("GTX bad response shape: %s", type(data).__name__)
                    return None
                parts = []
                for row in data[0]:
                    if isinstance(row, list) and row and isinstance(row[0], str):
                        parts.append(row[0])
                out = "".join(parts).strip()
                return out or None
    except Exception:
        logger.exception("GTX request failed")
        return None
    return None


async def translate_to_ru(text: str, *, preserve_blocks: bool = False) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None

    async def _one(block: str) -> Optional[str]:
        key = _deepseek_key()
        if key:
            out = await _translate_deepseek(block, key)
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

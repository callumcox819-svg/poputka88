"""MIME Content-Transfer-Encoding: 7bit, quoted-printable, base64, or auto."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

_ASCII_RE = re.compile(r"^[\x00-\x7f]*$", re.DOTALL)
_LONG_LINE = 998


class TransferEncoding(str, Enum):
    BIT7 = "7bit"
    QUOTED_PRINTABLE = "quoted-printable"
    BASE64 = "base64"
    AUTO = "auto"


def is_pure_ascii(text: str) -> bool:
    return bool(_ASCII_RE.match(text))


def has_long_lines(text: str) -> bool:
    return any(len(line) > _LONG_LINE for line in text.splitlines())


def can_use_7bit(text: str) -> bool:
    """RFC 2045: 7bit only for US-ASCII without overlong lines."""
    return is_pure_ascii(text) and not has_long_lines(text)


def recommend_encoding(
    body: str,
    *,
    is_html: bool = False,
) -> Literal["7bit", "quoted-printable", "base64"]:
    """
    7bit — идеально для чистого ASCII (максимальная совместимость).
    quoted-printable — лучше для UTF-8 / HTML с латиницей (меньше overhead, чем base64).
    base64 — для тяжёлого Unicode, вложений, бинарного контента.
    """
    if can_use_7bit(body):
        return "7bit"
    if is_html and len(body.encode("utf-8")) > 8192:
        return "base64"
    return "quoted-printable"


def resolve_encoding(
    choice: TransferEncoding,
    body: str,
    *,
    is_html: bool = False,
) -> Literal["7bit", "quoted-printable", "base64"]:
    if choice is TransferEncoding.AUTO:
        return recommend_encoding(body, is_html=is_html)
    if choice is TransferEncoding.BIT7:
        if not can_use_7bit(body):
            raise ValueError(
                "Текст не подходит для 7bit (нужен чистый ASCII без длинных строк). "
                "Выберите auto, quoted-printable или base64."
            )
        return "7bit"
    return choice.value  # type: ignore[return-value]

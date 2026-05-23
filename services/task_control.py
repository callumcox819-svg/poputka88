"""Флаги остановки фоновых задач (рассылка, проверка)."""

from __future__ import annotations

_stop_campaigns: set[int] = set()
_stop_validation: set[int] = set()


def request_stop_campaign(campaign_id: int) -> None:
    _stop_campaigns.add(campaign_id)


def clear_stop_campaign(campaign_id: int) -> None:
    _stop_campaigns.discard(campaign_id)


def should_stop_campaign(campaign_id: int) -> bool:
    return campaign_id in _stop_campaigns


def request_stop_validation(user_id: int) -> None:
    _stop_validation.add(user_id)


def clear_stop_validation(user_id: int) -> None:
    _stop_validation.discard(user_id)


def should_stop_validation(user_id: int) -> bool:
    return user_id in _stop_validation

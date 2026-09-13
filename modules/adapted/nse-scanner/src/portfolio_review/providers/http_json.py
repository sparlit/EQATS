from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Shared HTTP/JSON helpers for REST-based LLM providers."""


import json
from typing import Any

import requests

from .base import ProviderError


def post_json(url: str, *, headers: dict[str, str], body: dict[str, Any], timeout: int) -> dict[str, Any]:
    try:
        response = requests.post(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        msg = f"LLM HTTP request failed: {exc}"
        raise ProviderError(msg) from exc

    try:
        return response.json()
    except ValueError as exc:
        msg = "LLM provider returned non-JSON HTTP content"
        raise ProviderError(msg) from exc


def decode_json_object(text: str) -> dict[str, Any]:
    """Decode a JSON object, tolerating fenced JSON but no prose."""
    cleaned = text.strip()
    if cleaned.startswith("```json") and cleaned.endswith("```"):
        cleaned = cleaned[7:-3].strip()
    elif cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        msg = f"LLM response is not valid JSON: {exc}"
        raise ProviderError(msg) from exc

    if not isinstance(payload, dict):
        msg = "LLM response must be a JSON object"
        raise ProviderError(msg)
    return payload

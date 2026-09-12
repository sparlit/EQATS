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


"""Fail-closed Telegram delivery for the isolated Hull Pine bot."""

import os
import time
from dataclasses import dataclass

import requests
from telegram_dashboard import dashboard_keyboard


@dataclass(frozen=True)
class DeliveryResult:
    sent: bool
    message_count: int
    reason: str


def _topic_id(kind: str) -> int | None:
    value = os.getenv(f"HULL_{kind}_TOPIC_ID", "").strip()
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _send(messages: list[str], *, enabled: bool, topic: str) -> DeliveryResult:
    if not enabled:
        return DeliveryResult(False, 0, "dry_run")
    token = os.getenv("HULL_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("HULL_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return DeliveryResult(False, 0, "hull_telegram_credentials_missing")
    clean = [message.strip() for message in messages if message and message.strip()]
    if not clean:
        return DeliveryResult(False, 0, "no_messages")
    thread_id = _topic_id(topic)
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    sent, errors = 0, []
    for index, message in enumerate(clean, start=1):
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        if index == len(clean) and topic != "SYSTEM":
            payload["reply_markup"] = dashboard_keyboard("hull")
        try:
            response = requests.post(endpoint, json=payload, timeout=20)
            response.raise_for_status()
            if not response.json().get("ok"):
                msg = "telegram_rejected"
                raise RuntimeError(msg)
            sent += 1
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            errors.append(f"message_{index}:{type(exc).__name__}")
        if index < len(clean):
            time.sleep(1)
    if sent == len(clean):
        return DeliveryResult(True, sent, "sent")
    reason = ("partial_delivery:" if sent else "delivery_failed:") + ",".join(errors)
    return DeliveryResult(sent > 0, sent, reason)


def send_signals(messages: list[str], *, enabled: bool) -> DeliveryResult:
    return _send(messages, enabled=enabled, topic="DAILY")


def send_portfolio(message: str, *, enabled: bool) -> DeliveryResult:
    return _send([message], enabled=enabled, topic="PORTFOLIO")


def send_period(message: str, *, period: str, enabled: bool) -> DeliveryResult:
    return _send([message], enabled=enabled, topic="REVIEW")

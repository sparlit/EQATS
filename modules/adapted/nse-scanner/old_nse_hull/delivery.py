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


"""Telegram transport for the independent Old NSE + Hull PAPER system."""

import html
import os
import re
from dataclasses import dataclass

import requests
from telegram_dashboard import dashboard_keyboard


@dataclass(frozen=True)
class DeliveryResult:
    sent: bool
    reason: str


def _topic_id(kind: str) -> int | None:
    names = {
        "radar": ("LADDER_DAILY_TOPIC_ID",),
        "trades": ("LADDER_PORTFOLIO_TOPIC_ID",),
        "validation": ("LADDER_VALIDATION_TOPIC_ID",),
        "weekly": ("LADDER_REVIEW_TOPIC_ID",),
        "monthly": ("LADDER_REVIEW_TOPIC_ID",),
        "system": ("LADDER_SYSTEM_TOPIC_ID",),
    }
    value = next((os.getenv(name, "").strip() for name in names[kind] if os.getenv(name, "").strip()), "")
    try:
        topic_id = int(value)
    except ValueError:
        return None
    return topic_id if topic_id > 0 else None


def send_message(message: str, kind: str, timeout: int = 20) -> DeliveryResult:
    """Deliver only through the Momentum Ladder bot; never cross-route."""
    token = os.getenv("LADDER_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("LADDER_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return DeliveryResult(False, "telegram_not_configured")
    topic_id = _topic_id(kind)
    if topic_id is None:
        return DeliveryResult(False, f"topic_not_configured:{kind}")
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    payload["message_thread_id"] = topic_id
    if kind != "system":
        payload["reply_markup"] = dashboard_keyboard("ladder")
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=timeout)
        if getattr(response, "status_code", 200) == 400:
            # A malformed entity should not suppress an otherwise readable
            # validation card. Retry once as plain text in the same topic.
            payload.pop("parse_mode", None)
            payload["text"] = html.unescape(re.sub(r"<[^>]+>", "", message))
            response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return DeliveryResult(False, f"telegram_http_{status or 'network'}:{type(exc).__name__}")
    return DeliveryResult(True, "sent")


def send_radar(message: str, timeout: int = 20) -> DeliveryResult:
    return send_message(message, "radar", timeout)


def send_trades(message: str, timeout: int = 20) -> DeliveryResult:
    return send_message(message, "trades", timeout)


def send_period(message: str, period: str, timeout: int = 20) -> DeliveryResult:
    return send_message(message, period, timeout)

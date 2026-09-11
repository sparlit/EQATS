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


"""Frozen PAPER defaults for the progressive penny-stock funnel."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PennyConfig:
    strategy_version: str = "penny-shadow-v2-acceleration"
    min_price: float = 1.0
    max_price: float = 49.99
    radar_history: int = 120
    confirming_history: int = 180
    ready_history: int = 260
    radar_turnover_lacs: float = 20.0
    confirming_turnover_lacs: float = 40.0
    confirming_recent_turnover_lacs: float = 60.0
    ready_turnover_lacs: float = 60.0
    ready_recent_turnover_lacs: float = 100.0
    high_liquidity_turnover_lacs: float = 100.0
    high_liquidity_recent_lacs: float = 200.0
    ready_delivery_5: float = 30.0
    ready_delivery_20: float = 25.0
    ready_market_cap_cr: float = 100.0
    max_ready_distance_atr: float = 1.0
    extended_distance_atr: float = 1.5
    max_stop_risk_pct: float = 12.0
    min_reward_risk: float = 2.5
    radar_score: float = 35.0
    confirming_score: float = 50.0
    ready_review_score: float = 65.0
    ready_score: float = 75.0
    max_cards_per_message: int = 7
    telegram_message_limit: int = 3400

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


"""Fresh setup detectors for NSE Scanner V2.

These functions are deterministic and side-effect free so production and
backtests use identical setup definitions.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import atr, hma


@dataclass(frozen=True)
class SetupSignal:
    name: str
    passed: bool
    score: float
    reasons: tuple[str, ...]
    metrics: dict[str, float]


def breakout_signal(frame: pd.DataFrame, lookback: int = 20, volume_multiple: float = 1.5) -> SetupSignal:
    data = frame.sort_values("trade_date").copy()
    if len(data) < lookback + 1:
        return SetupSignal("BREAKOUT", False, 0.0, ("insufficient_history",), {})
    prior_high = data["close"].shift(1).rolling(lookback).max().iloc[-1]
    volume_avg = data["volume"].shift(1).rolling(20).mean().iloc[-1]
    last = data.iloc[-1]
    price_break = bool(last["close"] > prior_high)
    volume_confirm = bool(pd.notna(volume_avg) and last["volume"] >= volume_avg * volume_multiple)
    score = 60.0 * price_break + 40.0 * volume_confirm
    reasons = (
        "close_above_prior_high" if price_break else "no_price_breakout",
        "volume_confirmed" if volume_confirm else "volume_not_confirmed",
    )
    return SetupSignal(
        "BREAKOUT",
        price_break and volume_confirm,
        score,
        reasons,
        {"prior_high": float(prior_high), "volume_multiple": float(last["volume"] / volume_avg) if volume_avg else 0.0},
    )


def pullback_signal(
    frame: pd.DataFrame, hma_length: int = 55, atr_length: int = 14, max_distance_atr: float = 0.75
) -> SetupSignal:
    data = frame.sort_values("trade_date").copy()
    if len(data) < max(hma_length, atr_length) + 5:
        return SetupSignal("PULLBACK", False, 0.0, ("insufficient_history",), {})
    baseline = hma(data["close"], hma_length)
    volatility = atr(data, atr_length)
    last = data.iloc[-1]
    distance = abs(last["close"] - baseline.iloc[-1]) / volatility.iloc[-1]
    trend_up = bool(baseline.iloc[-1] > baseline.iloc[-5])
    near_hma = bool(distance <= max_distance_atr)
    bullish_close = bool(last["close"] >= last["open"])
    score = 45.0 * trend_up + 35.0 * near_hma + 20.0 * bullish_close
    reasons = (
        "hma_rising" if trend_up else "hma_not_rising",
        "near_hma" if near_hma else "extended_from_hma",
        "bullish_close" if bullish_close else "weak_close",
    )
    return SetupSignal(
        "PULLBACK",
        trend_up and near_hma and bullish_close,
        score,
        reasons,
        {"distance_atr": float(distance), "hma": float(baseline.iloc[-1])},
    )


def compression_signal(frame: pd.DataFrame, window: int = 20, threshold: float = 0.75) -> SetupSignal:
    data = frame.sort_values("trade_date").copy()
    if len(data) < window * 2:
        return SetupSignal("COMPRESSION", False, 0.0, ("insufficient_history",), {})
    tr = atr(data, 14)
    recent = tr.iloc[-window:].mean()
    prior = tr.iloc[-window * 2 : -window].mean()
    ratio = float(recent / prior) if prior else np.nan
    compressed = bool(pd.notna(ratio) and ratio <= threshold)
    score = float(max(0.0, min(100.0, (1.0 - ratio) * 200.0))) if pd.notna(ratio) else 0.0
    return SetupSignal(
        "COMPRESSION",
        compressed,
        score,
        ("volatility_compressed" if compressed else "no_compression",),
        {"atr_compression_ratio": ratio},
    )

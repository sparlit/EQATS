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


"""Independent 1M/3M/6M/12M scores for the shadow engine."""

from typing import TYPE_CHECKING

import numpy as np

from .config import CONFIRMING_SCORE, MIN_AVG_VOLUME, MIN_HISTORY, MIN_PRICE, QUALIFIED_SCORE

if TYPE_CHECKING:
    import pandas as pd

HORIZONS = ("1M", "3M", "6M", "12M")


def _percentile(values: pd.Series) -> pd.Series:
    return values.rank(pct=True, method="average").fillna(0.0) * 100


def score(
    features: pd.DataFrame,
    benchmark_returns: dict[str, float] | None = None,
    regime: str = "AWAITING_DATA",
    blocked_symbols: set[str] | None = None,
) -> pd.DataFrame:
    """Score independent horizons and assign exactly one principal bucket."""
    if features.empty:
        return features.copy()
    data = features.copy()
    eligible = (
        (data["history_sessions"] >= MIN_HISTORY)
        & (data["close"] >= MIN_PRICE)
        & (data["volume_sma20"] >= MIN_AVG_VOLUME)
    )
    if blocked_symbols:
        eligible &= ~data["symbol"].isin(blocked_symbols)
    data["eligible"] = eligible
    trend = (
        (data["close"] > data["sma50"]) & (data["sma50"] > data["sma150"]) & (data["sma150"] > data["sma200"])
    ).astype(float) * 25
    volume = (data["volume"] >= 1.2 * data["volume_sma20"]).astype(float) * 10
    delivery = (data["delivery_pct"] >= data["delivery_median60"]).fillna(False).astype(float) * 5
    near_high = (data["close"] >= 0.85 * data["previous_252d_high"]).fillna(False).astype(float) * 10
    returns = {"1M": "return_1m", "3M": "return_3m", "6M": "return_6m", "12M": "return_12m"}
    for horizon, column in returns.items():
        benchmark_return = (benchmark_returns or {}).get(horizon)
        excess = data[column] - benchmark_return if benchmark_return is not None else data[column]
        data[f"excess_return_{horizon.lower()}"] = excess
        data[f"rs_{horizon.lower()}"] = _percentile(excess.where(eligible)).reindex(data.index, fill_value=0)
        momentum = data[f"rs_{horizon.lower()}"] * 0.25
        rsi_component = ((data["rsi14"] >= 50) & (data["rsi14"] <= 75)).astype(float) * 8
        trend_strength = ((data["adx14"] >= 20) & (data["bb_width_change"] > 0)).fillna(False).astype(float) * 2
        trigger = (
            (data["close"] > data["previous_20d_high"]) if horizon == "1M" else (data["close"] > data["ema20"])
        ).fillna(False).astype(float) * 15
        structural = (
            near_high
            if horizon in ("6M", "12M")
            else ((data["close"] >= data["ema20"]).fillna(False).astype(float) * 10)
        )
        data[f"score_{horizon.lower()}"] = (
            (trend + momentum + rsi_component + trend_strength + volume + delivery + trigger + structural)
            .clip(upper=100)
            .round(2)
        )
    score_columns = [f"score_{h.lower()}" for h in HORIZONS]
    data["primary_horizon"] = data[score_columns].idxmax(axis=1).str.replace("score_", "", regex=False).str.upper()
    data["primary_score"] = data[score_columns].max(axis=1)
    data["confirming_horizons"] = data.apply(
        lambda row: [
            h for h in HORIZONS if row[f"score_{h.lower()}"] >= CONFIRMING_SCORE and h != row["primary_horizon"]
        ],
        axis=1,
    )
    data["confluence_score"] = data[score_columns].ge(CONFIRMING_SCORE).sum(axis=1) / len(HORIZONS) * 100
    data["qualified"] = data["eligible"] & (data["primary_score"] >= QUALIFIED_SCORE)
    data["market_regime"] = regime
    data["principal_bucket"] = np.where(
        data["qualified"],
        "NEWLY_QUALIFIED",
        np.where(data["eligible"] & (data["primary_score"] >= 55), "RADAR", "EXIT"),
    )
    return data

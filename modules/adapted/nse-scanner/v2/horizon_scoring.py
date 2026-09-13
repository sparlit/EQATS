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


"""Deterministic 1M/3M/6M/12M technical qualification scoring.

History length controls which horizons can be evaluated; it never assigns a
single horizon.  Every eligible stock receives independent horizon scores.
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .indicators import fixed_hybrid_hull_signals, hma
from .participation import evaluate_participation


@dataclass(frozen=True)
class HorizonScore:
    horizon: str
    score: float
    state: str
    component_scores: dict[str, float]
    hard_blocks: tuple[str, ...]
    reasons_for: tuple[str, ...]
    reasons_against: tuple[str, ...]
    metrics: dict[str, float | bool]

    def to_dict(self) -> dict:
        return asdict(self)


_MIN_HISTORY = {"1M": 80, "3M": 140, "6M": 220, "12M": 300}


def _bounded(value: float) -> float:
    return float(max(0.0, min(100.0, value)))


def _state(score: float, hard_blocks: list[str]) -> str:
    if hard_blocks:
        return "REJECTED"
    if score >= 80:
        return "QUALIFIED"
    if score >= 70:
        return "WATCH"
    if score >= 60:
        return "DEVELOPING"
    return "REJECTED"


def _rs_return(close: pd.Series, benchmark_close: pd.Series | None, lookback: int) -> float:
    if len(close) <= lookback:
        return 0.0
    stock_return = float(close.iloc[-1] / close.iloc[-lookback - 1] - 1.0)
    if benchmark_close is None or len(benchmark_close.dropna()) <= lookback:
        return stock_return
    benchmark = pd.to_numeric(benchmark_close, errors="coerce").dropna()
    benchmark_return = float(benchmark.iloc[-1] / benchmark.iloc[-lookback - 1] - 1.0)
    return stock_return - benchmark_return


def _rs_score(relative_return: float) -> float:
    # -10% or worse = 0; +25% or better = 100.
    return _bounded((relative_return + 0.10) / 0.35 * 100.0)


def _weekly_metrics(data: pd.DataFrame) -> dict[str, float | bool]:
    weekly_close = data.set_index(pd.to_datetime(data["trade_date"]))["close"].resample("W-FRI").last().dropna()
    if len(weekly_close) < 52:
        return {"weekly_bullish": False, "weekly_rising": False, "weekly_count": float(len(weekly_close))}
    weekly21 = hma(weekly_close, 21)
    weekly51 = hma(weekly_close, 51)
    valid = pd.notna(weekly21.iloc[-1]) and pd.notna(weekly51.iloc[-1])
    bullish = bool(valid and weekly21.iloc[-1] > weekly51.iloc[-1])
    rising = bool(valid and weekly21.iloc[-1] >= weekly21.iloc[-2])
    return {
        "weekly_bullish": bullish,
        "weekly_rising": rising,
        "weekly_count": float(len(weekly_close)),
    }


def _trend_persistence(close: pd.Series, lookback: int) -> float:
    if len(close) < lookback:
        return 0.0
    window = close.iloc[-lookback:]
    baseline = window.rolling(max(10, lookback // 6), min_periods=max(10, lookback // 6)).mean()
    valid = baseline.notna()
    if not valid.any():
        return 0.0
    return float((window[valid] > baseline[valid]).mean())


def _drawdown_score(close: pd.Series, lookback: int) -> float:
    if len(close) < lookback:
        return 0.0
    window = close.iloc[-lookback:]
    peak = window.cummax().replace(0, np.nan)
    max_drawdown = float((window / peak - 1.0).min())
    return _bounded((max_drawdown + 0.35) / 0.35 * 100.0)


def score_horizons(
    frame: pd.DataFrame,
    regime: str,
    benchmark_close: pd.Series | None = None,
) -> dict[str, HorizonScore]:
    data = frame.sort_values("trade_date").copy()
    close = pd.to_numeric(data["close"], errors="coerce")
    hybrid = fixed_hybrid_hull_signals(data)
    weekly = _weekly_metrics(data)
    participation = evaluate_participation(data)
    regime_value = {"BULL": 100.0, "BULLISH": 100.0, "NEUTRAL": 55.0, "BEAR": 0.0, "BEARISH": 0.0}.get(
        regime.upper(), 0.0
    )

    rs20 = _rs_return(close, benchmark_close, 20)
    rs63 = _rs_return(close, benchmark_close, 63)
    rs126 = _rs_return(close, benchmark_close, 126)
    rs252 = _rs_return(close, benchmark_close, 252)
    persistence63 = _trend_persistence(close, 63)
    persistence126 = _trend_persistence(close, 126)
    persistence252 = _trend_persistence(close, 252)
    drawdown126 = _drawdown_score(close, 126)
    drawdown252 = _drawdown_score(close, 252)

    daily_trend = (
        100.0
        if hybrid["daily_bullish"]
        else (
            75.0
            if hybrid["daily_persistent"]
            else 45.0
            if hybrid["hull_slope_improving"] and not hybrid["chop"]
            else 15.0
        )
    )
    weekly_trend = (
        100.0 if weekly["weekly_bullish"] and weekly["weekly_rising"] else (55.0 if weekly["weekly_bullish"] else 0.0)
    )
    structure_score = 100.0 if hybrid["daily_persistent"] else (55.0 if hybrid["hull_slope_improving"] else 20.0)
    participation_score = float(participation.score)
    alignment_score = (daily_trend + weekly_trend) / 2.0

    definitions = {
        "1M": {
            "weights": {
                "daily_trend": 25,
                "entry_readiness": 20,
                "rs20": 15,
                "participation": 15,
                "structure_persistence": 10,
                "risk_quality": 10,
                "market": 5,
            },
            "values": {
                "daily_trend": daily_trend,
                "entry_readiness": 100.0
                if hybrid["daily_persistent"] and not hybrid["stretched"] and not hybrid["chop"]
                else 35.0,
                "rs20": _rs_score(rs20),
                "participation": participation_score,
                "structure_persistence": structure_score,
                "risk_quality": 100.0 if not hybrid["stretched"] and not hybrid["chop"] else 20.0,
                "market": regime_value,
            },
        },
        "3M": {
            "weights": {
                "daily_trend": 20,
                "weekly_trend": 20,
                "rs63": 20,
                "participation": 12,
                "trend_persistence": 10,
                "entry_quality": 10,
                "market": 8,
            },
            "values": {
                "daily_trend": daily_trend,
                "weekly_trend": weekly_trend,
                "rs63": _rs_score(rs63),
                "participation": participation_score,
                "trend_persistence": persistence63 * 100.0,
                "entry_quality": 100.0 if not hybrid["stretched"] and not hybrid["chop"] else 25.0,
                "market": regime_value,
            },
        },
        "6M": {
            "weights": {
                "weekly_trend": 25,
                "rs126": 25,
                "alignment": 15,
                "trend_persistence": 12,
                "participation": 10,
                "drawdown": 8,
                "market": 5,
            },
            "values": {
                "weekly_trend": weekly_trend,
                "rs126": _rs_score(rs126),
                "alignment": alignment_score,
                "trend_persistence": persistence126 * 100.0,
                "participation": participation_score,
                "drawdown": drawdown126,
                "market": regime_value,
            },
        },
        "12M": {
            "weights": {
                "weekly_trend": 25,
                "rs252": 25,
                "trend_persistence": 15,
                "rs126": 10,
                "drawdown": 10,
                "participation": 8,
                "market": 7,
            },
            "values": {
                "weekly_trend": weekly_trend,
                "rs252": _rs_score(rs252),
                "trend_persistence": persistence252 * 100.0,
                "rs126": _rs_score(rs126),
                "drawdown": drawdown252,
                "participation": participation_score,
                "market": regime_value,
            },
        },
    }

    results: dict[str, HorizonScore] = {}
    for horizon, definition in definitions.items():
        blocks: list[str] = []
        if len(data) < _MIN_HISTORY[horizon]:
            blocks.append("insufficient_history")
        if regime.upper() in {"BEAR", "BEARISH"} and horizon in {"1M", "3M"}:
            blocks.append("bear_market_new_entry_block")
        if horizon == "1M":
            if not hybrid["daily_persistent"]:
                blocks.append("daily_hull_structure_not_persistent")
            if hybrid["chop"]:
                blocks.append("hybrid_hull_chop")
            if hybrid["stretched"]:
                blocks.append("extended_above_hybrid_hull")
        elif horizon == "3M":
            if not hybrid["daily_persistent"]:
                blocks.append("daily_trend_not_bullish")
            if rs63 <= 0:
                blocks.append("rs63_not_positive")
        elif horizon == "6M":
            if not weekly["weekly_bullish"]:
                blocks.append("weekly_trend_not_bullish")
            if rs126 <= 0:
                blocks.append("rs126_not_positive")
        elif horizon == "12M":
            if not weekly["weekly_bullish"]:
                blocks.append("long_term_weekly_trend_not_bullish")
            if rs252 <= 0:
                blocks.append("rs252_not_positive")

        components = {
            name: round(_bounded(float(definition["values"][name])) * weight / 100.0, 2)
            for name, weight in definition["weights"].items()
        }
        score = round(sum(components.values()), 2)
        reasons_for = [name for name, points in components.items() if points >= definition["weights"][name] * 0.70]
        reasons_against = list(blocks)
        reasons_against.extend(
            name for name, points in components.items() if points < definition["weights"][name] * 0.40
        )
        metrics = {
            **hybrid,
            **weekly,
            "rs20": round(rs20, 4),
            "rs63": round(rs63, 4),
            "rs126": round(rs126, 4),
            "rs252": round(rs252, 4),
            "trend_persistence_63": round(persistence63, 4),
            "trend_persistence_126": round(persistence126, 4),
            "trend_persistence_252": round(persistence252, 4),
        }
        results[horizon] = HorizonScore(
            horizon=horizon,
            score=score,
            state=_state(score, blocks),
            component_scores=components,
            hard_blocks=tuple(dict.fromkeys(blocks)),
            reasons_for=tuple(dict.fromkeys(reasons_for)),
            reasons_against=tuple(dict.fromkeys(reasons_against)),
            metrics=metrics,
        )
    return results

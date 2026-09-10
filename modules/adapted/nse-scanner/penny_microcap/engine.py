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


"""Point-in-time progressive selection for low-priced NSE equities.

Detection is intentionally wide. Entry authorization is intentionally strict.
Scores never override a hard tradeability or executability gate.
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from v2.indicators import atr
from v2.tradeability import evaluate_tradeability
from v2.tradeability import summarize as summarize_tradeability

from .config import PennyConfig

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class Candidate:
    symbol: str
    state: str
    score: float
    close: float
    entry_low: float | None
    entry_high: float | None
    stop: float | None
    target1: float | None
    target2: float | None
    reason_codes: tuple[str, ...]
    metrics: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _num(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _metadata(master: pd.DataFrame | None) -> dict[str, dict]:
    if master is None or master.empty:
        return {}
    return {str(row["symbol"]): row.to_dict() for _, row in master.iterrows()}


def _circuit_features(data: pd.DataFrame) -> tuple[int, bool]:
    """Conservative EOD proxy; never claims order-book certainty."""
    ret = data["close"].pct_change() * 100.0
    spread = (data["high"] - data["low"]) / data["close"].replace(0, np.nan) * 100.0
    near_high = (data["high"] - data["close"]).abs() / data["close"].replace(0, np.nan) <= 0.0025
    proxy = (ret >= 4.75) & near_high & (spread <= 1.0)
    count = 0
    for value in reversed(proxy.fillna(False).tolist()):
        if not value:
            break
        count += 1
    return count, bool(proxy.iloc[-1])


def evaluate_symbol(
    symbol: str,
    frame: pd.DataFrame,
    *,
    metadata: Mapping[str, object] | None = None,
    restricted_reason: str | None = None,
    expected_as_of: pd.Timestamp | None = None,
    config: PennyConfig = PennyConfig(),
) -> tuple[Candidate | None, dict]:
    data = frame.sort_values("trade_date").copy()
    meta = metadata or {}
    audit = {"symbol": symbol, "eligible": False, "stage": "DATA_QUALITY", "reason_code": "UNKNOWN"}
    if data["trade_date"].duplicated().any():
        audit.update(reason_code="DUPLICATE_DATES")
        return None, audit
    if (
        expected_as_of is not None
        and pd.Timestamp(data["trade_date"].max()).normalize() != pd.Timestamp(expected_as_of).normalize()
    ):
        audit.update(
            reason_code="STALE_LATEST_ROW",
            actual=str(pd.Timestamp(data["trade_date"].max()).date()),
            required=str(pd.Timestamp(expected_as_of).date()),
        )
        return None, audit
    if len(data) < config.radar_history:
        audit.update(reason_code="INSUFFICIENT_RADAR_HISTORY", actual=len(data), required=config.radar_history)
        return None, audit
    for col in ("open", "high", "low", "close", "volume"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    if data[["open", "high", "low", "close", "volume"]].tail(config.radar_history).isna().any().any():
        audit.update(reason_code="INVALID_OHLCV")
        return None, audit
    series = str(meta.get("series", "EQ") or "EQ").upper()
    if series != "EQ" or (meta.get("active") is not None and not bool(meta.get("active"))):
        audit.update(stage="TRADEABILITY", reason_code="NON_EQ_OR_INACTIVE", actual=series, required="ACTIVE_EQ")
        return None, audit
    if restricted_reason:
        audit.update(stage="REGULATORY", reason_code="RESTRICTED_SECURITY", actual=restricted_reason)
        return None, audit
    close = float(data["close"].iloc[-1])
    if not config.min_price <= close <= config.max_price:
        audit.update(
            stage="UNIVERSE",
            reason_code="PRICE_OUTSIDE_PENNY_BAND",
            actual=close,
            required=f"{config.min_price}-{config.max_price}",
        )
        return None, audit

    turnover = pd.to_numeric(data.get("turnover_lacs", pd.Series(np.nan, index=data.index)), errors="coerce")
    if turnover.isna().all():
        turnover = data["close"] * data["volume"] / 100_000.0
        turnover_source = "CALCULATED_CLOSE_X_VOLUME"
    else:
        turnover_source = "NSE_TURNOVER_LACS"
    median_turnover20 = _num(turnover.tail(20).median())
    if median_turnover20 < config.radar_turnover_lacs:
        audit.update(
            stage="LIQUIDITY",
            reason_code="LOW_RADAR_TURNOVER",
            actual=median_turnover20,
            required=config.radar_turnover_lacs,
        )
        return None, audit

    ema20 = data["close"].ewm(span=20, adjust=False).mean()
    ema50 = data["close"].ewm(span=50, adjust=False).mean()
    atr14s = atr(data, 14)
    atr14 = _num(atr14s.iloc[-1])
    prior_high = _num(data["high"].shift(1).rolling(20).max().iloc[-1], close)
    base_low = _num(data["low"].shift(1).rolling(20).min().iloc[-1], close)
    volume_med20 = _num(data["volume"].shift(1).tail(20).median())
    turnover_med_prior20 = _num(turnover.shift(1).tail(20).median())
    turnover_5 = _num(turnover.tail(5).mean())
    volume_ratio = _num(data["volume"].iloc[-1] / volume_med20) if volume_med20 else 0.0
    turnover_ratio = _num(turnover.tail(5).mean() / turnover_med_prior20) if turnover_med_prior20 else 0.0
    ret5 = _num((close / data["close"].iloc[-6] - 1) * 100)
    ret20 = _num((close / data["close"].iloc[-21] - 1) * 100)
    ret60 = _num((close / data["close"].iloc[-61] - 1) * 100) if len(data) >= 61 else 0.0
    ema20_rising = bool(ema20.iloc[-1] > ema20.iloc[-4])
    above_ema20 = bool(close > ema20.iloc[-1])
    trend_aligned = bool(above_ema20 and ema20.iloc[-1] > ema50.iloc[-1])
    breakout = bool(close > prior_high)
    near_breakout = bool(close >= prior_high * 0.97)
    range20_pct = _num((prior_high - base_low) / max(base_low, 0.01) * 100)
    compressed = range20_pct <= 18.0
    delivery = pd.to_numeric(data.get("delivery_pct", pd.Series(np.nan, index=data.index)), errors="coerce")
    delivery5, delivery20 = _num(delivery.tail(5).mean(), -1.0), _num(delivery.tail(20).mean(), -1.0)
    delivery_improving = delivery5 >= 0 and delivery20 >= 0 and delivery5 >= delivery20
    circuit_count, circuit_proxy = _circuit_features(data)

    early_flags = {
        "POSITIVE_MOMENTUM": ret5 > 0 or ret20 > 0,
        "TURNOVER_EXPANSION": turnover_ratio >= 1.5,
        "VOLUME_EXPANSION": volume_ratio >= 1.5,
        "DELIVERY_IMPROVING": delivery_improving,
        "ABOVE_EMA20": above_ema20,
        "EMA20_RISING": ema20_rising,
        "RANGE_BREAKOUT": breakout,
        "NEAR_BREAKOUT": near_breakout,
        "BASE_COMPRESSION": compressed,
    }
    interest_count = sum(early_flags.values())
    if not early_flags["POSITIVE_MOMENTUM"] or interest_count < 2:
        audit.update(stage="EARLY_DETECTION", reason_code="NO_EARLY_INTEREST", actual=interest_count, required=2)
        return None, audit

    score = 0.0
    # Early momentum 20
    score += 10 if ret5 > 0 else 0
    score += 10 if ret20 > 0 else 0
    # Turnover expansion 20
    score += 20 if turnover_ratio >= 2 else 15 if turnover_ratio >= 1.5 else 8 if turnover_ratio >= 1.1 else 0
    # Trend 15
    score += 8 if above_ema20 else 0
    score += 7 if ema20_rising else 0
    # Base/breakout 15
    score += 10 if breakout else 6 if near_breakout else 0
    score += 5 if compressed else 0
    # Relative momentum proxy 10; benchmark excess can replace this when index history is complete.
    score += 10 if ret20 > 8 and ret60 > 0 else 5 if ret20 > 0 else 0
    # Delivery 10
    score += 10 if delivery_improving and delivery5 >= 30 else 6 if delivery_improving else 0
    # Executability 10
    score += 0 if circuit_proxy else 10

    trigger = max(prior_high, close if breakout else prior_high)
    distance_atr = (close - prior_high) / atr14 if atr14 > 0 else 0.0
    structural_stop = min(_num(data["low"].tail(10).min(), close), close - 1.5 * atr14) if atr14 else base_low
    risk_pct = max(0.0, (trigger - structural_stop) / max(trigger, 0.01) * 100)
    risk = trigger - structural_stop
    target1 = trigger + 1.5 * risk if risk > 0 else None
    target2 = trigger + config.min_reward_risk * risk if risk > 0 else None
    risk_valid = 0 < risk_pct <= config.max_stop_risk_pct
    if risk_valid:
        score += 5
    score = min(100.0, round(score, 2))

    market_cap = meta.get("market_cap_cr")
    cap_verified = market_cap is not None and pd.notna(market_cap)
    ready_gates = {
        "READY_HISTORY": len(data) >= config.ready_history,
        "READY_TURNOVER": median_turnover20 >= config.ready_turnover_lacs
        and turnover_5 >= config.ready_recent_turnover_lacs,
        "READY_DELIVERY": delivery5 >= config.ready_delivery_5 and delivery20 >= config.ready_delivery_20,
        "READY_MARKET_CAP": cap_verified and float(market_cap) >= config.ready_market_cap_cr,
        "READY_TREND": trend_aligned and ema20_rising,
        "READY_BREAKOUT": breakout,
        "READY_DISTANCE": distance_atr <= config.max_ready_distance_atr,
        "READY_RISK": risk_valid,
        "READY_EXECUTABLE": not circuit_proxy and circuit_count == 0,
    }
    confirming_gates = {
        "CONFIRMING_HISTORY": len(data) >= config.confirming_history,
        "CONFIRMING_TURNOVER": median_turnover20 >= config.confirming_turnover_lacs
        and turnover_5 >= config.confirming_recent_turnover_lacs,
        "CONFIRMING_TREND": above_ema20 and ema20_rising,
        "CONFIRMING_PARTICIPATION": turnover_ratio >= 1.1 or delivery_improving,
        "CONFIRMING_DISTANCE": distance_atr <= config.extended_distance_atr,
    }

    if circuit_proxy:
        state = "CIRCUIT_LOCKED"
    elif distance_atr > config.extended_distance_atr:
        state = "EXTENDED"
    elif score >= config.ready_score and all(ready_gates.values()):
        state = "READY"
    elif score >= config.confirming_score and all(confirming_gates.values()):
        state = "CONFIRMING"
    elif score >= config.radar_score:
        state = "EARLY_RADAR"
    else:
        audit.update(stage="SCORING", reason_code="BELOW_RADAR_SCORE", actual=score, required=config.radar_score)
        return None, audit

    reasons = tuple(name for name, ok in early_flags.items() if ok)[:4]
    metrics = {
        "history_sessions": len(data),
        "return_5d_pct": round(ret5, 2),
        "return_20d_pct": round(ret20, 2),
        "median_turnover_20_lacs": round(median_turnover20, 2),
        "recent_turnover_5_lacs": round(turnover_5, 2),
        "turnover_ratio": round(turnover_ratio, 2),
        "volume_ratio": round(volume_ratio, 2),
        "delivery_5": round(delivery5, 2),
        "delivery_20": round(delivery20, 2),
        "distance_atr": round(distance_atr, 2),
        "risk_pct": round(risk_pct, 2),
        "market_cap_cr": round(float(market_cap), 2) if cap_verified else None,
        "market_cap_verified": cap_verified,
        "circuit_proxy": circuit_proxy,
        "liquidity_tier": "HIGH"
        if median_turnover20 >= config.high_liquidity_turnover_lacs and turnover_5 >= config.high_liquidity_recent_lacs
        else "STANDARD",
        "max_position_value_lacs": round(turnover_5 * 0.0025, 3),
        "consecutive_circuit_proxy": circuit_count,
        "executability": "UNAVAILABLE" if circuit_proxy else "EOD_GATES_PASSED",
        "turnover_source": turnover_source,
        "ready_gates": ready_gates,
        "confirming_gates": confirming_gates,
    }
    entry_low = round(trigger, 2) if state in {"CONFIRMING", "READY"} else None
    entry_high = round(trigger + min(0.5 * atr14, trigger * 0.03), 2) if entry_low is not None else None
    candidate = Candidate(
        symbol,
        state,
        score,
        round(close, 2),
        entry_low,
        entry_high,
        round(structural_stop, 2) if risk_valid else None,
        round(target1, 2) if target1 else None,
        round(target2, 2) if target2 else None,
        reasons,
        metrics,
    )
    audit.update(eligible=True, stage=state, reason_code=state, actual=score, required=config.radar_score)
    return candidate, audit


def scan_market(
    prices: pd.DataFrame,
    *,
    symbol_master: pd.DataFrame | None = None,
    restricted: Mapping[str, str] | None = None,
    lifecycle_registry: Mapping[str, Mapping[str, object]] | None = None,
    config: PennyConfig = PennyConfig(),
) -> dict:
    if prices.empty:
        return {"system": "PENNY_MICROCAP_SHADOW", "state": "NO_DATA", "candidates": [], "audit": []}
    prices = prices.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    as_of = prices["trade_date"].max()
    prices = prices[prices["trade_date"] <= as_of]
    metadata = _metadata(symbol_master)
    restricted = restricted or {}
    lifecycle_registry = lifecycle_registry or {}
    session_calendar = tuple(sorted(prices["trade_date"].dt.date.astype(str).unique()))
    tradeability_results = {}
    candidates, audits = [], []
    for symbol, frame in prices.groupby("symbol", sort=True):
        symbol = str(symbol)
        gate = evaluate_tradeability(
            symbol,
            frame,
            market_date=as_of.date().isoformat(),
            master_row=metadata.get(symbol),
            restricted_reason=restricted.get(symbol),
            lifecycle_event=lifecycle_registry.get(symbol),
            session_calendar=session_calendar,
            require_metadata=bool(metadata),
        )
        tradeability_results[symbol] = gate
        if not gate.eligible or gate.entry_blocked:
            audits.append({**gate.to_dict(), "eligible": False})
            continue
        candidate, audit = evaluate_symbol(
            symbol,
            frame,
            metadata=metadata.get(symbol, {}),
            restricted_reason=restricted.get(symbol),
            expected_as_of=as_of,
            config=config,
        )
        audits.append(audit)
        if candidate:
            candidates.append(candidate.to_dict())
    priority = {"READY": 0, "CONFIRMING": 1, "EARLY_RADAR": 2, "CIRCUIT_LOCKED": 3, "EXTENDED": 4}
    candidates.sort(key=lambda row: (priority.get(row["state"], 9), -row["score"], row["symbol"]))
    counts = {state: sum(row["state"] == state for row in candidates) for state in priority}
    return {
        "system": "PENNY_MICROCAP_SHADOW",
        "strategy_version": config.strategy_version,
        "mode": "PAPER",
        "as_of_date": as_of.date().isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(),
        "universe_symbols": prices["symbol"].nunique(),
        "selected": len(candidates),
        "counts": counts,
        "candidates": candidates,
        "audit": audits,
        "tradeability": summarize_tradeability(tradeability_results),
    }

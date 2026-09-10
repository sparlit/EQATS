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


"""Conservative, PAPER-only entry and risk levels for shadow candidates."""

import math

MAX_RISK_PCT = 8.0


def build_levels(row: dict) -> dict:
    """Return next-session levels or a rejection; never move a stop artificially.

    The trigger is based on a completed-session structure plus an ATR buffer.
    A structural stop wider than the declared maximum risk rejects the setup.
    """
    close, atr = float(row.get("close", 0)), float(row.get("atr", 0))
    pivot = float(row.get("previous_20d_high", 0))
    swing_low = float(row.get("previous_10d_low", 0))
    horizon = str(row.get("primary_horizon", ""))
    if not all(math.isfinite(value) and value > 0 for value in (close, atr, pivot, swing_low)):
        return {"eligible_for_paper": False, "rejection_code": "missing_trade_structure"}
    entry = pivot + 0.10 * atr if horizon == "1M" else max(close, float(row.get("ema20", close))) + 0.10 * atr
    structural_stop = swing_low - 0.25 * atr
    atr_stop = entry - 2.0 * atr
    # The structural level governs validity.  ATR is retained as a diagnostic,
    # not used to pull an invalid structure closer merely to fit the risk cap.
    stop = structural_stop
    risk = entry - stop
    risk_pct = risk / entry * 100
    if stop <= 0 or risk <= 0:
        return {"eligible_for_paper": False, "rejection_code": "invalid_stop"}
    if risk_pct > MAX_RISK_PCT:
        return {"eligible_for_paper": False, "rejection_code": "risk_exceeds_maximum", "risk_pct": round(risk_pct, 2)}
    return {
        "eligible_for_paper": True,
        "entry_trigger": round(entry, 2),
        "stop": round(stop, 2),
        "risk_per_share": round(risk, 2),
        "risk_pct": round(risk_pct, 2),
        "atr_stop_reference": round(atr_stop, 2),
        "target_1": round(entry + 1.5 * risk, 2),
        "target_2": round(entry + 2.5 * risk, 2),
        "trail_rule": "After T1, trail below prior 10-session low",
        "rejection_code": None,
    }

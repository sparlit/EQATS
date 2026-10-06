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


"""Transparent fixed-risk research sizing with hard safety caps."""
import math

import db
from strategy_config import SIZING as CFG

MAX_ALLOC = CFG["MAX_ALLOC"]
RISK_PER_TRADE = CFG["RISK_PER_TRADE"]
DEFAULT_CAPITAL = CFG["DEFAULT_CAPITAL"]

KNOWN_REGIMES = {"STRONG_BULL", "BULL", "NEUTRAL", "WEAK", "CAPITULATION"}


def get_capital(conn=None):
    own = conn is None
    if own:
        conn = db.get_conn()
    cap = DEFAULT_CAPITAL
    try:
        r = conn.execute("SELECT value FROM settings WHERE key='capital'").fetchone()
        if r and r[0]:
            cap = float(r[0])
    except Exception:
        pass
    if own:
        conn.close()
    return cap if _positive_finite(cap) else DEFAULT_CAPITAL


def set_capital(value):
    v = float(value)
    if not _positive_finite(v):
        raise ValueError("capital must be finite and > 0")
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('capital',?)", (str(v),))
    conn.commit()
    conn.close()
    return v


def _positive_finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def _regime_scale():
    try:
        from regime import MarketRegime

        reg = MarketRegime.compute()
        level = str(reg.level).upper()
        mult = float(reg.size_mult)
        if level not in KNOWN_REGIMES:
            return 0.0, level or "UNKNOWN", "unknown market regime"
        if not math.isfinite(mult) or not 0.0 <= mult <= 1.0:
            return 0.0, level, "invalid market regime multiplier"
        return mult, level, None
    except Exception as exc:
        return 0.0, "UNKNOWN", f"market regime unavailable: {exc}"


def _quality_mult(shape_score):
    """Return (multiplier, error) for an optional 0..100 shape score."""
    if shape_score is None:
        return 1.0, None
    try:
        s = float(shape_score)
    except (TypeError, ValueError):
        return 0.0, "shape score must be a finite number from 0 to 100"
    if not math.isfinite(s) or not 0.0 <= s <= 100.0:
        return 0.0, "shape score must be a finite number from 0 to 100"
    for threshold, mult in CFG["QUALITY_TIERS"]:
        if s >= threshold:
            try:
                mult = float(mult)
            except (TypeError, ValueError):
                return 0.0, "invalid quality multiplier"
            if not math.isfinite(mult) or not 0.0 <= mult <= 2.0:
                return 0.0, "invalid quality multiplier"
            return mult, None
    return 0.0, "no quality tier matched the shape score"


def suggest(symbol, trigger=None, stop=None, capital=None, shape_score=None, conn=None):
    """Suggest a fixed-risk research size; never infer a win probability."""
    own = conn is None
    if own:
        conn = db.get_conn()
    try:
        cap = float(capital) if capital is not None else get_capital(conn)
    finally:
        if own:
            conn.close()
    if not _positive_finite(cap):
        raise ValueError("capital must be finite and > 0")

    regime_mult, regime_level, regime_error = _regime_scale()
    quality_mult, quality_error = _quality_mult(shape_score)
    reason = regime_error or quality_error

    # Multipliers may reduce the research budget but can never lift either cap.
    combined_mult = regime_mult * quality_mult if reason is None else 0.0
    alloc = min(MAX_ALLOC, MAX_ALLOC * combined_mult)
    risk_fraction = min(RISK_PER_TRADE, RISK_PER_TRADE * combined_mult)

    out = {
        "symbol": symbol,
        "capital": cap,
        "p_win": None,
        "basis": "fixed-risk research sizing; no calibrated trade win probability",
        "payoff_b": None,
        "regime_level": regime_level,
        "regime_mult": regime_mult,
        "shape_score": shape_score,
        "quality_mult": quality_mult,
        "max_alloc_pct": MAX_ALLOC * 100,
        "risk_per_trade_pct": RISK_PER_TRADE * 100,
        "planned_risk_budget_pct": round(risk_fraction * 100, 2),
        "kelly_pct": None,
        "half_kelly_pct": None,
        "alloc_pct": round(alloc * 100, 2),
        "max_position_value": round(cap * alloc, 2),
        "actionable": False,
        "reason": reason,
        "risk_note": "Planned stop risk only; gaps, slippage, fees and taxes can increase actual loss.",
    }

    if trigger is None or stop is None:
        out["reason"] = reason or "valid trigger and stop are required for a quantity"
        return out
    if not _positive_finite(trigger) or not _positive_finite(stop):
        out["reason"] = reason or "trigger and stop must be finite and > 0"
        return out
    trigger = float(trigger)
    stop = float(stop)
    if trigger <= stop:
        out["reason"] = reason or "trigger must be above stop"
        return out
    if reason is not None or alloc <= 0.0 or risk_fraction <= 0.0:
        return out

    risk_pct = (trigger - stop) / trigger
    risk_value = cap * risk_fraction
    value_by_risk = risk_value / risk_pct
    position_limit = cap * alloc
    value_limit = min(position_limit, value_by_risk)
    shares = int(value_limit // trigger)
    invested_value = shares * trigger
    planned_stop_risk = shares * (trigger - stop)
    actual_alloc_pct = invested_value / cap * 100.0
    actual_risk_pct = planned_stop_risk / cap * 100.0
    actionable = shares > 0
    out.update(
        {
            "trigger": trigger,
            "stop": stop,
            "risk_pct": round(risk_pct * 100, 2),
            "value_by_risk_cap": round(value_by_risk, 2),
            "suggested_value": round(invested_value, 2),
            "shares": shares,
            "actual_alloc_pct": round(actual_alloc_pct, 2),
            "risk_amount": round(planned_stop_risk, 2),
            "actual_planned_risk_pct": round(actual_risk_pct, 2),
            "binding_cap": (
                "planned stop-risk cap"
                if value_by_risk < position_limit
                else f"allocation cap {round(alloc * 100, 2)}%"
            ),
            "actionable": actionable,
            "reason": None
            if actionable
            else "capital is insufficient for one share within the caps",
        }
    )
    return out


if __name__ == "__main__":
    import sys

    sym = sys.argv[1].upper() if len(sys.argv) > 1 else "DIXON"
    shape = float(sys.argv[2]) if len(sys.argv) > 2 else None
    print(suggest(sym, shape_score=shape))

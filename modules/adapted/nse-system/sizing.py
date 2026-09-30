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


"""
Position sizing — half-Kelly with caps. Reads from strategy_config.SIZING.
v5 (2026-09-12): migrated to central config.
"""
import db
from strategy_config import SIZING as CFG

B_PAYOFF = CFG["B_PAYOFF"]
MAX_ALLOC = CFG["MAX_ALLOC"]
RISK_PER_TRADE = CFG["RISK_PER_TRADE"]
DEFAULT_CAPITAL = CFG["DEFAULT_CAPITAL"]
FALLBACK_WINRATE = CFG["FALLBACK_WINRATE"]


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
    return cap


def set_capital(value):
    v = float(value)
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('capital',?)", (str(v),))
    conn.commit()
    conn.close()
    return v


def _system_winrate(conn):
    try:
        row = conn.execute("SELECT SUM(outcome='WIN'), SUM(outcome='LOSS') FROM swing_signals").fetchone()
        w = row[0] or 0
        l = row[1] or 0
        if w + l >= 10:
            return round(w / (w + l), 3)
    except Exception:
        pass
    return None


def _regime_scale():
    try:
        from regime import MarketRegime

        reg = MarketRegime.compute()
        return reg.size_mult, reg.level
    except Exception:
        return 1.0, "UNKNOWN"


def _quality_mult(shape_score):
    """shape_score -> multiplier. First match wins (descending)."""
    if shape_score is None:
        return 1.0
    try:
        s = float(shape_score)
    except (TypeError, ValueError):
        return 1.0
    for threshold, mult in CFG["QUALITY_TIERS"]:
        if s >= threshold:
            return mult
    return 1.0


def kelly_fraction(w, b=B_PAYOFF):
    if w is None:
        return None
    return max(0.0, (b * w - (1.0 - w)) / b)


def suggest(symbol, trigger=None, stop=None, capital=None, shape_score=None, conn=None):
    """
    Suggest a position size for `symbol`. All parameters from
    strategy_config.SIZING unless overridden.
    """
    own = conn is None
    if own:
        conn = db.get_conn()
    cap = float(capital) if capital else get_capital(conn)
    w = None
    src = None
    try:
        import pwin_cache

        pw = pwin_cache.get_map(conn)
        if symbol in pw:
            w, src = pw[symbol], "meta-model (daily cache)"
    except Exception:
        pass
    if w is None:
        wr = _system_winrate(conn)
        if wr is not None:
            w, src = wr, "graded system win-rate"
    if w is None:
        w, src = FALLBACK_WINRATE, "conservative fallback (no data yet)"
    if own:
        conn.close()

    regime_mult, regime_level = _regime_scale()
    quality_mult = _quality_mult(shape_score)

    out = {
        "symbol": symbol,
        "capital": cap,
        "p_win": w,
        "basis": src,
        "payoff_b": B_PAYOFF,
        "regime_level": regime_level,
        "regime_mult": regime_mult,
        "shape_score": shape_score,
        "quality_mult": quality_mult,
        "max_alloc_pct": MAX_ALLOC * 100,
        "risk_per_trade_pct": RISK_PER_TRADE * 100,
    }
    f = kelly_fraction(w)
    half = f / 2.0
    raw_alloc = min(half, MAX_ALLOC)
    alloc = raw_alloc * regime_mult * quality_mult
    out.update(
        {
            "kelly_pct": round(f * 100, 1),
            "half_kelly_pct": round(half * 100, 1),
            "alloc_pct": round(alloc * 100, 2),
            "max_position_value": round(cap * alloc, 0),
        }
    )
    if trigger and stop and trigger > stop:
        risk_pct = (trigger - stop) / trigger
        risk_value = cap * RISK_PER_TRADE * regime_mult * quality_mult
        value_by_risk = risk_value / risk_pct if risk_pct > 0 else 0.0
        value = min(cap * alloc, value_by_risk)
        shares = int(value // trigger) if trigger > 0 else 0
        out.update(
            {
                "trigger": trigger,
                "stop": stop,
                "risk_pct": round(risk_pct * 100, 2),
                "value_by_risk_cap": round(value_by_risk, 0),
                "suggested_value": round(value, 0),
                "shares": shares,
                "risk_amount": round(shares * trigger * risk_pct, 0),
                "binding_cap": (
                    "risk-based" if value_by_risk < cap * alloc else f"kelly/alloc {round(alloc * 100, 2)}%"
                ),
            }
        )
    return out


if __name__ == "__main__":
    import sys

    sym = sys.argv[1].upper() if len(sys.argv) > 1 else "DIXON"
    shape = float(sys.argv[2]) if len(sys.argv) > 2 else None
    print(suggest(sym, shape_score=shape))

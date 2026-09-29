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
All-Weather Swing Mode — high-conviction setups during DEFENSIVE regime.
Reads from strategy_config.ALL_WEATHER.
v3 (2026-09-12): migrated to central config.
"""
import datetime as dt
import sys

import db
import numpy as np
import pandas as pd
from strategy_config import ALL_WEATHER as CFG

BELOW_52W_MIN = CFG["BELOW_52W_MIN"]
NEAR_LOW_MAX = CFG["NEAR_LOW_MAX"]
MAX_RISK_PCT = CFG["MAX_RISK_PCT"]
TARGET_R = CFG["TARGET_R"]
TICK = CFG["TICK"]


def _quality_maps(conn):
    fund = {}
    try:
        rows = conn.execute(
            "SELECT symbol, fundamental_score FROM scan_results "
            "WHERE scan_date=(SELECT MAX(scan_date) FROM scan_results) "
            "AND fundamental_score IS NOT NULL"
        ).fetchall()
        for s, sc in rows:
            fund[s] = sc
    except Exception:
        pass
    roce = {}
    try:
        for s, r in conn.execute("SELECT symbol, roce FROM fundamentals WHERE roce IS NOT NULL").fetchall():
            roce[s] = r
    except Exception:
        pass
    return fund, roce


def _tier(fund_score, roce):
    if (fund_score is not None and fund_score >= 70) or (roce is not None and roce >= 15):
        return "HIGH"
    if (fund_score is not None and fund_score >= 50) or (roce is not None and roce >= 10):
        return "MED"
    return "UNK"


def _candle_pattern(o, h, l, c, po, pc):
    body = abs(c - o)
    rng = h - l
    if rng <= 0:
        return None
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    if body / rng < 0.35 and lower_wick / rng > 0.55 and upper_wick / rng < 0.15:
        return "HAMMER"
    if pc < po and c > o and c >= po and o <= pc:
        return "BULLISH_ENGULFING"
    return None


def candidates(conn, limit=600):
    fund, roce = _quality_maps(conn)
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM universe_broad "
            "WHERE mcap_cr BETWEEN 1000 AND 8000 "
            "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
            "ORDER BY mcap_cr DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]
    out = []
    for sym in syms:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 260",
            (sym,),
        ).fetchall()
        if len(rows) < 200:
            continue
        rows = list(reversed(rows))
        highs = [r[2] for r in rows if r[2] is not None]
        lows = [r[3] for r in rows if r[3] is not None]
        if len(highs) < 200 or len(lows) < 200:
            continue
        hi52 = max(highs[-252:])
        lo52 = min(lows[-252:])
        last = rows[-1][4]
        if hi52 <= 0 or last is None:
            continue
        below = (hi52 - last) / hi52
        if below < BELOW_52W_MIN:
            continue
        near_low = (last - lo52) / max(lo52, 1e-9)
        if near_low > NEAR_LOW_MAX:
            continue
        df = pd.DataFrame(rows, columns=["date", "Open", "High", "Low", "Close", "Volume"]).set_index("date")
        tier = _tier(fund.get(sym), roce.get(sym))
        out.append((sym, df, fund.get(sym), roce.get(sym), tier))
    return out


def detect(sym, df, fund_score=None, roce=None, tier="UNK"):
    if len(df) < 60:
        return None
    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values

    pat = _candle_pattern(o[-1], h[-1], l[-1], c[-1], o[-2], c[-2])
    if not pat:
        return None

    entry = float(h[-1]) + TICK
    stop = min(float(l[-1]), float(l[-2])) * 0.99
    if stop >= entry:
        return None
    risk_pct = (entry - stop) / entry
    if risk_pct > MAX_RISK_PCT:
        return None
    target = entry + TARGET_R * (entry - stop)

    hi52 = float(np.max(h[-252:])) if len(h) >= 252 else float(np.max(h))
    pb_depth = (hi52 - c[-1]) / hi52 if hi52 > 0 else 0
    return {
        "symbol": sym,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "pattern": pat,
        "risk_pct": round(risk_pct, 4),
        "pb_depth": round(pb_depth, 3),
        "impulse": 0.0,
        "fund_score": fund_score,
        "roce": roce,
        "tier": tier,
    }


def scan(conn=None):
    own = conn is None
    if own:
        conn = db.get_conn()
    setups = []
    for sym, df, fs, roce, tier in candidates(conn):
        s = detect(sym, df, fs, roce, tier)
        if s:
            setups.append(s)
    if own:
        conn.close()
    return setups


if __name__ == "__main__":
    rows = scan()
    print(f"[AW] {len(rows)} all-weather setups")
    for s in rows:
        print(
            f"  {s['symbol']:<12} {s['pattern']:<18} "
            f"tier {s['tier']:<4} "
            f"entry {s['entry']} stop {s['stop']} "
            f"target {s['target']} risk {s['risk_pct'] * 100:.1f}% "
            f"fund {s['fund_score']} roce {s['roce']}"
        )

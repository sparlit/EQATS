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
Rule-Based Pattern Scanner v6.

v6 (2026-09-13): every detector now records a per-condition checklist
(checks list) which is stored in the pattern_tags.params JSON. Enables
transparency UI — user sees exactly which conditions passed or failed.

BULL_FLAG KILLED 2026-09-17 by evidence (rescue experiment).
Detects early chart-pattern formations, tags them in DB, backfills
historical tags, respects the empirical hit-rate gate AND the
fundamental veto gate.
"""
import contextlib
import datetime as dt
import json
import math
import sys

import db
import numpy as np
import pandas as pd
import universe_helper as U

MIN_CONFIDENCE_TO_STORE = 58.0
DEFAULT_SYMBOL_LIMIT = 500


PATTERN_PARAMS = {
    "HIGH_TIGHT_FLAG": {
        "lookback": 100,
        "pole_min_gain": 0.60,
        "pole_max_days": 60,
        "consolidation_min_days": 5,
        "consolidation_max_days": 35,
        "max_pullback": 0.28,
        "max_below52": 0.25,
        "max_vcr": 0.90,
    },
    "ASCENDING_TRIANGLE": {
        "lookback": 140,
        "pivot_k": 4,
        "resistance_tolerance": 0.035,
        "min_pivot_highs": 2,
        "min_rising_lows": 2,
        "max_distance_to_breakout": 0.12,
        "max_vcr": 1.10,
    },
    "DOUBLE_BOTTOM": {
        "lookback": 170,
        "pivot_k": 4,
        "bottom_tolerance": 0.055,
        "min_separation_days": 15,
        "max_separation_days": 95,
        "max_distance_to_neckline": 0.16,
    },
    "INVERSE_HEAD_SHOULDERS": {
        "lookback": 190,
        "pivot_k": 4,
        "shoulder_tolerance": 0.09,
        "head_min_depth": 0.045,
        "max_distance_to_neckline": 0.18,
    },
    "HEAD_SHOULDERS_TOP_WARNING": {
        "lookback": 190,
        "pivot_k": 4,
        "shoulder_tolerance": 0.09,
        "head_min_height": 0.045,
        "max_distance_to_neckline": 0.15,
    },
}


def _ensure(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pattern_tags(
            date TEXT,
            symbol TEXT,
            pattern TEXT,
            direction TEXT,
            status TEXT,
            confidence REAL,
            breakout_level REAL,
            stop_level REAL,
            target_level REAL,
            notes TEXT,
            params TEXT,
            created_at TEXT,
            PRIMARY KEY(date, symbol, pattern)
        )
    """)


def _symbols(conn, limit=DEFAULT_SYMBOL_LIMIT):
    symbols = set()
    with contextlib.suppress(Exception):
        symbols.update(U.band_universe(conn, limit))
    try:
        rows = conn.execute("SELECT symbol FROM stocks WHERE active=1").fetchall()
        for r in rows:
            symbols.add(r[0])
    except Exception:
        pass
    return sorted(symbols)


def _load_df(conn, symbol, n=420):
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume "
        "FROM prices_daily WHERE symbol=? "
        "ORDER BY date DESC LIMIT ?",
        (symbol, n),
    ).fetchall()
    if not rows or len(rows) < 120:
        return None
    rows = list(reversed(rows))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df[df["volume"].fillna(0) >= 0]
    if len(df) < 120:
        return None
    return df.reset_index(drop=True)


def _secret_sauce(df):
    close = df["close"]
    high = df["high"]
    volume = df["volume"]
    high52 = high.rolling(252, min_periods=60).max()
    vol5 = volume.rolling(5, min_periods=3).mean()
    vol50 = volume.rolling(50, min_periods=20).mean()
    ret = close.pct_change()
    vcr = vol5 / vol50.replace(0, np.nan)
    ret_std20 = ret.rolling(20, min_periods=10).std()
    below52 = 1.0 - (close / high52.replace(0, np.nan))
    return {
        "vcr": _safe_float(vcr.iloc[-1]),
        "ret_std20": _safe_float(ret_std20.iloc[-1]),
        "below52": _safe_float(below52.iloc[-1]),
        "high52": _safe_float(high52.iloc[-1]),
    }


def _safe_float(x):
    try:
        if x is None:
            return None
        if pd.isna(x):
            return None
        if math.isinf(float(x)):
            return None
        return float(x)
    except Exception:
        return None


def _round(x, n=2):
    x = _safe_float(x)
    if x is None:
        return None
    return round(x, n)


def _status(close, breakout):
    if breakout is None or breakout <= 0:
        return "FORMING"
    if close >= breakout:
        return "BREAKOUT"
    if close >= breakout * 0.97:
        return "READY"
    return "FORMING"


def _target_2r(breakout, stop):
    if breakout is None or stop is None:
        return None
    if breakout <= stop:
        return None
    return breakout + 2.0 * (breakout - stop)


def _pivots(df, kind="high", k=4):
    vals = df["high"].values if kind == "high" else df["low"].values
    piv = []
    if len(vals) < 2 * k + 5:
        return piv
    for i in range(k, len(vals) - k):
        window = vals[i - k : i + k + 1]
        center = vals[i]
        if kind == "high":
            if center == np.nanmax(window) and center > vals[i - 1] and center >= vals[i + 1]:
                piv.append({"i": i, "date": df["date"].iloc[i], "price": float(center)})
        else:
            if center == np.nanmin(window) and center < vals[i - 1] and center <= vals[i + 1]:
                piv.append({"i": i, "date": df["date"].iloc[i], "price": float(center)})
    return piv


def _mk(symbol, pattern, direction, status, confidence, breakout, stop, notes, params, checks=None):
    target = _target_2r(breakout, stop)
    return {
        "symbol": symbol,
        "pattern": pattern,
        "direction": direction,
        "status": status,
        "confidence": round(float(confidence), 1),
        "breakout_level": _round(breakout),
        "stop_level": _round(stop),
        "target_level": _round(target),
        "notes": notes,
        "params": params,
        "checks": checks or [],
    }


# ============================================================
# Detectors — each builds a `checks` list
# ============================================================
def detect_high_tight_flag(symbol, df, sauce):
    p = PATTERN_PARAMS["HIGH_TIGHT_FLAG"]
    checks = []
    look = df.tail(p["lookback"]).copy()
    if len(look) < 70:
        return None
    close = float(look["close"].iloc[-1])
    high_vals = look["high"].values
    low_vals = look["low"].values
    recent_high_local = int(np.argmax(high_vals))
    recent_high = float(high_vals[recent_high_local])
    bars_since_high = len(look) - 1 - recent_high_local

    ok = p["consolidation_min_days"] <= bars_since_high <= p["consolidation_max_days"]
    checks.append(
        {
            "name": "bars_since_high in range",
            "ok": ok,
            "got": f"{bars_since_high}d ({p['consolidation_min_days']}-{p['consolidation_max_days']})",
        }
    )
    if not ok:
        return None

    pole_start = max(0, recent_high_local - p["pole_max_days"])
    pole_end = max(pole_start + 5, recent_high_local - 3)
    if pole_end <= pole_start:
        return None
    pole_low = float(np.nanmin(low_vals[pole_start:pole_end]))
    if pole_low <= 0:
        return None
    pole_gain = recent_high / pole_low - 1.0
    pullback = recent_high / close - 1.0
    cons_low = float(np.nanmin(low_vals[recent_high_local:]))

    ok = pole_gain >= p["pole_min_gain"]
    checks.append(
        {"name": f"pole_gain >= {p['pole_min_gain']:.0%}", "ok": ok, "got": f"{pole_gain:.1%}"}
    )
    if not ok:
        return None

    ok = pullback <= p["max_pullback"]
    checks.append(
        {"name": f"pullback <= {p['max_pullback']:.0%}", "ok": ok, "got": f"{pullback:.1%}"}
    )
    if not ok:
        return None

    below52 = sauce.get("below52")
    vcr = sauce.get("vcr")
    ret_std20 = sauce.get("ret_std20")

    ok = (below52 is None) or (below52 <= p["max_below52"])
    checks.append(
        {
            "name": f"below_52w_high <= {p['max_below52']:.0%}",
            "ok": ok,
            "got": (f"{below52:.1%}" if below52 is not None else "—"),
        }
    )
    if not ok:
        return None

    ok = (vcr is None) or (vcr <= p["max_vcr"])
    checks.append(
        {
            "name": f"vcr <= {p['max_vcr']}",
            "ok": ok,
            "got": (f"{vcr:.2f}" if vcr is not None else "—"),
        }
    )
    if not ok:
        return None

    score = 55.0
    if pole_gain >= 1.0:
        score += 15
    elif pole_gain >= 0.75:
        score += 10
    else:
        score += 5
    if pullback <= 0.15:
        score += 12
    elif pullback <= 0.22:
        score += 8
    else:
        score += 3
    if vcr is not None and vcr <= p["max_vcr"]:
        score += 10
    if below52 is not None and below52 <= p["max_below52"]:
        score += 8
    if ret_std20 is not None and ret_std20 < 0.035:
        score += 5

    breakout = recent_high
    stop = cons_low
    status = _status(close, breakout)
    notes = (
        f"HTF pole {pole_gain:.0%}, pullback {pullback:.0%}, "
        f"bars since high {bars_since_high}" + (f", vcr {vcr:.2f}" if vcr is not None else "")
    )
    return _mk(
        symbol,
        "HIGH_TIGHT_FLAG",
        "BULLISH",
        status,
        min(score, 95),
        breakout,
        stop,
        notes,
        p,
        checks,
    )


def detect_ascending_triangle(symbol, df, sauce):
    p = PATTERN_PARAMS["ASCENDING_TRIANGLE"]
    checks = []
    look = df.tail(p["lookback"]).copy().reset_index(drop=True)
    if len(look) < 80:
        return None
    close = float(look["close"].iloc[-1])
    ph = _pivots(look, "high", p["pivot_k"])
    pl = _pivots(look, "low", p["pivot_k"])

    ok = len(ph) >= p["min_pivot_highs"]
    checks.append({"name": f"pivot_highs >= {p['min_pivot_highs']}", "ok": ok, "got": str(len(ph))})
    if not ok:
        return None

    ok = len(pl) >= p["min_rising_lows"]
    checks.append({"name": f"pivot_lows >= {p['min_rising_lows']}", "ok": ok, "got": str(len(pl))})
    if not ok:
        return None

    recent_highs = ph[-5:]
    max_high = max(x["price"] for x in recent_highs)
    near_res = [
        x
        for x in recent_highs
        if abs(x["price"] - max_high) / max_high <= p["resistance_tolerance"]
    ]
    ok = len(near_res) >= p["min_pivot_highs"]
    checks.append(
        {
            "name": "flat_resistance_pivots",
            "ok": ok,
            "got": f"{len(near_res)} within {p['resistance_tolerance']:.1%}",
        }
    )
    if not ok:
        return None

    recent_lows = pl[-4:]
    if len(recent_lows) < 2:
        return None
    low_prices = [x["price"] for x in recent_lows]
    rising_count = 0
    for a, b in zip(low_prices, low_prices[1:], strict=False):
        if b > a * 0.985:
            rising_count += 1
    ok = rising_count >= p["min_rising_lows"] - 1
    checks.append(
        {"name": "rising_lows", "ok": ok, "got": f"{rising_count} of {len(low_prices) - 1}"}
    )
    if not ok:
        return None

    resistance = float(np.median([x["price"] for x in near_res]))
    distance = resistance / close - 1.0
    ok = -0.02 <= distance <= p["max_distance_to_breakout"]
    checks.append(
        {
            "name": f"distance_to_resistance <= {p['max_distance_to_breakout']:.1%}",
            "ok": ok,
            "got": f"{distance:.1%}",
        }
    )
    if not ok:
        return None

    vcr = sauce.get("vcr")
    ret_std20 = sauce.get("ret_std20")
    ok = (vcr is None) or (vcr <= p["max_vcr"])
    checks.append(
        {
            "name": f"vcr <= {p['max_vcr']}",
            "ok": ok,
            "got": (f"{vcr:.2f}" if vcr is not None else "—"),
        }
    )
    if not ok:
        return None

    score = 55.0
    score += min(15, len(near_res) * 5)
    score += min(12, rising_count * 6)
    if distance <= 0.05:
        score += 10
    elif distance <= 0.09:
        score += 5
    if vcr is not None and vcr <= p["max_vcr"]:
        score += 8
    if ret_std20 is not None and ret_std20 < 0.035:
        score += 5
    stop = min(x["price"] for x in recent_lows[-2:])
    status = _status(close, resistance)
    notes = f"Flat resistance near {resistance:.2f}, rising lows, distance {distance:.1%}" + (
        f", vcr {vcr:.2f}" if vcr is not None else ""
    )
    return _mk(
        symbol,
        "ASCENDING_TRIANGLE",
        "BULLISH",
        status,
        min(score, 92),
        resistance,
        stop,
        notes,
        p,
        checks,
    )


def detect_double_bottom(symbol, df, sauce):
    p = PATTERN_PARAMS["DOUBLE_BOTTOM"]
    checks = []
    look = df.tail(p["lookback"]).copy().reset_index(drop=True)
    if len(look) < 90:
        return None
    close = float(look["close"].iloc[-1])
    lows = _pivots(look, "low", p["pivot_k"])
    ok = len(lows) >= 2
    checks.append({"name": "pivot_lows >= 2", "ok": ok, "got": str(len(lows))})
    if not ok:
        return None

    best = None
    for i in range(len(lows) - 1):
        for j in range(i + 1, len(lows)):
            a = lows[i]
            b = lows[j]
            sep = b["i"] - a["i"]
            if sep < p["min_separation_days"] or sep > p["max_separation_days"]:
                continue
            avg = (a["price"] + b["price"]) / 2.0
            if avg <= 0:
                continue
            diff = abs(a["price"] - b["price"]) / avg
            if diff > p["bottom_tolerance"]:
                continue
            middle = look.iloc[a["i"] : b["i"] + 1]
            neckline = float(middle["high"].max())
            if neckline <= avg:
                continue
            best = (a, b, neckline, diff, sep)

    ok = best is not None
    checks.append(
        {
            "name": "two_bottoms_found",
            "ok": ok,
            "got": (f"yes (sep={best[4]}, diff={best[3]:.1%})" if ok else "no"),
        }
    )
    if not ok:
        return None

    a, b, neckline, diff, sep = best
    distance = neckline / close - 1.0
    ok = -0.03 <= distance <= p["max_distance_to_neckline"]
    checks.append(
        {
            "name": f"distance_to_neckline <= {p['max_distance_to_neckline']:.1%}",
            "ok": ok,
            "got": f"{distance:.1%}",
        }
    )
    if not ok:
        return None

    score = 58.0
    if diff <= 0.025:
        score += 12
    elif diff <= 0.04:
        score += 7
    if sep >= 25:
        score += 7
    if distance <= 0.06:
        score += 10
    elif distance <= 0.12:
        score += 5
    if b["price"] >= a["price"] * 0.98:
        score += 5
    vcr = sauce.get("vcr")
    if vcr is not None and vcr <= 1.15:
        score += 5
    stop = min(a["price"], b["price"]) * 0.985
    status = _status(close, neckline)
    notes = (
        f"Two bottoms within {diff:.1%}, separated {sep} bars, "
        f"neckline {neckline:.2f}, distance {distance:.1%}"
    )
    return _mk(
        symbol, "DOUBLE_BOTTOM", "BULLISH", status, min(score, 90), neckline, stop, notes, p, checks
    )


def detect_inverse_head_shoulders(symbol, df, sauce):
    p = PATTERN_PARAMS["INVERSE_HEAD_SHOULDERS"]
    checks = []
    look = df.tail(p["lookback"]).copy().reset_index(drop=True)
    if len(look) < 110:
        return None
    close = float(look["close"].iloc[-1])
    lows = _pivots(look, "low", p["pivot_k"])
    ok = len(lows) >= 3
    checks.append({"name": "pivot_lows >= 3", "ok": ok, "got": str(len(lows))})
    if not ok:
        return None

    candidate = None
    for i in range(len(lows) - 2):
        ls = lows[i]
        head = lows[i + 1]
        rs = lows[i + 2]
        if not (ls["i"] < head["i"] < rs["i"]):
            continue
        if head["price"] >= ls["price"] or head["price"] >= rs["price"]:
            continue
        shoulder_avg = (ls["price"] + rs["price"]) / 2.0
        if shoulder_avg <= 0:
            continue
        shoulder_diff = abs(ls["price"] - rs["price"]) / shoulder_avg
        if shoulder_diff > p["shoulder_tolerance"]:
            continue
        head_depth = shoulder_avg / head["price"] - 1.0
        if head_depth < p["head_min_depth"]:
            continue
        left_neck = look.iloc[ls["i"] : head["i"] + 1]["high"].max()
        right_neck = look.iloc[head["i"] : rs["i"] + 1]["high"].max()
        neckline = float((left_neck + right_neck) / 2.0)
        candidate = (ls, head, rs, neckline, shoulder_diff, head_depth)

    ok = candidate is not None
    checks.append(
        {"name": "inverse_hs_found", "ok": ok, "got": ("yes" if ok else "no shoulders/head shape")}
    )
    if not ok:
        return None

    ls, head, rs, neckline, shoulder_diff, head_depth = candidate
    distance = neckline / close - 1.0
    ok = -0.03 <= distance <= p["max_distance_to_neckline"]
    checks.append(
        {
            "name": f"distance_to_neckline <= {p['max_distance_to_neckline']:.1%}",
            "ok": ok,
            "got": f"{distance:.1%}",
        }
    )
    if not ok:
        return None

    score = 58.0
    if shoulder_diff <= 0.05:
        score += 10
    else:
        score += 5
    if head_depth >= 0.08:
        score += 10
    else:
        score += 5
    if distance <= 0.08:
        score += 10
    else:
        score += 4
    vcr = sauce.get("vcr")
    if vcr is not None and vcr <= 1.15:
        score += 5
    stop = min(ls["price"], head["price"], rs["price"]) * 0.985
    status = _status(close, neckline)
    notes = (
        f"Inverse H&S: shoulders diff {shoulder_diff:.1%}, "
        f"head depth {head_depth:.1%}, neckline {neckline:.2f}, "
        f"distance {distance:.1%}"
    )
    return _mk(
        symbol,
        "INVERSE_HEAD_SHOULDERS",
        "BULLISH",
        status,
        min(score, 91),
        neckline,
        stop,
        notes,
        p,
        checks,
    )


def detect_head_shoulders_top(symbol, df, sauce):
    p = PATTERN_PARAMS["HEAD_SHOULDERS_TOP_WARNING"]
    checks = []
    look = df.tail(p["lookback"]).copy().reset_index(drop=True)
    if len(look) < 110:
        return None
    close = float(look["close"].iloc[-1])
    highs = _pivots(look, "high", p["pivot_k"])
    ok = len(highs) >= 3
    checks.append({"name": "pivot_highs >= 3", "ok": ok, "got": str(len(highs))})
    if not ok:
        return None

    candidate = None
    for i in range(len(highs) - 2):
        ls = highs[i]
        head = highs[i + 1]
        rs = highs[i + 2]
        if not (ls["i"] < head["i"] < rs["i"]):
            continue
        if head["price"] <= ls["price"] or head["price"] <= rs["price"]:
            continue
        shoulder_avg = (ls["price"] + rs["price"]) / 2.0
        if shoulder_avg <= 0:
            continue
        shoulder_diff = abs(ls["price"] - rs["price"]) / shoulder_avg
        if shoulder_diff > p["shoulder_tolerance"]:
            continue
        head_height = head["price"] / shoulder_avg - 1.0
        if head_height < p["head_min_height"]:
            continue
        left_neck = look.iloc[ls["i"] : head["i"] + 1]["low"].min()
        right_neck = look.iloc[head["i"] : rs["i"] + 1]["low"].min()
        neckline = float((left_neck + right_neck) / 2.0)
        candidate = (ls, head, rs, neckline, shoulder_diff, head_height)

    ok = candidate is not None
    checks.append({"name": "head_shoulders_top_found", "ok": ok, "got": ("yes" if ok else "no")})
    if not ok:
        return None

    ls, head, rs, neckline, shoulder_diff, head_height = candidate
    if neckline <= 0:
        return None
    distance = close / neckline - 1.0
    if distance < -0.05:
        status = "BREAKDOWN"
    elif distance <= p["max_distance_to_neckline"]:
        status = "WARNING"
    else:
        return None

    score = 55.0
    if shoulder_diff <= 0.05:
        score += 10
    else:
        score += 5
    if head_height >= 0.08:
        score += 10
    else:
        score += 5
    if distance <= 0.08:
        score += 8
    ret_std20 = sauce.get("ret_std20")
    if ret_std20 is not None and ret_std20 > 0.025:
        score += 4
    breakout = neckline
    stop = max(ls["price"], head["price"], rs["price"]) * 1.015
    notes = (
        f"Bearish H&S warning: shoulders diff {shoulder_diff:.1%}, "
        f"head height {head_height:.1%}, neckline {neckline:.2f}"
    )
    return _mk(
        symbol,
        "HEAD_SHOULDERS_TOP_WARNING",
        "BEARISH",
        status,
        min(score, 88),
        breakout,
        stop,
        notes,
        p,
        checks,
    )


def detect_symbol(symbol, conn=None, df=None):
    own = conn is None
    if df is None:
        if own:
            conn = db.get_conn()
        df = _load_df(conn, symbol)
        if own:
            conn.close()
    if df is None:
        return []
    sauce = _secret_sauce(df)
    out = []
    detectors = [
        detect_high_tight_flag,
        detect_ascending_triangle,
        detect_double_bottom,
        detect_inverse_head_shoulders,
        detect_head_shoulders_top,
    ]
    for fn in detectors:
        try:
            r = fn(symbol, df, sauce)
            if r and r["confidence"] >= MIN_CONFIDENCE_TO_STORE:
                r["secret_sauce"] = sauce
                out.append(r)
        except Exception as e:
            print(f"[PATTERN] {symbol} {fn.__name__} failed: {e}")
    out.sort(key=lambda x: (-x["confidence"], x["pattern"]))
    return out


def _save(conn, date, rows):
    _ensure(conn)
    now = dt.datetime.now().isoformat(timespec="seconds")
    for r in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO pattern_tags(
                date, symbol, pattern, direction, status, confidence,
                breakout_level, stop_level, target_level,
                notes, params, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                date,
                r["symbol"],
                r["pattern"],
                r["direction"],
                r["status"],
                r["confidence"],
                r["breakout_level"],
                r["stop_level"],
                r["target_level"],
                r["notes"],
                json.dumps(
                    {
                        "params": r.get("params", {}),
                        "secret_sauce": r.get("secret_sauce", {}),
                        "checks": r.get("checks", []),
                    },
                    default=str,
                ),
                now,
            ),
        )


def run(limit=DEFAULT_SYMBOL_LIMIT):
    conn = db.get_conn()
    _ensure(conn)
    try:
        import pattern_grader

        enabled = pattern_grader.enabled_patterns(conn)
    except Exception:
        enabled = None
    try:
        import fund_veto

        veto_on = True
    except Exception:
        veto_on = False

    today = dt.date.today().isoformat()
    symbols = _symbols(conn, limit=limit)
    total = len(symbols)
    saved = 0
    hit_symbols = 0
    filtered = 0
    veto_filtered = 0

    print(f"[PATTERN] scanning {total} symbols")
    for i, sym in enumerate(symbols, 1):
        rows = detect_symbol(sym, conn=conn)
        if enabled is not None and rows:
            before = len(rows)
            rows = [h for h in rows if h["pattern"] in enabled]
            filtered += before - len(rows)
        if veto_on and rows:
            kept = []
            for h in rows:
                if h["direction"] == "BULLISH":
                    try:
                        bad, why = fund_veto.vetoed(h["symbol"], conn=conn)
                    except Exception:
                        bad = False
                    if bad:
                        veto_filtered += 1
                        continue
                kept.append(h)
            rows = kept
        if rows:
            hit_symbols += 1
            saved += len(rows)
            _save(conn, today, rows)
            best = rows[0]
            print(
                f"[{i}/{total}] {sym}: {len(rows)} pattern(s), "
                f"best={best['pattern']} {best['status']} "
                f"conf={best['confidence']}"
            )
        if i % 50 == 0:
            conn.commit()
            print(f"[PATTERN] progress {i}/{total}, saved {saved}")
    conn.commit()
    conn.close()
    print(
        f"[PATTERN] complete: symbols={total}, "
        f"hit_symbols={hit_symbols}, tags_saved={saved}, "
        f"gate_filtered={filtered}, veto_filtered={veto_filtered}"
    )
    try:
        import pattern_grader

        pattern_grader.grade_all()
        pattern_grader.report()
    except Exception as e:
        print(f"[PATTERN] grading skipped: {e}")
    return {
        "date": today,
        "symbols": total,
        "hit_symbols": hit_symbols,
        "tags_saved": saved,
        "gate_filtered": filtered,
        "veto_filtered": veto_filtered,
    }


def backfill_tags(step=10, limit=300):
    conn = db.get_conn()
    _ensure(conn)
    symbols = _symbols(conn, limit=limit)
    conn.close()
    total = len(symbols)
    saved = 0
    print(f"[PATTERN-BF] backfilling {total} symbols (step={step})")
    for i, sym in enumerate(symbols, 1):
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume "
            "FROM prices_daily WHERE symbol=? ORDER BY date",
            (sym,),
        ).fetchall()
        conn.close()
        if len(rows) < 200:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "open", "high", "low", "close"])
        df = df.reset_index(drop=True)
        for j in range(180, len(df), step):
            slice_df = df.iloc[:j].reset_index(drop=True)
            d = str(slice_df["date"].iloc[-1])[:10]
            conn = db.get_conn()
            exists = conn.execute(
                "SELECT 1 FROM pattern_tags WHERE symbol=? AND date=? LIMIT 1", (sym, d)
            ).fetchone()
            conn.close()
            if exists:
                continue
            hits = detect_symbol(sym, df=slice_df)
            if hits:
                conn = db.get_conn()
                _save(conn, d, hits)
                conn.commit()
                conn.close()
                saved += len(hits)
        if i % 25 == 0:
            print(f"[PATTERN-BF] {i}/{total} symbols, saved {saved}")
    print(f"[PATTERN-BF] complete: saved {saved} historical tags")
    return saved


def latest(limit=100):
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        """
        SELECT date, symbol, pattern, direction, status, confidence,
               breakout_level, stop_level, target_level, notes, params
        FROM pattern_tags
        ORDER BY date DESC, confidence DESC
        LIMIT ?
    """,
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def for_symbol(symbol, limit=50):
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        """
        SELECT date, symbol, pattern, direction, status, confidence,
               breakout_level, stop_level, target_level, notes, params
        FROM pattern_tags
        WHERE symbol=?
        ORDER BY date DESC, confidence DESC
        LIMIT ?
    """,
        (symbol.upper(), limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def history_for_symbol(symbol, limit=500):
    """Used by ID49 chart markers. Returns compact signal+outcome rows."""
    conn = db.get_conn()
    _ensure(conn)
    try:
        rows = conn.execute(
            """
            SELECT pt.date, pt.pattern, pt.direction, pt.confidence,
                   pt.breakout_level, pt.stop_level, pt.target_level,
                   pg.outcome
            FROM pattern_tags pt
            LEFT JOIN pattern_grades pg
              ON pg.tag_date=pt.date
             AND pg.symbol=pt.symbol
             AND pg.pattern=pt.pattern
            WHERE pt.symbol=?
            ORDER BY pt.date ASC
            LIMIT ?
        """,
            (symbol.upper(), limit),
        ).fetchall()
    except Exception:
        rows = []
    conn.close()
    return [
        {
            "date": r[0],
            "pattern": r[1],
            "direction": r[2],
            "confidence": r[3],
            "breakout": r[4],
            "stop": r[5],
            "target": r[6],
            "outcome": r[7],
        }
        for r in rows
    ]


def _row_to_dict(r):
    params = {}
    checks = []
    try:
        loaded = json.loads(r[10]) if r[10] else {}
        if isinstance(loaded, dict):
            params = loaded
            checks = loaded.get("checks", []) or []
    except Exception:
        params = {}
    return {
        "date": r[0],
        "symbol": r[1],
        "pattern": r[2],
        "direction": r[3],
        "status": r[4],
        "confidence": r[5],
        "breakout_level": r[6],
        "stop_level": r[7],
        "target_level": r[8],
        "notes": r[9],
        "params": params,
        "checks": checks,
    }


def print_latest(limit=30):
    rows = latest(limit)
    if not rows:
        print("No pattern tags found. Run: python patterns.py run")
        return
    for r in rows:
        print(
            f"{r['date']} {r['symbol']:<14} "
            f"{r['pattern']:<28} {r['direction']:<7} "
            f"{r['status']:<9} conf={r['confidence']:<5} "
            f"breakout={r['breakout_level']} stop={r['stop_level']}"
        )
        print(f"    {r['notes']}")
        if r.get("checks"):
            for c in r["checks"]:
                mark = "✓" if c.get("ok") else "✗"
                print(f"      {mark} {c.get('name')}: {c.get('got')}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "latest"

    if cmd == "run":
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SYMBOL_LIMIT
        print(json.dumps(run(limit=lim), indent=2))
    elif cmd == "backfill":
        st = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        lm = int(sys.argv[3]) if len(sys.argv) > 3 else 300
        backfill_tags(step=st, limit=lm)
    elif cmd == "symbol":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "DIXON"
        print(json.dumps(detect_symbol(sym), indent=2, default=str))
    elif cmd == "saved":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "DIXON"
        print(json.dumps(for_symbol(sym), indent=2, default=str))
    elif cmd == "history":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "DIXON"
        print(json.dumps(history_for_symbol(sym), indent=2, default=str))
    else:
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print_latest(lim)

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
Gold (XAUUSD) Strategy — ICT + SMC Hybrid (High Win-Rate)
==========================================================
Based on Inner Circle Trader (ICT) + Smart Money Concepts (SMC)

TIMEFRAMES:
  Daily  → market bias (bullish / bearish)
  H4     → zone mapping (Order Block, FVG, Premium/Discount)
  H1     → structure reference
  M15    → entry trigger (CHOCH, OTE, Judas Swing)
  M5     → entry confirmation candle

CONFLUENCE SCORING  (5 factors × 30 pts = 150 pt scale):
  [1] HTF Daily bias is clear              → 30 pts
  [2] Price in Discount (buy) / Premium (sell) zone → 30 pts
  [3] Kill Zone is active  ← HARD BLOCK   → 30 pts
  [4] Judas Swing confirmed                → 30 pts
  [5] H4 Order Block or FVG at OTE level  → 30 pts
  Minimum 4/5 = 120 pts to fire signal

KILL ZONES (UTC → IST):
  London Open:    07:00–10:00 UTC  =  12:30–15:30 IST
  New York Open:  13:00–16:00 UTC  =  18:30–21:30 IST
  (Configurable via KILL_ZONES_IST dict below)

ASIAN SESSION (UTC → IST):
  00:00–07:00 UTC  =  05:30–12:30 IST
  Used to detect Judas Swing (fake move against bias at KZ open)

TRADE MANAGEMENT:
  SL  : 5 pips ($0.50) below OB low  /  above OB high
  TP1 : 1.5R  (close 50% — move SL to breakeven)
  TP2 : 3.0R  (close remaining 50%)
  Risk: 1% of balance per trade (configurable)
"""

from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════
# CONFIGURABLE PARAMETERS
# ══════════════════════════════════════════════════════════════════

ASSET = "GOLD"
MIN_SCORE = 120  # 4/5 confluence = 120 / 150

# ── Kill Zones in IST (hour*100 + minute) ────────────────────────
# Change these to adjust kill zone windows
KILL_ZONES_IST = {
    "London Open": (1230, 1530),  # 12:30–15:30 IST  (07:00–10:00 UTC)
    "New York Open": (1830, 2130),  # 18:30–21:30 IST  (13:00–16:00 UTC)
}

# ── Asian session in IST ─────────────────────────────────────────
# 00:00–07:00 UTC = 05:30–12:30 IST
ASIAN_IST_START_H, ASIAN_IST_START_M = 5, 30  # 05:30 IST
ASIAN_IST_END_H, ASIAN_IST_END_M = 12, 30  # 12:30 IST

# ── Risk & reward ────────────────────────────────────────────────
RISK_PCT_DEFAULT = 1.0  # % of balance per trade
TP1_R = 1.5  # first take-profit (1.5R)
TP2_R = 3.0  # second take-profit (3.0R)
SL_BUFFER = 0.50  # $0.50 = ~5 pips below/above OB

# ── OTE Fibonacci window ─────────────────────────────────────────
OTE_LOW = 0.62  # 62% retracement
OTE_HIGH = 0.79  # 79% retracement

# ── H4 OB confirmation strength ──────────────────────────────────
OB_MOVE_FACTOR = 2.0  # next candle body must be >= 2× OB body

# ── Daily bias lookback ──────────────────────────────────────────
DAILY_LOOKBACK = 20  # 20-trading-day high/low (~1 month)

# ── Best trading days (isoweekday: 1=Mon … 7=Sun) ───────────────
BEST_DAYS = {2, 3, 4}  # Tue, Wed, Thu

# ── Score values ─────────────────────────────────────────────────
PTS_BIAS = 30
PTS_ZONE = 30
PTS_KZ = 30
PTS_JUDAS = 30
PTS_OBFVG = 30
TOTAL_MAX = 150

IST = timezone(timedelta(hours=5, minutes=30))
UTC = UTC


# ══════════════════════════════════════════════════════════════════
# STEP 1 — DAILY BIAS DETECTION
# ══════════════════════════════════════════════════════════════════


def detect_daily_bias(df_daily: pd.DataFrame, pdh=None, pdl=None) -> dict:
    """
    Determine market bias from the Daily chart.

    Rules:
      Bullish : close > 50-period low  (price holding above long-term support)
      Bearish : close < 50-period high (price below long-term resistance)

    Also returns PDH, PDL, and daily swing high/low.
    """
    empty = {
        "bias": None,
        "direction": None,
        "pdh": pdh,
        "pdl": pdl,
        "swing_high": None,
        "swing_low": None,
        "high_50": None,
        "low_50": None,
        "reason": "Insufficient daily data — using H4 fallback",
    }

    if df_daily is None or len(df_daily) < DAILY_LOOKBACK + 2:
        return empty

    close = float(df_daily["close"].iloc[-1])
    high_50 = float(df_daily["high"].iloc[-DAILY_LOOKBACK:].max())
    low_50 = float(df_daily["low"].iloc[-DAILY_LOOKBACK:].min())

    # Previous day H/L (prefer passed-in values)
    if pdh is None and len(df_daily) >= 2:
        pdh = round(float(df_daily["high"].iloc[-2]), 2)
    if pdl is None and len(df_daily) >= 2:
        pdl = round(float(df_daily["low"].iloc[-2]), 2)

    # Swing high / low on daily (3-bar pivot)
    swing_high = swing_low = None
    n = len(df_daily)
    for i in range(n - 3, max(2, n - 25), -1):
        h = float(df_daily["high"].iloc[i])
        if h == df_daily["high"].iloc[max(0, i - 3) : i + 4].max():
            swing_high = round(h, 2)
            break
    for i in range(n - 3, max(2, n - 25), -1):
        l = float(df_daily["low"].iloc[i])
        if l == df_daily["low"].iloc[max(0, i - 3) : i + 4].min():
            swing_low = round(l, 2)
            break

    # Bias
    margin = 0.001  # 0.1% tolerance band
    if close > low_50 * (1 + margin):
        bias, direction = "BULLISH", "LONG"
        reason = f"Bullish bias: price ${close:.2f} above 50D low ${low_50:.2f}"
    elif close < high_50 * (1 - margin):
        bias, direction = "BEARISH", "SHORT"
        reason = f"Bearish bias: price ${close:.2f} below 50D high ${high_50:.2f}"
    else:
        bias = direction = None
        reason = f"No clear bias: price ${close:.2f} near midrange"

    return {
        "bias": bias,
        "direction": direction,
        "pdh": pdh,
        "pdl": pdl,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "high_50": round(high_50, 2),
        "low_50": round(low_50, 2),
        "reason": reason,
    }


# ══════════════════════════════════════════════════════════════════
# STEP 2 — ZONE MAPPING ON H4
# ══════════════════════════════════════════════════════════════════


def detect_h4_ob(df_4h: pd.DataFrame, direction: str, lookback: int = 25) -> dict:
    """
    H4 Order Block with strong-move confirmation.

    Bullish OB = last bearish candle whose NEXT candle body is >= 2× its own body
                 (strong impulse up) AND the OB body has NOT been mitigated.
    Bearish OB = last bullish candle before a strong bearish impulse.
    """
    empty = {"valid": False, "high": None, "low": None, "body_top": None, "body_bot": None, "strength": None}
    n = len(df_4h)
    if n < 4:
        return empty

    for i in range(n - 2, max(0, n - lookback - 1), -1):
        row = df_4h.iloc[i]
        nxt = df_4h.iloc[i + 1] if i + 1 < n else None
        if nxt is None:
            continue

        o, c = float(row["open"]), float(row["close"])
        h, l = float(row["high"]), float(row["low"])
        no = float(nxt["open"])
        nc = float(nxt["close"])
        ob_body = abs(c - o)
        next_body = abs(nc - no)

        if ob_body < 1e-8:
            continue

        strength = round(next_body / ob_body, 2)

        if direction == "LONG" and c < o:  # bearish candle → bullish OB
            if nc > no and strength >= OB_MOVE_FACTOR:
                # Ensure OB body not yet mitigated (price never returned below body)
                future_lows = df_4h["low"].iloc[i + 1 :]
                if future_lows.empty or float(future_lows.min()) > c:
                    return {
                        "valid": True,
                        "high": round(h, 2),
                        "low": round(l, 2),
                        "body_top": round(o, 2),
                        "body_bot": round(c, 2),
                        "strength": strength,
                    }

        elif direction == "SHORT" and c > o:  # bullish candle → bearish OB
            if nc < no and strength >= OB_MOVE_FACTOR:
                future_highs = df_4h["high"].iloc[i + 1 :]
                if future_highs.empty or float(future_highs.max()) < c:
                    return {
                        "valid": True,
                        "high": round(h, 2),
                        "low": round(l, 2),
                        "body_top": round(c, 2),
                        "body_bot": round(o, 2),
                        "strength": strength,
                    }

    return empty


def detect_h4_fvg(df_4h: pd.DataFrame, direction: str, lookback: int = 15) -> dict:
    """
    H4 Fair Value Gap (3-candle imbalance).

    Bullish FVG : candle[i].high < candle[i+2].low → unfilled gap
    Bearish FVG : candle[i].low  > candle[i+2].high

    Returns top, bot, and 50% equilibrium level.
    """
    empty = {"valid": False, "top": None, "bot": None, "equilibrium": None, "filled": False}
    n = len(df_4h)
    if n < 3:
        return empty

    for i in range(n - 3, max(0, n - lookback - 3), -1):
        c1h = float(df_4h["high"].iloc[i])
        c1l = float(df_4h["low"].iloc[i])
        c3h = float(df_4h["high"].iloc[i + 2])
        c3l = float(df_4h["low"].iloc[i + 2])

        if direction == "LONG":
            if c3l > c1h:  # gap exists
                bot, top = c1h, c3l
                eq = round((top + bot) / 2, 2)
                filled = float(df_4h["low"].iloc[i + 2 :].min()) <= bot if i + 2 < n else False
                if not filled:
                    return {
                        "valid": True,
                        "top": round(top, 2),
                        "bot": round(bot, 2),
                        "equilibrium": eq,
                        "filled": False,
                    }

        elif direction == "SHORT":
            if c1l > c3h:
                top, bot = c1l, c3h
                eq = round((top + bot) / 2, 2)
                filled = float(df_4h["high"].iloc[i + 2 :].max()) >= top if i + 2 < n else False
                if not filled:
                    return {
                        "valid": True,
                        "top": round(top, 2),
                        "bot": round(bot, 2),
                        "equilibrium": eq,
                        "filled": False,
                    }

    return empty


def detect_premium_discount(df_4h: pd.DataFrame, direction: str) -> dict:
    """
    Premium / Discount classification on H4.

    Range = last major swing low → swing high (H4, last 60 bars).
    Equilibrium = 50% of the range.
    Discount < 50% → look for LONG.
    Premium  > 50% → look for SHORT.
    """
    empty = {
        "zone": None,
        "in_zone": False,
        "price": None,
        "eq": None,
        "pct": None,
        "swing_high": None,
        "swing_low": None,
    }

    n = len(df_4h)
    if n < 10:
        return empty

    window = df_4h.iloc[-min(60, n) :]
    swing_high = float(window["high"].max())
    swing_low = float(window["low"].min())

    if swing_high <= swing_low:
        return empty

    price = float(df_4h["close"].iloc[-1])
    rng = swing_high - swing_low
    eq = swing_low + rng * 0.5
    pct = round((price - swing_low) / rng * 100, 1)

    if pct < 50:
        zone = "DISCOUNT"
        in_zone = direction == "LONG"
    else:
        zone = "PREMIUM"
        in_zone = direction == "SHORT"

    return {
        "zone": zone,
        "in_zone": in_zone,
        "price": round(price, 2),
        "eq": round(eq, 2),
        "pct": pct,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
    }


# ══════════════════════════════════════════════════════════════════
# STEP 3 — KILL ZONE FILTER  (HARD BLOCK)
# ══════════════════════════════════════════════════════════════════


def get_active_killzone_ist(ist_h: int, ist_m: int) -> tuple:
    """
    Check if current IST time is inside a configured kill zone.
    Times are stored as HHMM integers for fast comparison.

    Returns: (zone_name: str | None, is_active: bool)
    """
    t = ist_h * 100 + ist_m
    for name, (start, end) in KILL_ZONES_IST.items():
        if start <= t <= end:
            return name, True
    return None, False


# ══════════════════════════════════════════════════════════════════
# STEP 4 — ASIAN SESSION RANGE + JUDAS SWING
# ══════════════════════════════════════════════════════════════════


def get_asian_range_ist(df_15m: pd.DataFrame) -> dict:
    """
    Compute today's Asian session high/low from M15 data (IST timestamps).
    Asian session in IST = 05:30 → 12:30  (= 00:00 → 07:00 UTC).
    Falls back to yesterday if today's Asian session data not yet full.
    """
    empty = {"high": None, "low": None, "valid": False}
    if df_15m is None or df_15m.empty:
        return empty

    # Convert 'time within IST day' to a numeric HHMM for filtering
    # df_15m.index is tz-naive IST after _clean()
    def _hhmm(ts):
        return ts.hour * 100 + ts.minute

    for delta_days in (0, 1, 2):
        ref_date = (df_15m.index[-1] - pd.Timedelta(days=delta_days)).date()
        day_bars = df_15m[df_15m.index.date == ref_date]
        if day_bars.empty:
            continue

        asian_start = ASIAN_IST_START_H * 100 + ASIAN_IST_START_M  # 530
        asian_end = ASIAN_IST_END_H * 100 + ASIAN_IST_END_M  # 1230
        hhmm_vals = pd.Series(day_bars.index.map(_hhmm), index=day_bars.index)
        asian = day_bars[hhmm_vals.between(asian_start, asian_end - 1)]
        if len(asian) >= 4:  # need at least 1 hour of bars
            return {
                "high": round(float(asian["high"].max()), 2),
                "low": round(float(asian["low"].min()), 2),
                "valid": True,
            }

    return empty


def detect_judas_swing(df_15m: pd.DataFrame, direction: str, asian_range: dict) -> dict:
    """
    Judas Swing: the engineered fake move at kill-zone open designed to
    trap retail traders before the real ICT move.

    Bullish bias → price first dips BELOW Asian session low, then recovers above it.
    Bearish bias → price first spikes ABOVE Asian session high, then drops below it.

    Look at the most recent 8 M15 bars (= 2 hours) inside the kill zone.
    """
    empty = {"confirmed": False, "sweep_level": None, "sweep_type": None, "reason": "No Judas swing detected"}

    if not asian_range.get("valid"):
        return {**empty, "reason": "Asian range not available"}
    if df_15m is None or len(df_15m) < 5:
        return empty

    asian_high = asian_range["high"]
    asian_low = asian_range["low"]
    recent = df_15m.iloc[-8:]
    cur_close = float(df_15m["close"].iloc[-1])

    if direction == "LONG":
        swept_low = float(recent["low"].min())
        if swept_low < asian_low:
            if cur_close > asian_low:
                return {
                    "confirmed": True,
                    "sweep_level": asian_low,
                    "sweep_type": "Asian Low Swept",
                    "reason": (f"Judas Swing LONG: swept Asian low ${asian_low:.2f} → recovered to ${cur_close:.2f}"),
                }
            return {**empty, "reason": f"Asian low ${asian_low:.2f} swept — awaiting recovery"}
        return {**empty, "reason": f"Asian low ${asian_low:.2f} NOT swept (min=${swept_low:.2f})"}

    # SHORT
    swept_high = float(recent["high"].max())
    if swept_high > asian_high:
        if cur_close < asian_high:
            return {
                "confirmed": True,
                "sweep_level": asian_high,
                "sweep_type": "Asian High Swept",
                "reason": (f"Judas Swing SHORT: swept Asian high ${asian_high:.2f} → rejected to ${cur_close:.2f}"),
            }
        return {**empty, "reason": f"Asian high ${asian_high:.2f} swept — awaiting rejection"}
    return {**empty, "reason": f"Asian high ${asian_high:.2f} NOT swept (max=${swept_high:.2f})"}


# ══════════════════════════════════════════════════════════════════
# STEP 5a — CHOCH ON M15
# ══════════════════════════════════════════════════════════════════


def detect_choch_m15(df_15m: pd.DataFrame, direction: str, lookback: int = 20) -> dict:
    """
    Change of Character (CHOCH) on M15.

    Bullish CHOCH : price breaks above the last lower high (LH) on M15
                    → signals shift from bearish to bullish structure
    Bearish CHOCH : price breaks below the last higher low (HL) on M15
    """
    empty = {"confirmed": False, "level": None, "reason": "No CHOCH on M15"}
    if df_15m is None or len(df_15m) < 10:
        return empty

    n = len(df_15m)
    close = float(df_15m["close"].iloc[-1])

    if direction == "LONG":
        # Collect recent swing highs
        swing_highs = []
        for i in range(n - 2, max(0, n - lookback), -1):
            h = float(df_15m["high"].iloc[i])
            window = df_15m["high"].iloc[max(0, i - 2) : i + 3]
            if h == float(window.max()):
                swing_highs.append(h)
                if len(swing_highs) >= 2:
                    break

        if swing_highs:
            lh = swing_highs[0]  # most recent swing high
            if close > lh:
                return {"confirmed": True, "level": round(lh, 2), "reason": f"Bullish CHOCH: closed above LH ${lh:.2f}"}

    else:  # SHORT
        swing_lows = []
        for i in range(n - 2, max(0, n - lookback), -1):
            l = float(df_15m["low"].iloc[i])
            window = df_15m["low"].iloc[max(0, i - 2) : i + 3]
            if l == float(window.min()):
                swing_lows.append(l)
                if len(swing_lows) >= 2:
                    break

        if swing_lows:
            hl = swing_lows[0]
            if close < hl:
                return {"confirmed": True, "level": round(hl, 2), "reason": f"Bearish CHOCH: closed below HL ${hl:.2f}"}

    return empty


# ══════════════════════════════════════════════════════════════════
# STEP 5b — OTE (OPTIMAL TRADE ENTRY) 62–79% FIBONACCI
# ══════════════════════════════════════════════════════════════════


def detect_ote(df_15m: pd.DataFrame, direction: str) -> dict:
    """
    OTE: price in the 62–79% retracement zone of the last swing.

    Bullish OTE : swing low → swing high, then price retraces 62–79% down
    Bearish OTE : swing high → swing low, then price bounces 62–79% up
    """
    empty = {"in_zone": False, "fib_62": None, "fib_79": None, "swing_high": None, "swing_low": None, "pct": None}
    if df_15m is None or len(df_15m) < 15:
        return empty

    window = df_15m.iloc[-min(40, len(df_15m)) :]
    sh = float(window["high"].max())
    sl = float(window["low"].min())
    close = float(df_15m["close"].iloc[-1])

    if sh <= sl:
        return empty

    rng = sh - sl

    if direction == "LONG":
        # Retracing from high → 62–79% down means price is at (sh - 0.79*rng) to (sh - 0.62*rng)
        fib_79 = round(sh - rng * OTE_HIGH, 2)  # deeper (79%)
        fib_62 = round(sh - rng * OTE_LOW, 2)  # shallower (62%)
        in_zone = fib_79 <= close <= fib_62
        pct = round((sh - close) / rng * 100, 1)
    else:
        fib_62 = round(sl + rng * OTE_LOW, 2)
        fib_79 = round(sl + rng * OTE_HIGH, 2)
        in_zone = fib_62 <= close <= fib_79
        pct = round((close - sl) / rng * 100, 1)

    return {
        "in_zone": in_zone,
        "fib_62": fib_62,
        "fib_79": fib_79,
        "swing_high": round(sh, 2),
        "swing_low": round(sl, 2),
        "pct": pct,
    }


# ══════════════════════════════════════════════════════════════════
# STEP 5c — M5 CONFIRMATION CANDLE
# ══════════════════════════════════════════════════════════════════


def detect_m5_confirmation(df_5m: pd.DataFrame, direction: str, ob: dict, fvg: dict) -> dict:
    """
    Final entry trigger: M5 candle closes bullish (LONG) or bearish (SHORT)
    while price is inside the H4 Order Block or FVG zone.
    """
    empty = {"confirmed": False, "candle_type": None, "zone_type": None, "reason": "No M5 confirmation"}
    if df_5m is None or len(df_5m) < 2:
        return {**empty, "reason": "M5 data not available"}

    last = df_5m.iloc[-1]
    o, c = float(last["open"]), float(last["close"])
    _h, _l = float(last["high"]), float(last["low"])

    if direction == "LONG":
        if c <= o:  # not a bullish close
            return {**empty, "reason": "M5: last candle not bullish"}
        # Inside OB?
        if ob.get("valid"):
            ob_top = ob.get("body_top") or ob.get("high") or 0
            ob_bot = ob.get("body_bot") or ob.get("low") or 0
            if ob_bot <= c <= ob_top or ob_bot <= o <= ob_top:
                return {
                    "confirmed": True,
                    "candle_type": "Bullish",
                    "zone_type": "OB",
                    "reason": (f"M5 bullish candle inside OB ${ob_bot:.2f}–${ob_top:.2f}"),
                }
        # Inside FVG?
        if fvg.get("valid"):
            fb, ft = fvg.get("bot") or 0, fvg.get("top") or 0
            if fb <= c <= ft or fb <= o <= ft:
                return {
                    "confirmed": True,
                    "candle_type": "Bullish",
                    "zone_type": "FVG",
                    "reason": (f"M5 bullish candle inside FVG ${fb:.2f}–${ft:.2f}"),
                }

    else:  # SHORT
        if c >= o:
            return {**empty, "reason": "M5: last candle not bearish"}
        if ob.get("valid"):
            ob_top = ob.get("body_top") or ob.get("high") or 0
            ob_bot = ob.get("body_bot") or ob.get("low") or 0
            if ob_bot <= c <= ob_top or ob_bot <= o <= ob_top:
                return {
                    "confirmed": True,
                    "candle_type": "Bearish",
                    "zone_type": "OB",
                    "reason": (f"M5 bearish candle inside OB ${ob_bot:.2f}–${ob_top:.2f}"),
                }
        if fvg.get("valid"):
            fb, ft = fvg.get("bot") or 0, fvg.get("top") or 0
            if fb <= c <= ft or fb <= o <= ft:
                return {
                    "confirmed": True,
                    "candle_type": "Bearish",
                    "zone_type": "FVG",
                    "reason": (f"M5 bearish candle inside FVG ${fb:.2f}–${ft:.2f}"),
                }

    return {**empty, "reason": "M5 candle not inside OB or FVG zone"}


# ══════════════════════════════════════════════════════════════════
# STEP 6 — TRADE PARAMETERS
# ══════════════════════════════════════════════════════════════════


def _calc_trade_params(entry: float, ob: dict, fvg: dict, direction: str, asian_range: dict | None = None) -> dict:
    """
    SL  = $0.50 below OB low (LONG) / above OB high (SHORT).
    Falls back to FVG geometry, then Asian session range extremes.
    TP1 = 1.5 × risk,  TP2 = 3.0 × risk.
    """
    empty = {"valid": False}

    # Determine zone boundaries — OB first, then FVG, then Asian range
    if ob.get("valid"):
        zone_high = ob.get("high") or 0
        zone_low = ob.get("low") or 0
    elif fvg.get("valid"):
        zone_high = fvg.get("top") or 0
        zone_low = fvg.get("bot") or 0
    elif asian_range and asian_range.get("valid"):
        # ICT fallback: Asian session extremes are natural S/R levels.
        # When Judas Swing is confirmed the swept Asian extreme IS the SL.
        zone_high = float(asian_range.get("high") or 0)
        zone_low = float(asian_range.get("low") or 0)
    else:
        return empty

    if direction == "LONG":
        sl = round(zone_low - SL_BUFFER, 2)
        if sl >= entry:
            return empty
        risk = entry - sl
    else:
        sl = round(zone_high + SL_BUFFER, 2)
        if sl <= entry:
            return empty
        risk = sl - entry

    if risk <= 0:
        return empty

    sl_pct = round(risk / entry * 100, 3)

    if direction == "LONG":
        t1 = round(entry + risk * TP1_R, 2)
        t2 = round(entry + risk * TP2_R, 2)
    else:
        t1 = round(entry - risk * TP1_R, 2)
        t2 = round(entry - risk * TP2_R, 2)

    return {
        "valid": True,
        "entry": round(entry, 2),
        "sl": sl,
        "sl_pct": sl_pct,
        "t1": t1,
        "t2": t2,
        "risk": round(risk, 2),
        "rr_t1": TP1_R,
        "rr_t2": TP2_R,
    }


# ══════════════════════════════════════════════════════════════════
# MAIN SCORING FUNCTION
# ══════════════════════════════════════════════════════════════════


def score_gold(
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_daily: pd.DataFrame = None,
    df_5m: pd.DataFrame = None,
    pdh=None,
    pdl=None,
    dxy_data: dict | None = None,
    ist_time: datetime | None = None,
    risk_pct: float = RISK_PCT_DEFAULT,
) -> dict:
    """
    ICT + SMC Gold Strategy — 5-point confluence scoring.

    Parameters
    ----------
    df_4h    : H4 OHLCV  (for OB, FVG, Premium/Discount)
    df_1h    : H1 OHLCV  (structure reference, kept for compatibility)
    df_15m   : M15 OHLCV (CHOCH, OTE, Judas Swing, Asian range)
    df_daily : Daily OHLCV (bias detection — optional, falls back to H4)
    df_5m    : M5 OHLCV  (entry confirmation — optional but recommended)
    pdh/pdl  : Previous day high/low overrides
    dxy_data : DXY dict (optional — informational only in this strategy)
    ist_time : Current IST datetime (timezone-aware)
    risk_pct : % of balance to risk per trade

    Returns
    -------
    Signal dict (compatible with existing notifier / logger) or {} if blocked.
    """

    # ── Basic guards ─────────────────────────────────────────────
    if df_15m is None or len(df_15m) < 15:
        return {}
    if df_4h is None or len(df_4h) < 10:
        return {}

    if ist_time is None:
        ist_time = datetime.now(IST)

    ist_h = ist_time.hour
    ist_m = ist_time.minute
    day_name = ist_time.strftime("%A")
    best_day = ist_time.isoweekday() in BEST_DAYS

    reasons = []  # confluence log — populated as we check each factor

    # ═══════════════════════════════════════════════
    # [HARD BLOCK] KILL ZONE CHECK  (done first —
    #  no point scoring if outside kill zone)
    # ═══════════════════════════════════════════════
    kz_name, kz_active = get_active_killzone_ist(ist_h, ist_m)
    if not kz_active:
        return {}  # Outside kill zone — no trade

    pts_kz = PTS_KZ
    reasons.append(f"[3] Kill Zone: {kz_name} active ({ist_time.strftime('%H:%M')} IST) +{pts_kz}pts")

    # ═══════════════════════════════════════════════
    # CONFLUENCE [1]: DAILY BIAS
    # ═══════════════════════════════════════════════
    daily = detect_daily_bias(df_daily, pdh=pdh, pdl=pdl)
    direction = daily.get("direction")

    # Fallback: if no daily data, use H4 BOS/CHOCH for direction
    if not direction:
        from shared.smc_engine import detect_bos_choch

        struct = detect_bos_choch(df_4h, left=3, right=3)
        if struct["bos"] or struct["choch"]:
            direction = struct["direction"]
            daily["direction"] = direction
            daily["bias"] = "BULLISH" if direction == "LONG" else "BEARISH"
            daily["reason"] = f"H4 {'BOS' if struct['bos'] else 'CHOCH'} fallback ({direction}) — no daily data"
        if not direction:
            return {}  # No structure at all → skip

    bias_clear = bool(daily.get("bias"))
    pts_bias = PTS_BIAS if bias_clear else 0
    reasons.append(f"[1] {daily['reason']} +{pts_bias}pts")

    # ═══════════════════════════════════════════════
    # CONFLUENCE [2]: PREMIUM / DISCOUNT ZONE
    # ═══════════════════════════════════════════════
    pd_zone = detect_premium_discount(df_4h, direction)
    in_zone = pd_zone["in_zone"]
    pts_zone = PTS_ZONE if in_zone else 0
    zone_lbl = pd_zone.get("zone", "Unknown")
    zone_pct = pd_zone.get("pct", "?")
    if in_zone:
        reasons.append(f"[2] {zone_lbl} zone ({zone_pct}% of range) — ideal for {direction} +{pts_zone}pts")
    else:
        reasons.append(f"[2] {zone_lbl} zone ({zone_pct}%) — not optimal for {direction} (0pts)")

    # ═══════════════════════════════════════════════
    # CONFLUENCE [4]: JUDAS SWING
    # ═══════════════════════════════════════════════
    asian_range = get_asian_range_ist(df_15m)
    judas = detect_judas_swing(df_15m, direction, asian_range)
    pts_judas = PTS_JUDAS if judas["confirmed"] else 0
    if judas["confirmed"]:
        reasons.append(f"[4] {judas['reason']} +{pts_judas}pts")
    else:
        reasons.append(f"[4] Judas Swing: {judas['reason']} (0pts)")

    # ═══════════════════════════════════════════════
    # CONFLUENCE [5]: H4 ORDER BLOCK or FVG at OTE
    # ═══════════════════════════════════════════════
    ob = detect_h4_ob(df_4h, direction)
    fvg = detect_h4_fvg(df_4h, direction)
    ote = detect_ote(df_15m, direction)

    has_ob_fvg = ob.get("valid") or fvg.get("valid")
    pts_obfvg = PTS_OBFVG if has_ob_fvg else 0

    if ob.get("valid"):
        reasons.append(
            f"[5] H4 OB {ob['body_bot']:.2f}–{ob['body_top']:.2f} (strength {ob.get('strength', '?')}x) +{pts_obfvg}pts"
        )
    if fvg.get("valid"):
        reasons.append(f"[5] H4 FVG {fvg['bot']:.2f}–{fvg['top']:.2f} EQ ${fvg['equilibrium']:.2f} +{pts_obfvg}pts")
    if not has_ob_fvg:
        reasons.append("[5] No H4 OB or FVG found (0pts)")

    # ═══════════════════════════════════════════════
    # TOTAL CONFLUENCE
    # ═══════════════════════════════════════════════
    total = pts_bias + pts_zone + pts_kz + pts_judas + pts_obfvg
    confluence = sum([bias_clear, in_zone, kz_active, judas["confirmed"], has_ob_fvg])

    if total < MIN_SCORE:
        return {}  # Less than 4 / 5 confluence — no trade

    # ═══════════════════════════════════════════════
    # ENTRY PRICE + TRADE PARAMETERS
    # ═══════════════════════════════════════════════
    entry = round(float(df_15m["close"].iloc[-1]), 2)
    tp = _calc_trade_params(entry, ob, fvg, direction, asian_range=asian_range)
    if not tp["valid"]:
        return {}

    # ═══════════════════════════════════════════════
    # ADDITIONAL CONTEXT (non-blocking, informational)
    # ═══════════════════════════════════════════════
    choch = detect_choch_m15(df_15m, direction)
    m5_confirm = detect_m5_confirmation(df_5m, direction, ob, fvg)

    if ote["in_zone"]:
        reasons.append(f"OTE: {ote['pct']}% fib retracement — inside 62–79% zone")
    else:
        reasons.append(f"OTE: {ote.get('pct', '?')}% fib — outside ideal 62–79%")

    if choch["confirmed"]:
        reasons.append(f"CHOCH M15: {choch['reason']}")

    if m5_confirm["confirmed"]:
        reasons.append(f"M5 confirm: {m5_confirm['reason']}")
    else:
        reasons.append(f"M5: {m5_confirm['reason']}")

    if daily.get("pdh") and daily.get("pdl"):
        reasons.append(f"PDH ${daily['pdh']:.2f} / PDL ${daily['pdl']:.2f}")

    if asian_range.get("valid"):
        reasons.append(f"Asian range: ${asian_range['low']:.2f}–${asian_range['high']:.2f}")

    reasons.append(f"Day: {day_name} ({'Best day' if best_day else 'Non-ideal — prefer Tue/Wed/Thu'})")

    # ═══════════════════════════════════════════════
    # BUILD SIGNAL DICT
    # ═══════════════════════════════════════════════
    pct_score = round(total / TOTAL_MAX * 100, 1)
    strength = "EXCELLENT" if confluence >= 5 else "GOOD" if confluence >= 4 else "WEAK"

    return {
        # Identity
        "asset": ASSET,
        "symbol": "XAUUSD",
        "direction": direction,
        "signal": "BUY" if direction == "LONG" else "SELL",
        # Score
        "score": total,
        "score_pct": pct_score,
        "signal_strength": strength,
        "confluence": confluence,
        "confluence_str": f"{confluence}/5",
        "blocked_reason": None,
        "kill_zone": kz_name,
        # Checklist (used by dashboard)
        "phase_scores": {
            "smc_structure": pts_bias + pts_judas,
            "ict_gold_filters": pts_kz + pts_zone,
            "pa_boosters": pts_obfvg,
        },
        "must_have_checklist": {
            "htf_bias_clear": bias_clear,
            "premium_discount_zone": in_zone,
            "kill_zone_active": kz_active,
            "judas_swing": judas["confirmed"],
            "ob_or_fvg_present": has_ob_fvg,
        },
        # Trade levels
        "trade_params": {
            "entry": tp["entry"],
            "sl": tp["sl"],
            "sl_pct": tp["sl_pct"],
            "t1": tp["t1"],
            "t2": tp["t2"],
            "rr_t1": tp["rr_t1"],
            "rr_t2": tp["rr_t2"],
            "risk": tp["risk"],
        },
        # ICT details (for logging / dashboard)
        "daily_bias": daily,
        "premium_discount": pd_zone,
        "asian_range": asian_range,
        "judas_swing": judas,
        "choch_m15": choch,
        "order_block": ob,
        "fvg": fvg,
        "ote": ote,
        "m5_confirmation": m5_confirm,
        "dxy_confirmation": bool(dxy_data and dxy_data.get("bearish" if direction == "LONG" else "bullish", False)),
        # Backward-compatible keys (notifier / logger)
        "entry": tp["entry"],
        "target": tp["t2"],
        "t1": tp["t1"],
        "sl": tp["sl"],
        "rr": tp["rr_t2"],
        "reasons": reasons,
        "rsi": None,
        "vwap": None,
        "vol_ratio": 1.0,
        "confidence": strength,
        "timestamp": ist_time.isoformat(),
        "risk_pct": risk_pct,
    }

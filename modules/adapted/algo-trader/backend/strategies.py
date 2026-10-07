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
Opening Range Breakout (ORB) — single intraday strategy for NSE.

Validation basis: IntradayLab NSE backtest (2017–2026, 2,122 trades).
  - Profitable in 8 of 9 years
  - Win rate 48.7%, avg win +0.48% vs avg loss -0.37%
  - The asymmetric win/loss ratio is the structural edge

No other strategy ships here. Each additional strategy requires equivalent
NSE-specific backtest evidence before it can be added.
"""

from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")

_ORB_BARS = 6  # 9:15–9:45 observation window at 5m resolution
_VOL_CONFIRM = 1.5  # breakout bar must have 1.5x rolling avg volume
_MIN_BODY_RATIO = 0.40  # breakout candle body must be ≥40% of bar range (no dojis)
_MIN_OR_RANGE_PCT = 0.30  # skip day if OR range < 0.3% of midpoint (no momentum)
_ORB_ENTRY_CUTOFF = (11, 30)  # no new entries after 11:30 IST — ORB works on first move only
_MAX_CHASE_PCT = 0.005  # anti-chase: skip if entry is >0.5% beyond OR level


def apply_orb(df: pd.DataFrame) -> pd.DataFrame:
    """
    Opening Range Breakout.

    Observation window (9:15–9:45): establish the high and low of the first
    6 five-minute bars. After 9:45, enter when:
      - Close breaks above OR high (long) or below OR low (short)
      - Volume is 2× the rolling average (confirmed momentum)
      - Breakout candle has a real body (≥40% of bar range — not a doji)

    SL/TP (injected as hints for the simulator):
      Long:  SL = or_low  (structural — range failed if we fall back through it)
             TP = entry + 1.5 × or_range
      Short: SL = or_high
             TP = entry - 1.5 × or_range

    Skips:
      - Days where OR range < 0.3% of price (no volatility = no ORB edge)
      - Entries after 12:00 IST (insufficient time for TP to be reached)
    """
    df = df.copy()
    df["signal"] = 0
    df["sl_hint"] = float("nan")
    df["tp_hint"] = float("nan")

    if len(df) <= _ORB_BARS:
        return df

    obs = df.iloc[:_ORB_BARS]
    or_high = obs["high"].max()
    or_low = obs["low"].min()
    or_mid = (or_high + or_low) / 2
    or_range = or_high - or_low

    df["or_high"] = or_high
    df["or_low"] = or_low

    # Skip low-volatility days — no momentum = no ORB edge
    if or_mid > 0 and (or_range / or_mid * 100) < _MIN_OR_RANGE_PCT:
        return df

    avg_vol = df["vol_avg"] if "vol_avg" in df.columns else df["volume"].rolling(20).mean()

    # Time gates
    cutoff_ist = (
        df.index[0]
        .astimezone(IST)
        .replace(hour=_ORB_ENTRY_CUTOFF[0], minute=_ORB_ENTRY_CUTOFF[1], second=0, microsecond=0)
    )
    in_trade_window = pd.Series(False, index=df.index)
    in_trade_window.iloc[_ORB_BARS:] = True
    in_trade_window &= pd.Series(
        [ts.astimezone(IST) <= cutoff_ist for ts in df.index], index=df.index
    )

    # Candle quality: real body (not doji / spinning top)
    bar_range = (df["high"] - df["low"]).replace(0, float("nan"))
    candle_body = (df["close"] - df["open"]).abs()
    strong_candle = candle_body / bar_range >= _MIN_BODY_RATIO

    # VWAP alignment filter: long only when breakout closes above VWAP (price is with
    # the day's institutional flow), short only when below. Breakouts against VWAP
    # are the primary failure mode — they reverse because they fight the day's direction.
    vwap_s = df["vwap"] if "vwap" in df.columns else df["close"]
    above_vwap = df["close"] > vwap_s
    below_vwap = df["close"] < vwap_s

    # Entry conditions (single-bar — fire on the breakout bar itself)
    breakout_up = (
        in_trade_window
        & (df["close"] > or_high)
        & (df["volume"] > avg_vol * _VOL_CONFIRM)
        & strong_candle
        & above_vwap  # VWAP filter: long only when price is above VWAP
    )
    breakout_dn = (
        in_trade_window
        & (df["close"] < or_low)
        & (df["volume"] > avg_vol * _VOL_CONFIRM)
        & strong_candle
        & below_vwap  # VWAP filter: short only when price is below VWAP
    )

    # First occurrence only (deduplicate consecutive True rows)
    long_entry = breakout_up & ~breakout_up.shift(1, fill_value=False)
    short_entry = breakout_dn & ~breakout_dn.shift(1, fill_value=False)

    # Anti-chase filter: skip entries where price has already run >0.5% past the OR level.
    # A late entry inflates sl_distance (entry is far above or_high) which ruins the 2:1 R:R.
    long_entry = long_entry & (df["close"] <= or_high * (1 + _MAX_CHASE_PCT))
    short_entry = short_entry & (df["close"] >= or_low * (1 - _MAX_CHASE_PCT))

    df.loc[long_entry, "signal"] = 1
    df.loc[short_entry, "signal"] = -1

    # SL/TP hints — 2:1 reward:risk based on actual stop distance
    # sl_distance = how far entry is from the structural SL (or_low / or_high).
    # TP = entry ± 2 × sl_distance, so every trade targets exactly 2:1 R:R.
    # At 40% WR, breakeven requires only 33% WR with 2:1 — this gives margin.
    if or_range > 0:
        long_entries = df.index[long_entry]
        short_entries = df.index[short_entry]

        for idx in long_entries:
            entry = float(df.loc[idx, "close"])
            sl_dist = entry - or_low
            if sl_dist <= 0:
                continue
            df.loc[idx, "sl_hint"] = or_low
            df.loc[idx, "tp_hint"] = round(entry + sl_dist * 2, 2)

        for idx in short_entries:
            entry = float(df.loc[idx, "close"])
            sl_dist = or_high - entry
            if sl_dist <= 0:
                continue
            df.loc[idx, "sl_hint"] = or_high
            df.loc[idx, "tp_hint"] = round(entry - sl_dist * 2, 2)

    return df


# ── Mean-reversion arms ───────────────────────────────────────────────────────
# These are the counter-family to ORB. On range days breakouts whipsaw and
# fading extremes back to fair value (VWAP / prior close) is what pays.
# The selector decides which family fits the day — no arm runs unconditionally.

_FADE_DEV_ATR = 2.0  # enter when price is ≥2 ATR away from VWAP
_FADE_SL_ATR = 1.5  # stop beyond the bar extreme — wide enough that costs stay < 0.5R
_FADE_ENTRY_CUTOFF = (14, 0)  # need time for reversion before square-off
_GAP_FADE_MIN_PCT = 0.30  # gaps smaller than this are noise
_GAP_FADE_MAX_PCT = 2.00  # gaps larger than this tend to run, not fill


def apply_vwap_fade(df: pd.DataFrame) -> pd.DataFrame:
    """
    VWAP mean reversion — fade stretched moves back to VWAP.

    After 9:45, when price closes ≥2 ATR below VWAP and the bar itself turns
    up (close > open), go long targeting VWAP. Mirrored for shorts.
    SL = bar extreme ∓ 1.5 ATR (structural: the stretch failed to reverse).
    """
    df = df.copy()
    df["signal"] = 0
    df["sl_hint"] = float("nan")
    df["tp_hint"] = float("nan")
    if len(df) <= _ORB_BARS or "vwap" not in df.columns or "atr" not in df.columns:
        return df

    cutoff_ist = (
        df.index[0]
        .astimezone(IST)
        .replace(hour=_FADE_ENTRY_CUTOFF[0], minute=_FADE_ENTRY_CUTOFF[1], second=0, microsecond=0)
    )
    in_window = pd.Series(False, index=df.index)
    in_window.iloc[_ORB_BARS:] = True
    in_window &= pd.Series([ts.astimezone(IST) <= cutoff_ist for ts in df.index], index=df.index)

    atr_s = df["atr"].replace(0, float("nan"))
    dev = (df["close"] - df["vwap"]) / atr_s  # signed stretch in ATR units

    long_setup = in_window & (dev <= -_FADE_DEV_ATR) & (df["close"] > df["open"])
    short_setup = in_window & (dev >= _FADE_DEV_ATR) & (df["close"] < df["open"])

    long_entry = long_setup & ~long_setup.shift(1, fill_value=False)
    short_entry = short_setup & ~short_setup.shift(1, fill_value=False)

    df.loc[long_entry, "signal"] = 1
    df.loc[short_entry, "signal"] = -1

    for idx in df.index[long_entry]:
        entry = float(df.loc[idx, "close"])
        sl = float(df.loc[idx, "low"]) - _FADE_SL_ATR * float(df.loc[idx, "atr"])
        tp = float(df.loc[idx, "vwap"])
        if tp > entry > sl:
            df.loc[idx, "sl_hint"] = round(sl, 2)
            df.loc[idx, "tp_hint"] = round(tp, 2)
        else:
            df.loc[idx, "signal"] = 0
    for idx in df.index[short_entry]:
        entry = float(df.loc[idx, "close"])
        sl = float(df.loc[idx, "high"]) + _FADE_SL_ATR * float(df.loc[idx, "atr"])
        tp = float(df.loc[idx, "vwap"])
        if tp < entry < sl:
            df.loc[idx, "sl_hint"] = round(sl, 2)
            df.loc[idx, "tp_hint"] = round(tp, 2)
        else:
            df.loc[idx, "signal"] = 0

    return df


def apply_gap_fade(df: pd.DataFrame) -> pd.DataFrame:
    """
    Gap fade — moderate overnight gaps (0.3–2.0%) fill toward the prior close
    most of the time. Requires a 'prev_close' column (injected by the runner).

    Gap-up day: after 9:45, if a bar closes below the day's open AND below VWAP
    (the gap is failing), go short targeting prev close. Mirrored for gap-downs.
    SL = day extreme so far ± 0.3 ATR.
    """
    df = df.copy()
    df["signal"] = 0
    df["sl_hint"] = float("nan")
    df["tp_hint"] = float("nan")
    if len(df) <= _ORB_BARS or "prev_close" not in df.columns:
        return df

    prev_close = float(df["prev_close"].iloc[0])
    day_open = float(df.iloc[0]["open"])
    if not prev_close or not day_open:
        return df
    gap_pct = (day_open - prev_close) / prev_close * 100
    if not (_GAP_FADE_MIN_PCT <= abs(gap_pct) <= _GAP_FADE_MAX_PCT):
        return df

    cutoff_ist = (
        df.index[0]
        .astimezone(IST)
        .replace(hour=_FADE_ENTRY_CUTOFF[0], minute=_FADE_ENTRY_CUTOFF[1], second=0, microsecond=0)
    )
    in_window = pd.Series(False, index=df.index)
    in_window.iloc[_ORB_BARS:] = True
    in_window &= pd.Series([ts.astimezone(IST) <= cutoff_ist for ts in df.index], index=df.index)

    vwap_s = df["vwap"] if "vwap" in df.columns else df["close"]
    atr_s = df["atr"] if "atr" in df.columns else (df["high"] - df["low"]).rolling(14).mean()

    if gap_pct > 0:  # gap up → fade short toward prev close
        setup = (
            in_window
            & (df["close"] < day_open)
            & (df["close"] < vwap_s)
            & (df["close"] > prev_close)
        )
        entry_rows = setup & ~setup.shift(1, fill_value=False)
        df.loc[entry_rows, "signal"] = -1
        for idx in df.index[entry_rows]:
            entry = float(df.loc[idx, "close"])
            sl = float(df.loc[:idx, "high"].max()) + 0.3 * float(atr_s.loc[idx])
            tp = prev_close
            if tp < entry < sl:
                df.loc[idx, "sl_hint"] = round(sl, 2)
                df.loc[idx, "tp_hint"] = round(tp, 2)
            else:
                df.loc[idx, "signal"] = 0
    else:  # gap down → fade long toward prev close
        setup = (
            in_window
            & (df["close"] > day_open)
            & (df["close"] > vwap_s)
            & (df["close"] < prev_close)
        )
        entry_rows = setup & ~setup.shift(1, fill_value=False)
        df.loc[entry_rows, "signal"] = 1
        for idx in df.index[entry_rows]:
            entry = float(df.loc[idx, "close"])
            sl = float(df.loc[:idx, "low"].min()) - 0.3 * float(atr_s.loc[idx])
            tp = prev_close
            if tp > entry > sl:
                df.loc[idx, "sl_hint"] = round(sl, 2)
                df.loc[idx, "tp_hint"] = round(tp, 2)
            else:
                df.loc[idx, "signal"] = 0

    return df


# ── Intraday momentum ride (noise-band breakout, hold to close) ──────────────
# Basis: Zarattini/Aziz/Barbon (SSRN 4824172) — price escaping the "noise area"
# (open ± avg |move-from-open| at that time of day) signals a demand/supply
# imbalance; the move tends to persist into the close. Intraday time-series
# momentum is also confirmed for China (CSI) and APAC markets, strongest on
# high-volume/high-volatility days. The win is the rest of the day's trend, so
# costs are a small fraction of R — this is the arm built to clear the cost wall.

_MOMO_ENTRY_CUTOFF = (13, 30)  # breakout later than this has too little day left
_MOMO_MIN_NOISE_PCT = 0.25  # band half-width ≥0.25% so the stop clears the cost floor
_MOMO_MAX_RR = 4.0  # TP cap at 4R — effectively "ride to close"


def apply_momo_ride(df: pd.DataFrame) -> pd.DataFrame:
    """
    Noise-band momentum: after 9:45, go long on the first close above the upper
    noise band with price above VWAP (short mirrored below). SL one band
    half-width from entry; TP at 4R (rarely hit — the designed exit is the
    15:15 square-off, capturing the day's drift).

    Requires noise_up / noise_dn columns (injected by the runner from the
    prior 10 sessions — strictly causal).
    """
    df = df.copy()
    df["signal"] = 0
    df["sl_hint"] = float("nan")
    df["tp_hint"] = float("nan")
    if len(df) <= _ORB_BARS or "noise_up" not in df.columns:
        return df

    cutoff_ist = (
        df.index[0]
        .astimezone(IST)
        .replace(hour=_MOMO_ENTRY_CUTOFF[0], minute=_MOMO_ENTRY_CUTOFF[1], second=0, microsecond=0)
    )
    in_window = pd.Series(False, index=df.index)
    in_window.iloc[_ORB_BARS:] = True
    in_window &= pd.Series([ts.astimezone(IST) <= cutoff_ist for ts in df.index], index=df.index)

    vwap_s = df["vwap"] if "vwap" in df.columns else df["close"]
    half_w = (df["noise_up"] - df["noise_dn"]) / 2

    # Per-bar trailing stop levels (Zarattini exit): a long is out when price
    # falls back to the lower band or VWAP, whichever is higher. The simulator
    # ratchets the SL along these — winners ride, reversals get cut.
    df["trail_long"] = pd.concat([df["noise_dn"], vwap_s], axis=1).max(axis=1)
    df["trail_short"] = pd.concat([df["noise_up"], vwap_s], axis=1).min(axis=1)

    long_setup = in_window & (df["close"] > df["noise_up"]) & (df["close"] > vwap_s)
    short_setup = in_window & (df["close"] < df["noise_dn"]) & (df["close"] < vwap_s)

    long_entry = long_setup & ~long_setup.shift(1, fill_value=False)
    short_entry = short_setup & ~short_setup.shift(1, fill_value=False)

    df.loc[long_entry, "signal"] = 1
    df.loc[short_entry, "signal"] = -1

    for idx in df.index[long_entry]:
        entry = float(df.loc[idx, "close"])
        hw = float(half_w.loc[idx])
        if entry <= 0 or hw / entry * 100 < _MOMO_MIN_NOISE_PCT:
            df.loc[idx, "signal"] = 0
            continue
        df.loc[idx, "sl_hint"] = round(entry - hw, 2)
        df.loc[idx, "tp_hint"] = round(entry + _MOMO_MAX_RR * hw, 2)
    for idx in df.index[short_entry]:
        entry = float(df.loc[idx, "close"])
        hw = float(half_w.loc[idx])
        if entry <= 0 or hw / entry * 100 < _MOMO_MIN_NOISE_PCT:
            df.loc[idx, "signal"] = 0
            continue
        df.loc[idx, "sl_hint"] = round(entry + hw, 2)
        df.loc[idx, "tp_hint"] = round(entry - _MOMO_MAX_RR * hw, 2)

    return df


# ── Registry and helpers (used by backtest.py / selector.py) ─────────────────

STRATEGY_REGISTRY = {
    "ORB": {
        "id": "ORB",
        "name": "Opening Range Breakout",
        "description": "9:15–9:45 opening range; enters on volume-confirmed close "
        "above (long) or below (short) the range with structural SL/TP. "
        "Trend-day arm.",
        "fn": apply_orb,
    },
    "VWAP_FADE": {
        "id": "VWAP_FADE",
        "name": "VWAP Mean Reversion",
        "description": "Fades moves stretched ≥2 ATR from VWAP back to VWAP. Range-day arm.",
        "fn": apply_vwap_fade,
    },
    "GAP_FADE": {
        "id": "GAP_FADE",
        "name": "Gap Fade",
        "description": "Fades failing moderate overnight gaps (0.3–2%) toward the "
        "prior close. Gap-day arm.",
        "fn": apply_gap_fade,
    },
    "MOMO": {
        "id": "MOMO",
        "name": "Momentum Ride",
        "description": "Noise-band breakout (open ± typical move-from-open), rides "
        "the imbalance to the 15:15 close. Trend-day arm built to "
        "clear costs: the win is the whole day's drift.",
        "fn": apply_momo_ride,
    },
}


def get_strategy_fn(strategy_id: str):
    """Return strategy function by ID. Defaults to ORB for unknown IDs."""
    meta = STRATEGY_REGISTRY.get((strategy_id or "ORB").upper())
    return meta["fn"] if meta else apply_orb

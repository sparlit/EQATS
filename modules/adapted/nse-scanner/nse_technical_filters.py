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
nse_technical_filters.py — Forward-Looking Technical Scoring Engine (v3)
=========================================================================
WHAT CHANGED FROM v2:
  NEW: Weekly HMA two-tier alignment system

  Tier 1 — WEEKLY STRONGLY BULLISH
    Weekly HMA20 slope up AND weekly HMA20 > weekly HMA55
    → Full pass, eligible for PRIME ENTRY

  Tier 2 — WEEKLY NEUTRAL (pullback in uptrend)
    Weekly HMA20 > weekly HMA55 (long trend intact)
    BUT weekly HMA20 slope flat/negative (resting)
    → Pass but situation capped at WATCH CLOSELY

  Tier 3 — WEEKLY BEARISH (hard remove)
    Weekly HMA20 ≤ weekly HMA55 (trend broken)
    → HARD REMOVE from list entirely

WHY TWO-TIER NOT HARD:
  Hard filter misses pullback entries — best opportunities
  Two-tier keeps them but prevents premature PRIME signals

NEW EXPORTS:
  get_weekly_tiers_bulk()
  WEEKLY_TIER_BULLISH = 1
  WEEKLY_TIER_NEUTRAL = 2
  WEEKLY_TIER_BEARISH = 3
  get_weekly_tier_label()
"""

from datetime import date

import numpy as np
import pandas as pd

TIER_HIGH_CONVICTION = "HIGH CONVICTION"
TIER_WATCHLIST = "Watchlist"

WEEKLY_TIER_BULLISH = 1
WEEKLY_TIER_NEUTRAL = 2
WEEKLY_TIER_BEARISH = 3

CATEGORY_META = {
    "rising": {"icon": "📈", "label": "Consistently Rising", "desc": "Steady momentum, early in the move"},
    "uptrend": {"icon": "🚀", "label": "Clear Uptrend Confirmed", "desc": "Fresh cross, room to run, volume confirmed"},
    "peak": {"icon": "🔝", "label": "Close to Their Peak", "desc": "Near 52-week highs — strong institutional demand"},
    "recovering": {"icon": "📉", "label": "Recovering from a Fall", "desc": "Bouncing back — early recovery signal"},
    "safer": {
        "icon": "🛡️",
        "label": "Safer Bets with Good Reward",
        "desc": "Tight stop, high delivery, lower risk setup",
    },
}
CATEGORY_ORDER = ["uptrend", "rising", "peak", "safer", "recovering"]

SECTOR_BIAS = {
    "PHARMA": +1,
    "HEALTHCARE": +1,
    "DEFENCE": +1,
    "PSU": +1,
    "INFRA": +1,
    "CAPITAL": +1,
    "POWER": +1,
    "ENERGY": +1,
    "FMCG": 0,
    "IT": 0,
    "TECH": 0,
    "AUTO": 0,
    "AUTO ANCIL": 0,
    "BANK": 0,
    "FINANCE": 0,
    "NBFC": 0,
    "REALTY": 0,
    "METAL": -1,
    "STEEL": -1,
    "CHEMICAL": 0,
}

SYMBOL_TO_SECTOR = {
    "SUNPHARMA": "PHARMA",
    "DRREDDY": "PHARMA",
    "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA",
    "TORNTPHARM": "PHARMA",
    "ALKEM": "PHARMA",
    "AUROPHARMA": "PHARMA",
    "ABBOTINDIA": "PHARMA",
    "BIOCON": "PHARMA",
    "HAL": "DEFENCE",
    "BEL": "DEFENCE",
    "BHEL": "DEFENCE",
    "MIDHANI": "DEFENCE",
    "NTPC": "POWER",
    "POWERGRID": "POWER",
    "TATAPOWER": "POWER",
    "ADANIPOWER": "POWER",
    "CESC": "POWER",
    "HINDUNILVR": "FMCG",
    "ITC": "FMCG",
    "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    "DABUR": "FMCG",
    "MARICO": "FMCG",
    "TCS": "IT",
    "INFY": "IT",
    "WIPRO": "IT",
    "HCLTECH": "IT",
    "TECHM": "IT",
    "LTIM": "IT",
    "MPHASIS": "IT",
    "HDFCBANK": "BANK",
    "ICICIBANK": "BANK",
    "SBIN": "BANK",
    "AXISBANK": "BANK",
    "KOTAKBANK": "BANK",
    "BANDHANBNK": "BANK",
    "BAJFINANCE": "FINANCE",
    "BAJAJFINSV": "FINANCE",
    "CHOLAFIN": "FINANCE",
    "MARUTI": "AUTO",
    "TATAMOTORS": "AUTO",
    "BAJAJ-AUTO": "AUTO",
    "EICHERMOT": "AUTO",
    "HEROMOTOCO": "AUTO",
    "TATASTEEL": "METAL",
    "JSWSTEEL": "METAL",
    "HINDALCO": "METAL",
    "VEDL": "METAL",
    "COALINDIA": "METAL",
}


# ═══════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════


def _hma(series, period):
    half = max(1, int(period / 2))
    sqrt_ = max(1, int(np.sqrt(period)))
    wh = series.ewm(span=half, adjust=False).mean()
    wf = series.ewm(span=period, adjust=False).mean()
    return (2 * wh - wf).ewm(span=sqrt_, adjust=False).mean()


# Fixed settings mirror the manual defaults in "Hybrid Hull V17.3 - R2D@":
# Hull 55, HMA 21/51, ATR(14), ATR multiplier 3.5 and KAMA(30).
# These helpers intentionally use weighted moving averages, as Pine's ta.wma
# does.  The older _hma() above remains in place for the legacy score so this
# addition does not silently re-rank the whole scanner.
HYBRID_HULL_LENGTH = 55
HULL_FAST_LENGTH = 21
HULL_SLOW_LENGTH = 51
HULL_ATR_LENGTH = 14
HULL_KAMA_LENGTH = 30
HULL_ATR_MULTIPLIER = 3.5


def _wma(series, period):
    """Pine-compatible weighted moving average (latest bar has most weight)."""
    period = max(1, int(period))
    weights = np.arange(1, period + 1, dtype=float)
    return (
        series.astype(float)
        .rolling(period, min_periods=period)
        .apply(lambda values: float(np.dot(values, weights) / weights.sum()), raw=True)
    )


def _tv_hma(series, period):
    """TradingView ta.hma equivalent used by the supplied Hybrid Hull script."""
    half = max(1, int(period / 2))
    root = max(1, int(np.sqrt(period)))
    return _wma(2 * _wma(series, half) - _wma(series, period), root)


def _hybrid_hull(series, period=HYBRID_HULL_LENGTH):
    """Exact hybridHull expression from the supplied Pine script."""
    base = _wma(series, period)
    return 2 * _wma(base, max(1, int(period / 2))) - _wma(base, period)


def _atr(highs, lows, closes, period=HULL_ATR_LENGTH):
    previous_close = closes.shift(1)
    true_range = pd.concat(
        [
            highs - lows,
            (highs - previous_close).abs(),
            (lows - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # TradingView ta.atr uses Wilder's smoothing.
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _kama(series, length=HULL_KAMA_LENGTH):
    """Kaufman adaptive MA using the same 2 / length slow constant as Pine."""
    values = series.astype(float)
    change = (values - values.shift(length)).abs()
    volatility = values.diff().abs().rolling(length).sum()
    efficiency = (change / volatility.replace(0, np.nan)).fillna(0.0)
    fast = 2.0 / 3.0
    slow = 2.0 / (length + 1.0)
    smoothing = (efficiency * (fast - slow) + slow) ** 2
    out = pd.Series(np.nan, index=values.index, dtype=float)
    if len(values):
        out.iloc[0] = values.iloc[0]
    for i in range(1, len(values)):
        previous = out.iloc[i - 1]
        out.iloc[i] = previous + smoothing.iloc[i] * (values.iloc[i] - previous)
    return out


def _fixed_hybrid_hull_signals(grp):
    """Return the EOD-only, fixed-parameter Hybrid Hull signal set."""
    data = grp.sort_values("date").copy()
    closes = data["close"].astype(float).reset_index(drop=True)
    highs = data.get("high", data["close"]).astype(float).reset_index(drop=True)
    lows = data.get("low", data["close"]).astype(float).reset_index(drop=True)
    hull = _hybrid_hull(closes)
    hma21 = _tv_hma(closes, HULL_FAST_LENGTH)
    hma51 = _tv_hma(closes, HULL_SLOW_LENGTH)
    atr14 = _atr(highs, lows, closes)
    kama30 = _kama(closes)

    def last(series, fallback=0.0):
        value = series.iloc[-1] if len(series) else fallback
        return float(value) if pd.notna(value) else float(fallback)

    close = last(closes)
    hull_now, hull_prev = last(hull, close), last(hull.iloc[:-1], close)
    atr_now = last(atr14, 0.0)
    kama_now, kama_prev = last(kama30, close), last(kama30.iloc[:-1], close)
    distance_atr = (close - hull_now) / atr_now if atr_now > 0 else 0.0
    daily_up = close > hull_now > hull_prev
    hma_aligned = last(hma21, close) > last(hma51, close)
    kama_rising = kama_now > kama_prev and close > hull_now

    # The script's practical EOD read: low impulse + tight band is chop;
    # a tight ATR regime while structure is aligned is a compression setup.
    kama_slope = abs(kama_now - kama_prev) / atr_now if atr_now > 0 else 0.0
    kama_band = ((kama30.rolling(20).max() - kama30.rolling(20).min()) / kama30.replace(0, np.nan)).iloc[-1]
    rotation = abs(distance_atr) < 0.4 and abs(hull_now - hull_prev) < (atr_now * 0.15)
    chop = bool((kama_slope < 0.072 and (pd.notna(kama_band) and kama_band < 0.025)) or rotation)
    atr_contracting = atr14.iloc[-1] < atr14.rolling(20).mean().iloc[-1] if len(atr14) >= 20 else False
    compression = bool(atr_contracting and daily_up and hma_aligned and not chop)

    weekly_data = data[["date", "close"]].copy()
    weekly_data["date"] = pd.to_datetime(weekly_data["date"])
    weekly = weekly_data.set_index("date")["close"].resample("W-FRI").last().dropna()
    weekly21 = _tv_hma(weekly, HULL_FAST_LENGTH)
    weekly51 = _tv_hma(weekly, HULL_SLOW_LENGTH)
    w21, w21_prev = last(weekly21, close), last(weekly21.iloc[:-1], close)
    w51 = last(weekly51, close)
    weekly_bullish = bool(w21 > w51 and w21 >= w21_prev)
    weekly_status = "BULLISH" if weekly_bullish else ("PULLBACK" if w21 > w51 else "NOT_ALIGNED")

    return {
        "hybrid_hull_55": round(hull_now, 2),
        "hma21": round(last(hma21, close), 2),
        "hma51": round(last(hma51, close), 2),
        "atr14": round(atr_now, 2),
        "hybrid_hull_stop": round(hull_now - HULL_ATR_MULTIPLIER * atr_now, 2),
        "kama30": round(kama_now, 2),
        "daily_hull_status": "BULLISH" if daily_up else "NOT_ALIGNED",
        "daily_hma_aligned": bool(hma_aligned),
        "kama_rising": bool(kama_rising),
        "weekly_hull_status": weekly_status,
        "weekly_hma21": round(w21, 2),
        "weekly_hma51": round(w51, 2),
        "hull_distance_atr": round(distance_atr, 2),
        "hull_stretched": bool(distance_atr > 1.5),
        "hull_critical_stretch": bool(distance_atr > 1.8),
        "hull_chop": bool(chop),
        "hull_compression": bool(compression),
    }


def _macd_bullish(closes):
    if len(closes) < 35:
        return False
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    return bool(macd.iloc[-1] > sig.iloc[-1])


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not np.isnan(val) else 50.0


def _obv_trend(closes, volumes, lookback=10):
    if len(closes) < lookback + 1:
        return "flat"
    obv, obv_s = 0.0, [0.0]
    for i in range(1, len(closes)):
        if closes.iloc[i] > closes.iloc[i - 1]:
            obv += volumes.iloc[i]
        elif closes.iloc[i] < closes.iloc[i - 1]:
            obv -= volumes.iloc[i]
        obv_s.append(obv)
    recent = obv_s[-lookback:]
    slope = np.polyfit(range(len(recent)), recent, 1)[0]
    return "rising" if slope > 0 else "falling" if slope < 0 else "flat"


def _acc_days(closes, volumes, vol_ma, lookback=5):
    if len(closes) < lookback + 1:
        return 0
    return sum(
        1 for i in range(-lookback, 0) if closes.iloc[i] > closes.iloc[i - 1] and volumes.iloc[i] > vol_ma.iloc[i] * 0.9
    )


def _dist_days(closes, volumes, vol_ma, lookback=5):
    if len(closes) < lookback + 1:
        return 0
    return sum(
        1 for i in range(-lookback, 0) if closes.iloc[i] < closes.iloc[i - 1] and volumes.iloc[i] > vol_ma.iloc[i] * 0.9
    )


def _del_trend(delivery, lookback=5):
    valid = delivery.dropna()
    if len(valid) < lookback:
        return "flat"
    slope = np.polyfit(range(lookback), valid.iloc[-lookback:].values, 1)[0]
    return "rising" if slope > 0.5 else "falling" if slope < -0.5 else "flat"


def _cross_age(h20, h55):
    if len(h20) < 5 or len(h55) < 5:
        return 999
    if h20.iloc[-1] <= h55.iloc[-1]:
        return -1
    for i in range(1, min(61, len(h20))):
        if len(h20) - (i + 1) < 0:
            break
        if h20.iloc[-(i + 1)] <= h55.iloc[-(i + 1)]:
            return i
    return 999


def _decelerating(hma_s, lookback=5):
    if len(hma_s) < lookback + 2:
        return False
    slopes = [hma_s.iloc[-i] - hma_s.iloc[-(i + 1)] for i in range(1, lookback + 1)]
    return all(s > 0 for s in slopes) and slopes[0] < slopes[-1] * 0.5


def _sector_bias(symbol):
    sym = str(symbol).upper().strip()
    if sym in SYMBOL_TO_SECTOR:
        return SECTOR_BIAS.get(SYMBOL_TO_SECTOR[sym], 0)
    for kw, sec in [
        ("PHARMA", "PHARMA"),
        ("HEALTH", "HEALTHCARE"),
        ("POWER", "POWER"),
        ("DEFENCE", "DEFENCE"),
        ("BANK", "BANK"),
        ("FIN", "FINANCE"),
        ("TECH", "IT"),
        ("STEEL", "METAL"),
        ("METAL", "METAL"),
    ]:
        if kw in sym:
            return SECTOR_BIAS.get(sec, 0)
    return 0


# ═══════════════════════════════════════════════════════════════
# WEEKLY HMA TIER — Two-tier alignment system
# ═══════════════════════════════════════════════════════════════


def get_weekly_tier(symbol: str, price_df: pd.DataFrame) -> int:
    """
    Calculate weekly HMA alignment tier.

    Returns:
      1 = BULLISH  (weekly HMA20 > HMA55, slope up)
      2 = NEUTRAL  (weekly HMA20 > HMA55, slope flat/down — pullback)
      3 = BEARISH  (weekly HMA20 ≤ HMA55 — trend broken, hard remove)
    """
    try:
        grp = price_df[price_df["symbol"] == symbol].copy()
        grp = grp.sort_values("date").set_index("date")

        if len(grp) < 30:
            return WEEKLY_TIER_NEUTRAL

        # Resample daily → weekly (last close of each week)
        weekly = grp["close"].resample("W").last().dropna()

        if len(weekly) < 15:
            return WEEKLY_TIER_NEUTRAL

        w_hma20 = _hma(weekly, 20)

        # If not enough bars for HMA55, use HMA20 slope only
        if len(weekly) < 55:
            if pd.isna(w_hma20.iloc[-1]):
                return WEEKLY_TIER_NEUTRAL
            w20_now = float(w_hma20.iloc[-1])
            w20_prev = float(w_hma20.iloc[-2]) if len(w_hma20) >= 2 else w20_now
            return WEEKLY_TIER_BULLISH if w20_now > w20_prev else WEEKLY_TIER_NEUTRAL

        w_hma55 = _hma(weekly, 55)

        if pd.isna(w_hma20.iloc[-1]) or pd.isna(w_hma55.iloc[-1]):
            return WEEKLY_TIER_NEUTRAL

        w20_now = float(w_hma20.iloc[-1])
        w55_now = float(w_hma55.iloc[-1])
        w20_prev = float(w_hma20.iloc[-2]) if len(w_hma20) >= 2 else w20_now

        if w20_now <= w55_now:
            return WEEKLY_TIER_BEARISH  # trend broken

        return (
            WEEKLY_TIER_BULLISH  # trend up and rising
            if w20_now > w20_prev
            else WEEKLY_TIER_NEUTRAL
        )  # trend up but resting

    except Exception:
        return WEEKLY_TIER_NEUTRAL


def get_weekly_tier_label(tier: int) -> str:
    return {
        WEEKLY_TIER_BULLISH: "Weekly ✅ Bullish",
        WEEKLY_TIER_NEUTRAL: "Weekly 🟡 Pullback",
        WEEKLY_TIER_BEARISH: "Weekly ❌ Bearish",
    }.get(tier, "Weekly ?")


def get_weekly_tiers_bulk(symbols: list, price_df: pd.DataFrame) -> dict:
    """Calculate weekly tier for all symbols. Returns {symbol: tier}."""
    return {sym: get_weekly_tier(sym, price_df) for sym in symbols}


# ═══════════════════════════════════════════════════════════════
# PER-STOCK SCORING
# ═══════════════════════════════════════════════════════════════


def _score_single_stock(symbol, grp, w52_map, scan_date, weekly_tier=WEEKLY_TIER_NEUTRAL):
    # Hybrid Hull(55) is nested WMA mathematics and needs a longer warm-up.
    grp = grp.sort_values("date").tail(180)
    if len(grp) < 30:
        return None

    closes = grp["close"].astype(float)
    volumes = grp["volume"].astype(float)
    deliveries = (
        grp["delivery_pct"].astype(float)
        if "delivery_pct" in grp.columns
        else pd.Series([50.0] * len(grp), index=grp.index)
    )

    close_now = float(closes.iloc[-1])
    if close_now <= 0:
        return None

    fixed_hull = _fixed_hybrid_hull_signals(grp)

    hma20 = _hma(closes, 20)
    hma55 = _hma(closes, 55)
    hma55_now = float(hma55.iloc[-1]) if not np.isnan(hma55.iloc[-1]) else close_now
    vol_ma = volumes.rolling(20).mean()

    # 1. HMA Freshness
    ca = _cross_age(hma20, hma55)
    fresh_cross = False
    if ca == -1:
        pts_hma = 0
        hma_up = False
    elif ca <= 10:
        pts_hma = 2
        fresh_cross = True
        hma_up = True
    elif ca <= 20:
        pts_hma = 1
        hma_up = True
    else:
        pts_hma = 0
        hma_up = ca != 999

    # 2. Distance from Mean
    dist_pct = (close_now - hma55_now) / hma55_now * 100 if hma55_now > 0 else 0.0
    overext = dist_pct > 15.0
    if dist_pct < 0:
        pts_dist = 0
    elif dist_pct <= 5.0:
        pts_dist = 2
    elif dist_pct <= 10:
        pts_dist = 1
    elif dist_pct <= 15:
        pts_dist = 0
    else:
        pts_dist = -1

    # 3. Volume Quality
    acc = _acc_days(closes, volumes, vol_ma)
    dist = _dist_days(closes, volumes, vol_ma)
    obv = _obv_trend(closes, volumes)
    delt = _del_trend(deliveries)

    if acc >= 4 and obv == "rising":
        pts_vol = 2
    elif acc >= 3 and obv != "falling":
        pts_vol = 1
    elif dist >= 4 and obv == "falling":
        pts_vol = -1
    elif dist >= 3 or obv == "falling":
        pts_vol = 0
    else:
        pts_vol = 1

    # 4-7. RSI / MACD / Sector / RR
    rsi_val = _rsi(closes)
    pts_rsi = 1 if 40 <= rsi_val <= 65 else 0
    pts_macd = 1 if _macd_bullish(closes) else 0
    sb = _sector_bias(symbol)
    pts_sector = sb
    # The Hybrid Hull script's fixed ATR(14) × 3.5 trail is the primary stop.
    # Fall back to the legacy HMA stop only if the indicator is not warmed up.
    hull_stop = float(fixed_hull.get("hybrid_hull_stop", 0))
    sl_price = hull_stop if 0 < hull_stop < close_now else hma55_now * 0.97
    risk = close_now - sl_price
    sl_pct = abs(close_now - sl_price) / close_now * 100 if close_now > 0 else 99
    pts_rr = 1 if sl_pct <= 7.0 and risk > 0 else 0

    # Penalties
    pen_overext = -1 if overext else 0
    pen_decel = -1 if _decelerating(hma55) else 0

    score = max(
        0, min(10, pts_hma + pts_dist + pts_vol + pts_rsi + pts_macd + pts_sector + pts_rr + pen_overext + pen_decel)
    )

    conviction = TIER_HIGH_CONVICTION if score >= 7 else TIER_WATCHLIST if score >= 4 else ""

    w52_high = w52_map.get(symbol, (None, None))
    if isinstance(w52_high, tuple):
        w52_high = w52_high[0]
    near_52w = w52_high is not None and w52_high > 0 and close_now >= 0.90 * float(w52_high)

    return {
        "symbol": symbol,
        "score": score,
        "conviction": conviction,
        "pts_hma": pts_hma,
        "pts_dist": pts_dist,
        "pts_vol": pts_vol,
        "pts_rsi": pts_rsi,
        "pts_macd": pts_macd,
        "pts_sector": pts_sector,
        "pts_rr": pts_rr,
        "pen_overext": pen_overext,
        "pen_decel": pen_decel,
        "cross_age": ca,
        "fresh_cross": fresh_cross,
        "dist_pct": round(dist_pct, 1),
        "overextended": overext,
        "rsi": round(rsi_val, 1),
        "obv_dir": obv,
        "acc_days": acc,
        "dist_days": dist,
        "del_trend": delt,
        "hma_trend_up": hma_up,
        "near_52w": near_52w,
        "sector_bias": sb,
        "weekly_tier": weekly_tier,
        "weekly_label": get_weekly_tier_label(weekly_tier),
        **fixed_hull,
        "stop": round(sl_price, 2),
        "target": round(close_now + risk, 2),
        "target2": round(close_now + 2 * risk, 2),
        "rr": 2.0,
    }


# ═══════════════════════════════════════════════════════════════
# BULK SCORER
# ═══════════════════════════════════════════════════════════════


def score_all_stocks(price_df, filtered_symbols, scan_date, w52_map=None):
    if w52_map is None:
        w52_map = {}

    sym_set = {str(s).strip() for s in filtered_symbols}

    print(f"\n  Calculating weekly HMA alignment for {len(sym_set)} stocks...")
    weekly_tiers = get_weekly_tiers_bulk(list(sym_set), price_df)

    tier1 = [s for s, t in weekly_tiers.items() if t == WEEKLY_TIER_BULLISH]
    tier2 = [s for s, t in weekly_tiers.items() if t == WEEKLY_TIER_NEUTRAL]
    tier3 = [s for s, t in weekly_tiers.items() if t == WEEKLY_TIER_BEARISH]

    print(f"  Weekly Tier 1 (Bullish):  {len(tier1)} ✅ PRIME eligible")
    print(f"  Weekly Tier 2 (Pullback): {len(tier2)} 🟡 WATCH max")
    print(f"  Weekly Tier 3 (Bearish):  {len(tier3)} ❌ removed")

    eligible = set(tier1 + tier2)
    results = []

    for symbol, grp in price_df.groupby("symbol"):
        sym = str(symbol).strip()
        if sym not in eligible:
            continue
        try:
            r = _score_single_stock(sym, grp.copy(), w52_map, scan_date, weekly_tiers.get(sym, 2))
            if r:
                results.append(r)
        except Exception:
            pass

    if not results:
        print("  No stocks scored ≥ 4 after weekly filter.")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df[df["conviction"].isin([TIER_HIGH_CONVICTION, TIER_WATCHLIST])]
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df.index = df.index + 1
    df.index.name = "rank"

    hc = (df["conviction"] == TIER_HIGH_CONVICTION).sum()
    wl = (df["conviction"] == TIER_WATCHLIST).sum()
    t1c = (df["weekly_tier"] == WEEKLY_TIER_BULLISH).sum()
    t2c = (df["weekly_tier"] == WEEKLY_TIER_NEUTRAL).sum()

    print(f"\n  Results: HC={hc} WL={wl} | Tier1={t1c}(PRIME ok) Tier2={t2c}(WATCH cap)")
    return df


# ═══════════════════════════════════════════════════════════════
# CATEGORY ASSIGNMENT
# ═══════════════════════════════════════════════════════════════


def assign_categories_bulk(scored_df, returns_df, w52_map=None):
    if w52_map is None:
        w52_map = {}
    categories = {}

    for _, row in scored_df.iterrows():
        sym = row.get("symbol", row.name if hasattr(row, "name") else "")
        if not sym:
            sym = row.name

        score = float(row.get("score", 0))
        fresh_cross = bool(row.get("fresh_cross", False))
        cross_age = int(row.get("cross_age", 999))
        dist_pct = float(row.get("dist_pct", 0))
        overext = bool(row.get("overextended", False))
        acc_days = int(row.get("acc_days", 0))
        near_52w = bool(row.get("near_52w", False))
        delivery = float(row.get("delivery_pct", 0))
        r1m = float(row.get("return_1m_pct", row.get("return_1m", 0)))
        r3m = float(row.get("return_3m_pct", row.get("return_3m", 0)))
        if abs(r1m) < 1 and r1m != 0:
            r1m *= 100
        if abs(r3m) < 1 and r3m != 0:
            r3m *= 100

        if fresh_cross and not overext and dist_pct <= 10 and acc_days >= 3 and score >= 6:
            categories[sym] = "uptrend"
        elif near_52w and score >= 5:
            categories[sym] = "peak"
        elif delivery >= 55 and dist_pct <= 8 and score >= 5 and not overext:
            categories[sym] = "safer"
        elif r3m > 0 and r1m < r3m * 0.5 and cross_age <= 15:
            categories[sym] = "recovering"
        else:
            categories[sym] = "rising"

    return pd.Series(scored_df.index.map(lambda s: categories.get(s, "rising")), index=scored_df.index)


# ═══════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ═══════════════════════════════════════════════════════════════


def get_caution_flags(stock):
    flags = []
    if float(stock.get("score", 10)) <= 4:
        flags.append(f"Low score {stock.get('score', 0)}/10")
    if float(stock.get("delivery_pct", 100)) < 40:
        flags.append(f"Low delivery {stock.get('delivery_pct', 0):.0f}%")
    if float(stock.get("return_3m_pct", 0)) > 40:
        flags.append(f"Overextended ({stock.get('return_3m_pct', 0):.0f}%)")
    if float(stock.get("dist_pct", 0)) > 15:
        flags.append(f"{stock.get('dist_pct', 0):.0f}% above HMA55")
    if int(stock.get("cross_age", 0)) > 30:
        flags.append(f"Cross {stock.get('cross_age', 0)}d ago — mature")
    if int(stock.get("weekly_tier", 2)) == WEEKLY_TIER_NEUTRAL:
        flags.append("Weekly pulling back — not prime timing")
    return flags


def format_score_breakdown(stock):
    parts = []
    ca = int(stock.get("cross_age", 999))
    dist = float(stock.get("dist_pct", 0))
    w_tier = int(stock.get("weekly_tier", WEEKLY_TIER_NEUTRAL))

    parts.append(f"HMA{'✅' if stock.get('pts_hma', 0) == 2 else '🟡' if stock.get('pts_hma', 0) == 1 else '❌'}{ca}d")
    parts.append(
        f"Rm{'✅' if stock.get('pts_dist', 0) >= 1 else '⚠️' if stock.get('pts_dist', 0) == 0 else '❌'}{dist:.0f}%"
    )
    parts.append(f"Vol{'✅' if stock.get('pts_vol', 0) >= 2 else '🟡' if stock.get('pts_vol', 0) == 1 else '❌'}")
    parts.append(f"RSI{'✅' if stock.get('pts_rsi', 0) else '❌'}")
    parts.append(f"MACD{'✅' if stock.get('pts_macd', 0) else '❌'}")
    parts.append("W✅" if w_tier == WEEKLY_TIER_BULLISH else "W🟡" if w_tier == WEEKLY_TIER_NEUTRAL else "W❌")
    return " | ".join(parts)

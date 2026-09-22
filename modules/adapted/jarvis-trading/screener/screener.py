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


"""
AXIOM Stock Screener — NSE Universe
Scoring weights per config.py (NSE Scanner engine):
  Price Action   : 30%
  Trend Strength : 25%
  Relative Strength : 20%
  Momentum       : 15%
  Volume         : 10%
  Total          : 100 pts
"""

from typing import Any

import pandas as pd
import yfinance as yf
from data.fetcher import fetch_symbols_history, load_universe
from loguru import logger
from utils.indicators import adx_full, atr, bollinger_bands, ema, macd, rsi

from config import (
    ADX_PERIOD,
    ATR_PERIOD,
    BB_PERIOD,
    BB_STD_DEV,
    BREAKOUT_LOOKBACK,
    EMA_PERIODS,
    EMA_SLOPE_BARS,
    GRADE_A_MIN,
    GRADE_B_MIN,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    MAX_ATR_PCT,
    MIN_ADX,
    MIN_ATR_PCT,
    MIN_PRICE,
    RSI_PERIOD,
    SCORE_WEIGHTS,
    VOLUME_SMA_PERIOD,
)

MAX_PRICE = 100_000.0


# ─────────────────────────────────────────────────────────────────
# BENCHMARK FETCH (Nifty 50)
# ─────────────────────────────────────────────────────────────────


def _fetch_nifty_benchmark(period: str = "6mo") -> pd.Series:
    """Fetch Nifty 50 closing prices for RS calculation (OHLCV cache first)."""
    try:
        from data.ohlcv_cache import get_cached_ohlcv

        cached = get_cached_ohlcv("^NSEI")
        if cached is not None and not cached.empty:
            return cached["close"].dropna()
    except Exception:
        pass
    try:
        df = yf.Ticker("^NSEI").history(period=period, interval="1d")
        df.columns = [c.lower() for c in df.columns]
        closes = df["close"].dropna()
        closes.index = closes.index.tz_localize(None) if closes.index.tzinfo else closes.index
        return closes
    except Exception as exc:
        logger.warning("Could not fetch Nifty benchmark: {}", exc)
        return pd.Series(dtype=float)


# ─────────────────────────────────────────────────────────────────
# SCORING COMPONENTS — NSE Scanner engine (each 0–100 raw)
# ─────────────────────────────────────────────────────────────────


def _price_action_score(history: pd.DataFrame, latest: pd.Series) -> tuple[float, list[str]]:
    """
    Price Action Score — 0 to 100 raw (weight: 30%)
      EMA stack aligned (9>21>50)    : 30 pts
      Near 52W high (>=95%)          : 20 pts
      BB position (close > BB mid)   : 15 pts
      Range breakout (close > 20D high) : 20 pts
      Candle body strength (>=50%)   : 15 pts
    """
    score = 0.0
    notes: list[str] = []

    # EMA stack
    if latest["ema9"] > latest["ema21"] > latest["ema50"]:
        score += 30
        notes.append("EMA stack aligned")

    # Near 52-week high
    high_52 = history["close"].rolling(window=252, min_periods=20).max().iloc[-1]
    if pd.notna(high_52) and high_52 > 0 and latest["close"] >= 0.95 * high_52:
        score += 20
        notes.append("Near 52W high")

    # BB position
    if pd.notna(latest["bb_middle"]) and latest["close"] > latest["bb_middle"]:
        score += 15
        notes.append("Above BB mid")

    # Range breakout
    lookback_high = (
        history["close"].iloc[-(BREAKOUT_LOOKBACK + 1) : -1].max() if len(history) > BREAKOUT_LOOKBACK else 0
    )
    if lookback_high > 0 and latest["close"] > lookback_high:
        score += 20
        notes.append(f"Breakout {BREAKOUT_LOOKBACK}D high")

    # Candle body strength
    candle_range = latest["high"] - latest["low"]
    if candle_range > 0:
        body = abs(latest["close"] - latest["open"]) if "open" in latest.index else 0
        if body / candle_range >= 0.50:
            score += 15
            notes.append("Strong body")

    return score, notes


def _trend_strength_score(latest: pd.Series, history: pd.DataFrame) -> tuple[float, list[str]]:
    """
    Trend Strength Score — 0 to 100 raw (weight: 25%)
      ADX level (>=25=40, >=18=20, else 0) : 40 pts
      DI+ > DI-                            : 20 pts
      EMA21 slope positive (5-bar delta)   : 40 pts
    """
    score = 0.0
    notes: list[str] = []

    # ADX level
    adx_val = latest["adx_val"]
    if pd.notna(adx_val):
        if adx_val >= 25:
            score += 40
            notes.append(f"ADX {adx_val:.0f} strong")
        elif adx_val >= MIN_ADX:
            score += 20
            notes.append(f"ADX {adx_val:.0f}")

    # DI alignment
    if pd.notna(latest["di_plus"]) and pd.notna(latest["di_minus"]):
        if latest["di_plus"] > latest["di_minus"]:
            score += 20
            notes.append("DI+ bullish")

    # EMA21 slope (5-bar delta as % of price)
    ema21_slope = latest.get("ema21_slope", None)
    if ema21_slope is not None and pd.notna(ema21_slope) and ema21_slope > 0:
        score += 40
        notes.append(f"EMA21 slope +{ema21_slope:.2f}%")

    return score, notes


def _relative_strength_score(
    history: pd.DataFrame,
    benchmark: pd.Series,
) -> tuple[float, list[str], float, float]:
    """
    Relative Strength Score — 0 to 100 raw (weight: 20%)
      RS 20D vs Nifty > 0  : 50 pts
      RS 60D vs Nifty > 0  : 50 pts

    Returns: (score, notes, rs_20d, rs_60d)
    """
    score = 0.0
    notes: list[str] = []
    rs_20d = 0.0
    rs_60d = 0.0

    if benchmark.empty or len(history) < 61:
        notes.append("RS: insufficient data")
        return score, notes, rs_20d, rs_60d

    stock_closes = history["close"].dropna()
    stock_closes.index = pd.to_datetime(stock_closes.index).tz_localize(None)
    bench = benchmark.copy()
    bench.index = pd.to_datetime(bench.index).tz_localize(None)

    common = stock_closes.index.intersection(bench.index)
    if len(common) < 61:
        notes.append("RS: insufficient common dates")
        return score, notes, rs_20d, rs_60d

    s = stock_closes.reindex(common)
    b = bench.reindex(common)

    if len(s) >= 21:
        stock_ret_20 = (s.iloc[-1] / s.iloc[-21] - 1) * 100
        bench_ret_20 = (b.iloc[-1] / b.iloc[-21] - 1) * 100
        rs_20d = round(stock_ret_20 - bench_ret_20, 2)
        if rs_20d > 0:
            score += 50
            notes.append(f"RS 20D: +{rs_20d:.1f}%")

    if len(s) >= 61:
        stock_ret_60 = (s.iloc[-1] / s.iloc[-61] - 1) * 100
        bench_ret_60 = (b.iloc[-1] / b.iloc[-61] - 1) * 100
        rs_60d = round(stock_ret_60 - bench_ret_60, 2)
        if rs_60d > 0:
            score += 50
            notes.append(f"RS 60D: +{rs_60d:.1f}%")

    return score, notes, rs_20d, rs_60d


def _momentum_score(latest: pd.Series) -> tuple[float, list[str]]:
    """
    Momentum Score — 0 to 100 raw (weight: 15%)
      RSI in 55–70 sweet spot     : 50 pts
      MACD histogram positive     : 30 pts
      MACD line > signal line     : 20 pts
    """
    score = 0.0
    notes: list[str] = []

    rsi_val = latest.get("rsi_val")
    if pd.notna(rsi_val) and 55 <= rsi_val <= 70:
        score += 50
        notes.append(f"RSI {rsi_val:.0f}")

    macd_hist = latest.get("macd_hist")
    if pd.notna(macd_hist) and macd_hist > 0:
        score += 30
        notes.append("MACD hist +")

    macd_line = latest.get("macd_line")
    macd_sig = latest.get("macd_signal")
    if pd.notna(macd_line) and pd.notna(macd_sig) and macd_line > macd_sig:
        score += 20
        notes.append("MACD bullish")

    return score, notes


def _volume_quality_score(latest: pd.Series) -> tuple[float, list[str]]:
    """
    Volume Quality Score — 0 to 100 raw (weight: 10%)
      Ratio vs 20D SMA scaled linearly:
        >= 3.0x → 100 pts
        >= 2.0x → 80 pts
        >= 1.5x → 60 pts
        >= 1.0x → 30 pts
        < 1.0x  → 0 pts
    """
    score = 0.0
    notes: list[str] = []

    if pd.isna(latest.get("volume_sma")) or latest["volume_sma"] == 0:
        return score, notes

    ratio = latest["volume"] / latest["volume_sma"]
    if ratio >= 3.0:
        score = 100
        notes.append(f"Vol surge {ratio:.1f}x")
    elif ratio >= 2.0:
        score = 80
        notes.append(f"Vol strong {ratio:.1f}x")
    elif ratio >= 1.5:
        score = 60
        notes.append(f"Vol confirm {ratio:.1f}x")
    elif ratio >= 1.0:
        score = 30
        notes.append(f"Vol avg {ratio:.1f}x")

    return score, notes


def _detect_setup_flags(history: pd.DataFrame, latest: pd.Series) -> list[str]:
    """Detect categorical setup flags: BREAKOUT, BB_SQUEEZE_SETUP, MOMENTUM_CONT."""
    flags: list[str] = []

    # BREAKOUT: close > 20D high + vol surge + ADX >= 20
    lookback_high = (
        history["close"].iloc[-(BREAKOUT_LOOKBACK + 1) : -1].max() if len(history) > BREAKOUT_LOOKBACK else 0
    )
    vol_ratio = (
        latest["volume"] / latest["volume_sma"]
        if pd.notna(latest.get("volume_sma")) and latest["volume_sma"] > 0
        else 0
    )
    if lookback_high > 0 and latest["close"] > lookback_high and vol_ratio >= 1.5 and latest["adx_val"] >= 20:
        flags.append("BREAKOUT")

    # BB_SQUEEZE_SETUP: BB width < 4% of price AND RSI > 50
    if pd.notna(latest.get("bb_upper")) and pd.notna(latest.get("bb_lower")) and latest["close"] > 0:
        bb_width_pct = (latest["bb_upper"] - latest["bb_lower"]) / latest["close"] * 100
        if bb_width_pct < 4.0 and pd.notna(latest.get("rsi_val")) and latest["rsi_val"] > 50:
            flags.append("BB_SQUEEZE_SETUP")

    # MOMENTUM_CONT: EMA aligned + MACD bullish + RSI 50-75
    ema_aligned = latest["ema9"] > latest["ema21"] > latest["ema50"]
    macd_bull = (
        pd.notna(latest.get("macd_hist"))
        and latest["macd_hist"] > 0
        and pd.notna(latest.get("macd_line"))
        and pd.notna(latest.get("macd_signal"))
        and latest["macd_line"] > latest["macd_signal"]
    )
    rsi_ok = pd.notna(latest.get("rsi_val")) and 50 <= latest["rsi_val"] <= 75
    if ema_aligned and macd_bull and rsi_ok:
        flags.append("MOMENTUM_CONT")

    return flags


# ─────────────────────────────────────────────────────────────────
# MAIN SYMBOL SCORER
# ─────────────────────────────────────────────────────────────────


def score_symbol(
    history: pd.DataFrame,
    symbol: str,
    benchmark: pd.Series,
) -> dict[str, Any]:
    """Score a single symbol across all 5 dimensions using NSE Scanner engine."""
    if history.empty:
        msg = "History data is empty"
        raise ValueError(msg)

    history = history.copy()
    history.columns = [c.lower() for c in history.columns]
    history = history.dropna(subset=["close", "high", "low", "volume"])

    if len(history) < 40:
        msg = f"Not enough data for symbol {symbol}"
        raise ValueError(msg)

    # Compute all indicators
    bb = bollinger_bands(history["close"], BB_PERIOD, BB_STD_DEV)
    macd_df = macd(history["close"], MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    adx_df = adx_full(history, ADX_PERIOD)
    ema21_series = ema(history["close"], EMA_PERIODS[1])
    ema21_slope_raw = ema21_series.diff(EMA_SLOPE_BARS)

    history = history.assign(
        ema9=ema(history["close"], EMA_PERIODS[0]),
        ema21=ema21_series,
        ema50=ema(history["close"], EMA_PERIODS[2]),
        ema200=ema(history["close"], EMA_PERIODS[3]),
        ema21_slope=(ema21_slope_raw / history["close"] * 100),
        atr_val=atr(history, ATR_PERIOD),
        rsi_val=rsi(history["close"], RSI_PERIOD),
        adx_val=adx_df["adx"],
        di_plus=adx_df["di_plus"],
        di_minus=adx_df["di_minus"],
        bb_upper=bb["bb_upper"],
        bb_middle=bb["bb_middle"],
        bb_lower=bb["bb_lower"],
        macd_line=macd_df["macd"],
        macd_signal=macd_df["signal"],
        macd_hist=macd_df["histogram"],
        volume_sma=history["volume"].rolling(window=VOLUME_SMA_PERIOD, min_periods=VOLUME_SMA_PERIOD).mean(),
    )

    latest = history.iloc[-1]

    # Hard filters
    atr_pct = latest["atr_val"] / latest["close"] if latest["close"] > 0 else 0
    if latest["close"] < MIN_PRICE or latest["close"] > MAX_PRICE:
        msg = f"Price filter failed: {latest['close']:.2f}"
        raise ValueError(msg)
    if atr_pct < MIN_ATR_PCT or atr_pct > MAX_ATR_PCT:
        msg = f"ATR filter failed: {atr_pct:.4f}"
        raise ValueError(msg)

    # Score each dimension (raw 0–100)
    pa_raw, pa_notes = _price_action_score(history, latest)
    tr_raw, tr_notes = _trend_strength_score(latest, history)
    rs_raw, rs_notes, rs_20d, rs_60d = _relative_strength_score(history, benchmark)
    mom_raw, mom_notes = _momentum_score(latest)
    vol_raw, vol_notes = _volume_quality_score(latest)

    # Weighted composite (each raw score × weight)
    w = SCORE_WEIGHTS
    total = (
        pa_raw * w["price_action"]
        + tr_raw * w["trend_strength"]
        + rs_raw * w["rel_strength"]
        + mom_raw * w["momentum"]
        + vol_raw * w["volume"]
    )

    setup_flags = _detect_setup_flags(history, latest)
    all_notes = pa_notes + tr_notes + rs_notes + mom_notes + vol_notes
    vol_ratio = (
        round(latest["volume"] / latest["volume_sma"], 2)
        if pd.notna(latest.get("volume_sma")) and latest["volume_sma"] > 0
        else 0.0
    )

    grade = "A" if total >= GRADE_A_MIN else ("B" if total >= GRADE_B_MIN else "C")

    return {
        "symbol": symbol,
        "close": round(float(latest["close"]), 2),
        "volume": int(latest["volume"]),
        "volume_ratio": vol_ratio,
        "score": round(float(total), 1),
        "grade": grade,
        "pa_score": round(pa_raw, 1),
        "trend_score": round(tr_raw, 1),
        "rs_score": round(rs_raw, 1),
        "momentum_score": round(mom_raw, 1),
        "vol_score": round(vol_raw, 1),
        "rs_20d": rs_20d,
        "rs_60d": rs_60d,
        "rsi": round(float(latest["rsi_val"]), 1) if pd.notna(latest.get("rsi_val")) else None,
        "adx": round(float(latest["adx_val"]), 1) if pd.notna(latest.get("adx_val")) else None,
        "di_plus": round(float(latest["di_plus"]), 1) if pd.notna(latest.get("di_plus")) else None,
        "di_minus": round(float(latest["di_minus"]), 1) if pd.notna(latest.get("di_minus")) else None,
        "atr_pct": round(float(atr_pct) * 100, 2),
        "ema9": round(float(latest["ema9"]), 2),
        "ema21": round(float(latest["ema21"]), 2),
        "ema50": round(float(latest["ema50"]), 2),
        "ema200": round(float(latest["ema200"]), 2),
        "macd_hist": round(float(latest["macd_hist"]), 3) if pd.notna(latest.get("macd_hist")) else None,
        "setup_flags": "; ".join(setup_flags) if setup_flags else "",
        "notes": "; ".join(all_notes),
    }


# ─────────────────────────────────────────────────────────────────
# SCREENER RUNNER
# ─────────────────────────────────────────────────────────────────


def run_screener(symbols: list[str] | None = None) -> pd.DataFrame:
    """
    Run the full AXIOM screener pipeline.
    Fetches Nifty benchmark once, scores every symbol, returns ranked DataFrame.
    """
    if symbols is None:
        universe = load_universe()
        symbols = universe["symbol"].tolist()
    symbols = list(dict.fromkeys(symbols))  # dedupe, keep order
    if not symbols:
        msg = "No symbols provided for screener"
        raise ValueError(msg)

    logger.info("Fetching Nifty 50 benchmark for RS calculation...")
    benchmark = _fetch_nifty_benchmark(period="6mo")
    if benchmark.empty:
        logger.warning("Benchmark unavailable — RS scores will be 0")

    logger.info("Fetching history for {} symbols...", len(symbols))
    histories = fetch_symbols_history(symbols, period="6mo", interval="1d")

    results: list[dict[str, Any]] = []
    skipped = 0
    for symbol in symbols:
        history = histories.get(symbol)
        if history is None:
            skipped += 1
            continue
        try:
            row = score_symbol(history, symbol, benchmark)
            try:
                from screener.ta_engine import mtf_confluence

                m = mtf_confluence(history)
                row["mtf"] = m["score"]
                row["mtf_of"] = m["of"]
            except Exception:
                pass
            results.append(row)
        except Exception as exc:
            logger.debug("Skipped {}: {}", symbol, exc)
            skipped += 1

    logger.info("Scored {} symbols, skipped {}", len(results), skipped)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    return df

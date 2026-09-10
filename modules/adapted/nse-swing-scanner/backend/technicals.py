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
technicals.py
Computes all price/volume-based criteria from yfinance OHLCV data, plus
ATR(14)-based entry/target/stop and a relative-strength-vs-Nifty-50 adjustment.

Verified live against RELIANCE.NS: yfinance returns ~250 trading days for period="1y",
sufficient for 200-day EMA, 14-day RSI, and 30-day volume averages.

Confidence: high on the math (standard, well-known formulas). Moderate on yfinance
data quality for thinly-traded mid/small caps in the Nifty 500 tail — spot-check any
name you're about to act on against a second source (e.g. NSE's own daily bhavcopy)
before sizing a real position.

ATR / target / stop: heuristic only. Not backtested. Documented in methodology.md.
"""

from typing import Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from cache import cached_call
from settings import (
    ADV_LOOKBACK_SESSIONS,
    ADV_MIN_SESSIONS,
    ATR_PERIOD,
    ENTRY_ZONE_ATR_FRACTION,
    STOP_LOSS_ATR_MULT,
    TARGET_1_ATR_MULT,
    TARGET_2_ATR_MULT,
    YF_CACHE_TTL_SECONDS,
)
from yf_retry import call_with_retry, is_rate_limit_error, should_cache_yf_payload

NIFTY50_TICKER = "^NSEI"  # Nifty 50 index on yfinance


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Standard Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _compute_technicals_impl(yf_ticker: str, period: str = "1y") -> dict:
    """Implementation behind the cached_call wrapper. See compute_technicals."""
    try:

        def _hist():
            return yf.Ticker(yf_ticker).history(period=period, auto_adjust=True)

        hist = call_with_retry(
            _hist,
            max_attempts=4,
            base_delay_s=3.0,
            is_retryable=is_rate_limit_error,
            # yfinance sometimes returns empty instead of raising on throttle.
            retryable_result=lambda h: h is None or getattr(h, "empty", True),
        )
    except Exception as e:
        return {"yf_ticker": yf_ticker, "error": f"fetch_failed: {e}"}

    if hist is None or hist.empty or len(hist) < 210:
        n_bars = 0 if hist is None or getattr(hist, "empty", True) else len(hist)
        # Empty after retries is often a soft rate-limit; tag it so coverage
        # accounting and the recovery pass can re-attempt later.
        if n_bars == 0:
            return {
                "yf_ticker": yf_ticker,
                "error": "fetch_failed: Too Many Requests. Rate limited. (empty history after retries)",
            }
        return {"yf_ticker": yf_ticker, "error": f"insufficient_history ({n_bars} bars)"}

    # yfinance sometimes returns the most recent session with all-NaN OHLCV
    # (incomplete feed, e.g. intraday session still settling). Drop trailing
    # rows where Close is NaN so "current" refers to the last complete session.
    valid_close = hist["Close"].dropna()
    if len(valid_close) < 210:
        return {"yf_ticker": yf_ticker, "error": f"insufficient_valid_history ({len(valid_close)} non-NaN bars)"}

    # Truncate hist to the last valid bar so all downstream series agree.
    last_valid_idx = valid_close.index[-1]
    hist = hist.loc[:last_valid_idx]

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    current_price = float(close.iloc[-1])
    fifty_two_wk_high = float(close.rolling(252, min_periods=100).max().iloc[-1])
    pct_off_high = (current_price / fifty_two_wk_high - 1) * 100  # negative number

    ema200 = close.ewm(span=200, adjust=False).mean()
    current_ema200 = float(ema200.iloc[-1])
    pct_from_ema200 = (current_price / current_ema200 - 1) * 100

    rsi_series = compute_rsi(close, 14)
    current_rsi = float(rsi_series.iloc[-1])

    atr_series = compute_atr(high, low, close, ATR_PERIOD)
    current_atr = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else None

    # Volume surge
    avg_vol_30 = float(volume.rolling(30, min_periods=20).mean().iloc[-1])
    recent = hist.tail(10).copy()
    recent["is_down"] = recent["Close"] < recent["Open"]
    down_days = recent[recent["is_down"]]
    peak_down_volume = float(down_days["Volume"].max()) if not down_days.empty else float(recent["Volume"].max())
    volume_surge_factor = peak_down_volume / avg_vol_30 if avg_vol_30 > 0 else np.nan

    # Approximate traded-value proxy (NOT delivery value; delivery comes from bhavcopy)
    adtv_value_inr = avg_vol_30 * current_price

    # True 20-session ADV: mean of (volume_i * close_i) over the last N valid sessions.
    # Used by the liquidity hard gate so we gate on real exitability, not a single-day
    # volume×close proxy for delivery. Take the trailing window FIRST, then drop
    # NaN rows inside it, so adv_sessions reflects how many bars actually contributed.
    adv_window = hist[["Volume", "Close"]].tail(ADV_LOOKBACK_SESSIONS).dropna()
    adv_sessions = len(adv_window)
    if adv_sessions >= ADV_MIN_SESSIONS:
        adv_value_inr = float((adv_window["Volume"] * adv_window["Close"]).mean())
    else:
        adv_value_inr = None

    # ATR-based entry zone / stop / targets
    entry_low = current_price - ENTRY_ZONE_ATR_FRACTION * (current_atr or 0)
    entry_high = current_price
    entry_mid = (entry_low + entry_high) / 2
    stop_loss = entry_mid - STOP_LOSS_ATR_MULT * (current_atr or 0) if current_atr else None
    target_1 = entry_mid + TARGET_1_ATR_MULT * (current_atr or 0) if current_atr else None
    target_2 = entry_mid + TARGET_2_ATR_MULT * (current_atr or 0) if current_atr else None
    rr1 = (
        ((target_1 - entry_mid) / (entry_mid - stop_loss))
        if (target_1 and stop_loss and entry_mid > stop_loss)
        else None
    )
    rr2 = (
        ((target_2 - entry_mid) / (entry_mid - stop_loss))
        if (target_2 and stop_loss and entry_mid > stop_loss)
        else None
    )

    # --- 1.3.0 accuracy plumbing: confirmation + exit-warning features ---
    # Confirmation overlay (A/B-able label, NOT a gate): is there early
    # stabilization evidence, or is this still a falling knife? Persist the
    # raw features alongside the composite state so cohort analysis can
    # re-cut later without re-fetching.
    rsi_series_full = compute_rsi(close, 14)
    confirmation_state = "anticipatory"
    rsi_delta_3d = None
    close_up_1d = None
    vol_ratio_3v20 = None
    if len(rsi_series_full) >= 4 and not np.isnan(rsi_series_full.iloc[-1]):
        rsi_now = float(rsi_series_full.iloc[-1])
        rsi_3d_ago = float(rsi_series_full.iloc[-4]) if len(rsi_series_full) >= 4 else np.nan
        if not np.isnan(rsi_3d_ago):
            rsi_delta_3d = round(rsi_now - rsi_3d_ago, 2)
    if len(close) >= 2:
        close_up_1d = bool(close.iloc[-1] > close.iloc[-2])
    if len(volume) >= 20:
        recent_vol = float(volume.iloc[-3:].mean())
        base_vol = float(volume.iloc[-20:].mean())
        if base_vol > 0:
            vol_ratio_3v20 = round(recent_vol / base_vol, 2)
    # Confirmed = RSI turning up over 3 sessions AND last close > prior close.
    # Both conditions must hold; everything else is anticipatory. This is a
    # deliberately strict definition so the "confirmed" cohort stays clean.
    if rsi_delta_3d is not None and rsi_delta_3d > 0 and close_up_1d:
        confirmation_state = "confirmed"

    # Exit-side warning #1: nearby swing high capping T1.
    # 63 sessions ≈ 3 trading months. If a recent swing high sits between
    # entry and T1, the measured-move target is structurally optimistic.
    swing_high_63d = None
    if len(high) >= 21:
        swing_high_63d = float(high.rolling(63, min_periods=21).max().iloc[-1])

    # Exit-side warning #2: ATR expanding (stop too tight).
    # Ratio of current ATR to ATR 20 sessions ago. >1.3 = volatility
    # expanding, so the 1.0xATR stop is likely to be clipped.
    atr_expansion_ratio = None
    if current_atr and len(atr_series) >= 21:
        atr_20d_ago = atr_series.iloc[-21]
        if not np.isnan(atr_20d_ago) and atr_20d_ago > 0:
            atr_expansion_ratio = round(float(current_atr) / float(atr_20d_ago), 2)

    return {
        "yf_ticker": yf_ticker,
        "current_price": round(current_price, 2),
        "fifty_two_wk_high": round(fifty_two_wk_high, 2),
        "pct_off_52wk_high": round(pct_off_high, 2),
        "ema200": round(current_ema200, 2),
        "pct_from_ema200": round(pct_from_ema200, 2),
        "rsi14": round(current_rsi, 2),
        "atr14": round(current_atr, 2) if current_atr is not None else None,
        "entry_zone_low": round(entry_low, 2) if current_atr else None,
        "entry_zone_high": round(entry_high, 2),
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
        "target_1": round(target_1, 2) if target_1 else None,
        "target_2": round(target_2, 2) if target_2 else None,
        "risk_reward_target_1": round(rr1, 2) if rr1 else None,
        "risk_reward_target_2": round(rr2, 2) if rr2 else None,
        "avg_vol_30d": round(avg_vol_30, 0),
        "peak_down_day_volume_10d": round(peak_down_volume, 0),
        "volume_surge_factor": round(volume_surge_factor, 2) if not np.isnan(volume_surge_factor) else None,
        "adtv_value_inr_approx": round(adtv_value_inr, 0),
        "adv_value_inr": round(adv_value_inr, 0) if adv_value_inr is not None else None,
        "adv_sessions": adv_sessions,
        # 1.3.0 accuracy plumbing
        "confirmation_state": confirmation_state,
        "rsi_delta_3d": rsi_delta_3d,
        "close_up_1d": close_up_1d,
        "vol_ratio_3v20": vol_ratio_3v20,
        "swing_high_63d": round(swing_high_63d, 2) if swing_high_63d is not None else None,
        "atr_expansion_ratio": atr_expansion_ratio,
        "error": None,
    }


def compute_technicals(yf_ticker: str, period: str = "1y") -> dict:
    """
    Returns a dict of computed technical fields for one ticker, or a dict with
    'error' set if data was insufficient/unavailable. Results are cached on
    disk for YF_CACHE_TTL_SECONDS (12 h) keyed on (ticker, period, schema).
    Bumping the schema suffix invalidates old cached payloads whose shape would
    otherwise be silently merged with the new field set (causing missing/null
    fields in the JSON contract for one full TTL).
    """
    return cached_call(
        f"tech:{yf_ticker}:{period}:v3",
        YF_CACHE_TTL_SECONDS,
        _compute_technicals_impl,
        yf_ticker,
        period,
        should_cache=should_cache_yf_payload,
    )


def _compute_nifty50_context_impl(period: str = "1y") -> dict:
    """Implementation behind the cached_call wrapper. See compute_nifty50_context."""
    try:

        def _hist():
            return yf.Ticker(NIFTY50_TICKER).history(period=period, auto_adjust=True)

        hist = call_with_retry(
            _hist,
            max_attempts=3,
            base_delay_s=2.0,
            is_retryable=is_rate_limit_error,
        )
    except Exception as e:
        return {"error": f"fetch_failed: {e}"}
    if hist is None or hist.empty or len(hist) < 210:
        return {"error": "insufficient_history"}
    close = hist["Close"].dropna()
    if len(close) < 210:
        return {"error": "insufficient_valid_history"}
    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
    pct_from_ema200 = (float(close.iloc[-1]) / float(ema200) - 1) * 100
    return {
        "index_symbol": "NIFTY50",
        "index_last": round(float(close.iloc[-1]), 2),
        "index_ema200": round(float(ema200), 2),
        "index_pct_from_ema200": round(pct_from_ema200, 2),
        "error": None,
    }


def compute_nifty50_context(period: str = "1y") -> dict:
    """
    Fetch Nifty 50 index data once per scan and return its 200EMA + distance.
    Used for the relative-strength-vs-market adjustment (a soft factor, not a gate).
    Results cached on disk for YF_CACHE_TTL_SECONDS (12 h).
    """
    return cached_call(
        f"tech:{NIFTY50_TICKER}:{period}",
        YF_CACHE_TTL_SECONDS,
        _compute_nifty50_context_impl,
        period,
    )


if __name__ == "__main__":
    for t in ["RELIANCE.NS", "TATAMOTORS.NS", "INFY.NS"]:
        print(compute_technicals(t))
    print(compute_nifty50_context())

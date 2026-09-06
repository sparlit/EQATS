"""
Market regime classifier — BULLISH / NEUTRAL / BEARISH.
Must run before any screener or trade entry decision.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import yfinance as yf
from loguru import logger

from utils.indicators import adx, ema


@dataclass
class RegimeResult:
    regime: str          # BULLISH | NEUTRAL | BEARISH
    nifty_close: float
    ema50: float
    ema200: float
    adx_value: float
    high_52w: float
    low_52w: float
    position_multiplier: float   # 1.0 = full, 0.5 = half, 0.0 = no longs
    min_rr: float                # minimum R:R required
    max_positions: int
    reason: str


def classify_regime() -> RegimeResult:
    """
    Classify current NSE market regime from Nifty 50 data.

    Rules (from CLAUDE.md):
      BULLISH  : price > EMA50, EMA50 > EMA200, ADX > 20, price > 52W_low * 1.03
      NEUTRAL  : price between EMA50/EMA200, OR ADX 15-20
      BEARISH  : price < EMA50 AND EMA50 < EMA200
    """
    try:
        df = yf.Ticker("^NSEI").history(period="1y", interval="1d")
        df.columns = [c.lower() for c in df.columns]
    except Exception as exc:
        logger.error("Failed to fetch Nifty data for regime: {}", exc)
        return _fallback_regime("Data fetch failed")

    if df.empty or len(df) < 50:
        return _fallback_regime("Insufficient Nifty data")

    closes = df["close"].dropna()
    ema50_series = closes.ewm(span=50, adjust=False).mean()
    ema200_series = closes.ewm(span=200, adjust=False).mean()
    adx_series = adx(df)

    price = float(closes.iloc[-1])
    e50 = float(ema50_series.iloc[-1])
    e200 = float(ema200_series.iloc[-1])
    adx_val = float(adx_series.iloc[-1]) if not adx_series.empty else 0.0
    high_52 = float(closes.rolling(252, min_periods=20).max().iloc[-1])
    low_52 = float(closes.rolling(252, min_periods=20).min().iloc[-1])

    above_ema50 = price > e50
    ema_aligned = e50 > e200
    adx_strong = adx_val > 20
    not_near_bottom = price > low_52 * 1.03

    if above_ema50 and ema_aligned and adx_strong and not_near_bottom:
        return RegimeResult(
            regime="BULLISH",
            nifty_close=round(price, 2),
            ema50=round(e50, 2),
            ema200=round(e200, 2),
            adx_value=round(adx_val, 1),
            high_52w=round(high_52, 2),
            low_52w=round(low_52, 2),
            position_multiplier=1.0,
            min_rr=2.0,
            max_positions=2,
            reason="Price > EMA50 > EMA200, ADX strong, not near 52W low",
        )
    elif not above_ema50 and not ema_aligned:
        return RegimeResult(
            regime="BEARISH",
            nifty_close=round(price, 2),
            ema50=round(e50, 2),
            ema200=round(e200, 2),
            adx_value=round(adx_val, 1),
            high_52w=round(high_52, 2),
            low_52w=round(low_52, 2),
            position_multiplier=0.0,
            min_rr=99.0,
            max_positions=0,
            reason="Price < EMA50 and EMA50 < EMA200 — no long entries",
        )
    else:
        return RegimeResult(
            regime="NEUTRAL",
            nifty_close=round(price, 2),
            ema50=round(e50, 2),
            ema200=round(e200, 2),
            adx_value=round(adx_val, 1),
            high_52w=round(high_52, 2),
            low_52w=round(low_52, 2),
            position_multiplier=0.5,
            min_rr=2.5,
            max_positions=1,
            reason="Mixed signals — reduced size, Grade A only",
        )


def _fallback_regime(reason: str) -> RegimeResult:
    logger.warning("Regime defaulting to NEUTRAL: {}", reason)
    return RegimeResult(
        regime="NEUTRAL",
        nifty_close=0.0,
        ema50=0.0,
        ema200=0.0,
        adx_value=0.0,
        high_52w=0.0,
        low_52w=0.0,
        position_multiplier=0.5,
        min_rr=2.5,
        max_positions=1,
        reason=reason,
    )

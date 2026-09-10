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
Market context data fetcher — institutional-grade global & overnight cues.

Pulls a full cross-asset picture for the morning briefing:
  · US close + US futures (overnight direction)
  · Asia-Pacific (live this morning) + Europe (prior close)
  · Rates / bonds (US 10Y, 2Y), Dollar Index
  · Commodities (Brent, WTI, Gold, Silver, Copper, NatGas)
  · Crypto risk proxy (BTC)
  · India: Nifty, Bank Nifty, India VIX + technicals + pivot levels
  · Sector performance + breadth

All data via yfinance (free). FII/DII is NOT reliably available free — it is
returned as None and the AI is instructed not to fabricate it.
"""

import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

from datetime import datetime

import pandas as pd
import yfinance as yf
from data.fii_dii import fetch_fii_dii
from loguru import logger
from utils.indicators import adx_full, rsi
from utils.timez import now_ist

# ── Ticker groups ─────────────────────────────────────────────────
US_MARKETS = {
    "S&P 500": "^GSPC",
    "Dow Jones": "^DJI",
    "Nasdaq": "^IXIC",
    "Russell 2000": "^RUT",
    "VIX": "^VIX",
}
US_FUTURES = {
    "S&P Fut": "ES=F",
    "Nasdaq Fut": "NQ=F",
    "Dow Fut": "YM=F",
}
ASIA_MARKETS = {
    "Nikkei 225": "^N225",
    "Hang Seng": "^HSI",
    "Shanghai": "000001.SS",
    "Kospi": "^KS11",
    "ASX 200": "^AXJO",
    "Taiwan": "^TWII",
}
EUROPE_MARKETS = {
    "FTSE 100": "^FTSE",
    "DAX": "^GDAXI",
    "CAC 40": "^FCHI",
}
RATES_FX = {
    "US 10Y": "^TNX",
    "US 2Y": "^IRX",
    "Dollar Index": "DX-Y.NYB",
    "USD/INR": "USDINR=X",
    "EUR/USD": "EURUSD=X",
}
COMMODITIES = {
    "Brent": "BZ=F",
    "WTI Crude": "CL=F",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Copper": "HG=F",
    "Nat Gas": "NG=F",
}
CRYPTO = {
    "Bitcoin": "BTC-USD",
}
INDIA_INDICES = {
    "Nifty 50": "^NSEI",
    "Bank Nifty": "^NSEBANK",
    "India VIX": "^INDIAVIX",
}

# NSE Sector proxies (single liquid leader per sector)
SECTOR_PROXIES = {
    "IT": "INFY.NS",
    "Banking": "HDFCBANK.NS",
    "Auto": "MARUTI.NS",
    "Pharma": "SUNPHARMA.NS",
    "FMCG": "HINDUNILVR.NS",
    "Metal": "TATASTEEL.NS",
    "Energy": "RELIANCE.NS",
    "Infra": "LT.NS",
    "Realty": "DLF.NS",
    "PSU Bank": "SBIN.NS",
}


def _safe_fetch(ticker: str, period: str = "5d", interval: str = "1d") -> pd.DataFrame:
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval)
        if df.empty:
            return df
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as exc:
        logger.warning("Failed to fetch {}: {}", ticker, exc)
        return pd.DataFrame()


def _batch_fetch(tickers: list[str], period: str = "5d") -> dict[str, pd.DataFrame]:
    """Fetch many tickers in one call; return {ticker: ohlcv_df}."""
    out: dict[str, pd.DataFrame] = {}
    if len(tickers) == 1:
        return {tickers[0]: _safe_fetch(tickers[0], period)}
    try:
        data = yf.download(
            tickers, period=period, interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True
        )
    except Exception as exc:
        logger.warning("Batch download failed ({}); falling back per-ticker", exc)
        return {t: _safe_fetch(t, period) for t in tickers}

    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            df = df.dropna(how="all")
            df.columns = [c.lower() for c in df.columns]
            out[t] = df
        except Exception:
            out[t] = pd.DataFrame()
    return out


def _pct_change(df: pd.DataFrame) -> float:
    if df.empty or len(df) < 2:
        return 0.0
    closes = df["close"].dropna()
    if len(closes) < 2:
        return 0.0
    return float(round((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100, 2))


def _latest_close(df: pd.DataFrame) -> float:
    if df.empty or "close" not in df.columns:
        return 0.0
    closes = df["close"].dropna()
    return float(round(closes.iloc[-1], 2)) if not closes.empty else 0.0


def _quote_group(name_to_ticker: dict[str, str]) -> dict[str, dict]:
    """Return {name: {close, change_pct}} for a group of tickers (batched)."""
    tickers = list(name_to_ticker.values())
    frames = _batch_fetch(tickers)
    result = {}
    for name, ticker in name_to_ticker.items():
        df = frames.get(ticker, pd.DataFrame())
        result[name] = {"close": _latest_close(df), "change_pct": _pct_change(df)}
    return result


def _pivot_levels(df: pd.DataFrame) -> dict[str, float]:
    """Classic floor-trader pivots from the last completed session."""
    if df.empty or len(df) < 1:
        return {}
    last = df.iloc[-1]
    h, l, c = float(last["high"]), float(last["low"]), float(last["close"])
    p = (h + l + c) / 3
    return {
        "pivot": round(p, 2),
        "r1": round(2 * p - l, 2),
        "r2": round(p + (h - l), 2),
        "r3": round(h + 2 * (p - l), 2),
        "s1": round(2 * p - h, 2),
        "s2": round(p - (h - l), 2),
        "s3": round(l - 2 * (h - p), 2),
        "prev_high": round(h, 2),
        "prev_low": round(l, 2),
        "prev_close": round(c, 2),
    }


def fetch_index_technicals(ticker: str) -> dict[str, float]:
    """Full technical read for an index: EMAs, RSI, ADX, 52w range, pivots."""
    df = _safe_fetch(ticker, period="1y", interval="1d")
    if df.empty or len(df) < 50:
        return {}
    closes = df["close"].dropna()
    latest = float(closes.iloc[-1])
    ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1]) if len(closes) >= 200 else 0.0
    rsi_val = float(rsi(closes, 14).iloc[-1])
    try:
        adx_val = float(adx_full(df, 14)["adx"].iloc[-1])
    except Exception:
        adx_val = 0.0
    return {
        "close": round(latest, 2),
        "change_pct": _pct_change(df),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "rsi": round(rsi_val, 1),
        "adx": round(adx_val, 1),
        "high_52w": round(float(closes.rolling(252, min_periods=20).max().iloc[-1]), 2),
        "low_52w": round(float(closes.rolling(252, min_periods=20).min().iloc[-1]), 2),
        "above_ema50": latest > ema50,
        "above_ema200": latest > ema200 if ema200 else None,
        "pivots": _pivot_levels(df),
    }


def fetch_sector_performance() -> dict[str, float]:
    """1-day % change for key NSE sector proxies (batched)."""
    frames = _batch_fetch(list(SECTOR_PROXIES.values()))
    return {sector: _pct_change(frames.get(ticker, pd.DataFrame())) for sector, ticker in SECTOR_PROXIES.items()}


def _gift_nifty() -> dict:
    """
    Best-effort Gift Nifty (NSE IX) read. yfinance has no clean Gift Nifty feed;
    we approximate overnight bias from Nifty futures sentiment + US futures.
    Returns a note so the AI does not present it as a hard quote.
    """
    return {
        "available": False,
        "note": "Gift Nifty live quote not available via free feed — infer pre-open "
        "bias from US futures + Asia + prior Nifty close.",
    }


def build_briefing_context() -> dict:
    """Assemble the full institutional context dict for the morning briefing."""
    logger.info("Building institutional briefing context (cross-asset)...")

    us_close = _quote_group(US_MARKETS)
    us_futures = _quote_group(US_FUTURES)
    asia = _quote_group(ASIA_MARKETS)
    europe = _quote_group(EUROPE_MARKETS)
    rates_fx = _quote_group(RATES_FX)
    commods = _quote_group(COMMODITIES)
    crypto = _quote_group(CRYPTO)
    india = _quote_group(INDIA_INDICES)

    sectors = fetch_sector_performance()
    top_sectors = sorted(sectors.items(), key=lambda x: x[1], reverse=True)[:3]
    weak_sectors = sorted(sectors.items(), key=lambda x: x[1])[:3]

    nifty_tech = fetch_index_technicals("^NSEI")
    banknifty_tech = fetch_index_technicals("^NSEBANK")

    # Risk-sentiment read for the AI
    vix_change = us_close.get("VIX", {}).get("change_pct", 0.0)
    spx_change = us_close.get("S&P 500", {}).get("change_pct", 0.0)
    risk_tone = (
        "RISK-ON"
        if (spx_change > 0 and vix_change < 0)
        else "RISK-OFF"
        if (spx_change < 0 and vix_change > 0)
        else "MIXED"
    )

    return {
        "date": now_ist().strftime("%A, %d %b %Y"),
        "time": now_ist().strftime("%H:%M IST"),
        # ── Global / overnight ──
        "us_markets_close": us_close,
        "us_futures": us_futures,
        "asia_pacific": asia,
        "europe_prev_close": europe,
        "rates_and_fx": rates_fx,
        "commodities": commods,
        "crypto": crypto,
        "global_risk_tone": risk_tone,
        "gift_nifty": _gift_nifty(),
        # ── India ──
        "india_indices": india,
        "nifty": nifty_tech,
        "bank_nifty": banknifty_tech,
        # ── Breadth / rotation ──
        "top_sectors": top_sectors,
        "weak_sectors": weak_sectors,
        "all_sectors": sectors,
        # ── Institutional flows (real, from NSE) ──
        "fii_dii": fetch_fii_dii(),
        # ── Honesty flags ──
        "data_notes": "FII/DII flows are real NSE provisional figures (₹ crore). If "
        "fii_dii.available is False, say 'confirm manually'. Economic-calendar "
        "events are NOT in this dataset — do not fabricate them.",
    }

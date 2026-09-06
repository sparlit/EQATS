from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from loguru import logger

from config import CACHE_DIR, UNIVERSE_CSV


def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _period_to_dates(period: str) -> tuple[str, str]:
    now = pd.Timestamp.now().normalize()
    if period.endswith("y"):
        years = int(period[:-1])
        start = now - pd.DateOffset(years=years)
    elif period.endswith("mo"):
        months = int(period[:-2])
        start = now - pd.DateOffset(months=months)
    elif period.endswith("d"):
        days = int(period[:-1])
        start = now - pd.Timedelta(days=days)
    else:
        start = now - pd.DateOffset(years=1)
    return start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


def _fetch_history_from_yfinance(symbol: str, period: str, interval: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        return df
    df.columns = [c.lower() for c in df.columns]
    if hasattr(df.index, "tzinfo") and df.index.tzinfo is not None:
        df.index = df.index.tz_localize(None)
    return df


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase columns and strip timezone from index."""
    if df.empty:
        return df
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if hasattr(df.index, "tzinfo") and df.index.tzinfo is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_symbol_history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Fetch OHLCV history for a single symbol and cache as parquet."""
    ensure_cache_dir()
    safe = symbol.replace(":", "_").replace(".", "_")
    symbol_path = CACHE_DIR / f"{safe}_{interval}_{period}.parquet"
    # Parquet cache is best-effort — needs a parquet engine (pyarrow). On hosts
    # without it (lean cloud backend), we silently skip caching and re-fetch.
    if symbol_path.exists():
        try:
            df = pd.read_parquet(symbol_path)
            if not df.empty:
                return _normalise(df)
        except Exception as exc:
            logger.debug("Parquet cache read skipped for %s: %s", symbol, exc)

    logger.info("Fetching history for %s", symbol)
    try:
        df = _normalise(_fetch_history_from_yfinance(symbol, period, interval))
    except Exception as exc:
        logger.exception("yfinance fetch failed for %s: %s", symbol, exc)
        raise

    if df.empty:
        raise ValueError(f"No data returned for symbol: {symbol}")
    try:
        df.to_parquet(symbol_path)
    except Exception as exc:
        logger.debug("Parquet cache write skipped for %s: %s", symbol, exc)
    return df


def fetch_symbols_history(symbols: list[str], period: str = "6mo", interval: str = "1d") -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV history for multiple symbols.

    Daily bars are served from the committed OHLCV cache when available (built
    nightly by GitHub Actions) — this is what makes the screener fast/reliable
    on the cloud. Anything not cached falls back to a live yfinance fetch.
    """
    results: dict[str, pd.DataFrame] = {}
    misses: list[str] = []

    if interval == "1d":
        try:
            from data.ohlcv_cache import get_cached_ohlcv
            for symbol in symbols:
                df = get_cached_ohlcv(symbol)
                if df is not None and not df.empty:
                    results[symbol] = df
                else:
                    misses.append(symbol)
        except Exception as exc:
            logger.debug("OHLCV cache unavailable: {}", exc)
            misses = [s for s in symbols if s not in results]
    else:
        misses = list(symbols)

    if results and misses:
        # Cache is live: don't serially hammer yfinance for stragglers (delisted
        # or newly added names) — the screener can proceed without them.
        logger.info("OHLCV cache hit {}/{} symbols; skipping {} misses",
                    len(results), len(symbols), len(misses))
        return results

    for symbol in misses:
        try:
            results[symbol] = fetch_symbol_history(symbol, period=period, interval=interval)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", symbol, exc)
    return results


def load_universe() -> pd.DataFrame:
    """Load the symbol universe from CSV."""
    if not UNIVERSE_CSV.exists():
        raise FileNotFoundError(f"Universe file not found: {UNIVERSE_CSV}")
    df = pd.read_csv(UNIVERSE_CSV)
    df.columns = df.columns.str.lower()
    # Use yfinance_ticker as symbol so .NS suffix is included for all fetches
    if "yfinance_ticker" in df.columns:
        df = df.assign(symbol=df["yfinance_ticker"])
    return df

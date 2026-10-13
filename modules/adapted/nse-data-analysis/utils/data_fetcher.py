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
data_fetcher.py
================
Resilient data access layer for the NSE Fundamental Screener.

Design goals:
- yfinance is unofficial and rate-limits aggressively at scale (Nifty 500 = 500 tickers).
  This module adds: disk caching (parquet), exponential backoff retries, batched/throttled
  fetching, and graceful per-ticker failure (one bad symbol never kills the whole run).
- Pluggable: `DataSource` is an abstract interface. Today only YFinanceSource is implemented,
  but a NSEOfficialSource / paid-provider source can be dropped in later without touching
  the rest of the app (see README "Extending data sources").
"""


import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_fetcher")

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS = 60 * 60 * 6  # 6 hours — fundamentals don't change intraday


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    symbol: str
    ok: bool
    info: dict = field(default_factory=dict)
    financials: pd.DataFrame | None = None
    balance_sheet: pd.DataFrame | None = None
    cashflow: pd.DataFrame | None = None
    quarterly_financials: pd.DataFrame | None = None
    history: pd.DataFrame | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Abstract data source interface (so other providers can be slotted in)
# ---------------------------------------------------------------------------


class DataSource(ABC):
    @abstractmethod
    def fetch(self, symbol: str) -> FetchResult: ...


# ---------------------------------------------------------------------------
# yfinance implementation with retry/backoff + disk cache
# ---------------------------------------------------------------------------


class YFinanceSource(DataSource):
    """
    Wraps yfinance with:
      - exponential backoff retries on transient failures / rate limits
      - on-disk parquet caching per symbol (info as JSON-ish single-row df)
      - jittered delay between calls to reduce 429s when looping over many tickers
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 1.5, request_jitter: float = 0.4):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.request_jitter = request_jitter

    def _cache_paths(self, symbol: str) -> dict:
        safe = symbol.replace(".", "_")
        return {
            "info": CACHE_DIR / f"{safe}_info.parquet",
            "financials": CACHE_DIR / f"{safe}_financials.parquet",
            "balance_sheet": CACHE_DIR / f"{safe}_balance_sheet.parquet",
            "cashflow": CACHE_DIR / f"{safe}_cashflow.parquet",
            "quarterly_financials": CACHE_DIR / f"{safe}_qfinancials.parquet",
            "history": CACHE_DIR / f"{safe}_history.parquet",
        }

    def _cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        return (time.time() - path.stat().st_mtime) < CACHE_TTL_SECONDS

    def _load_cache(self, symbol: str) -> FetchResult | None:
        paths = self._cache_paths(symbol)
        if not self._cache_fresh(paths["info"]):
            return None
        try:
            info_df = pd.read_parquet(paths["info"])
            info = info_df.iloc[0].to_dict() if not info_df.empty else {}

            def _load(p):
                return pd.read_parquet(p) if p.exists() else None

            return FetchResult(
                symbol=symbol,
                ok=True,
                info=info,
                financials=_load(paths["financials"]),
                balance_sheet=_load(paths["balance_sheet"]),
                cashflow=_load(paths["cashflow"]),
                quarterly_financials=_load(paths["quarterly_financials"]),
                history=_load(paths["history"]),
            )
        except Exception as e:  # corrupted cache -> ignore, refetch
            logger.warning(f"Cache read failed for {symbol}: {e}")
            return None

    def _save_cache(self, symbol: str, result: FetchResult) -> None:
        paths = self._cache_paths(symbol)
        try:
            pd.DataFrame([result.info]).to_parquet(paths["info"])
            for key in [
                "financials",
                "balance_sheet",
                "cashflow",
                "quarterly_financials",
                "history",
            ]:
                df = getattr(result, key)
                if df is not None and not df.empty:
                    df.to_parquet(paths[key])
        except Exception as e:
            logger.warning(f"Cache write failed for {symbol}: {e}")

    def fetch(self, symbol: str, use_cache: bool = True) -> FetchResult:
        if use_cache:
            cached = self._load_cache(symbol)
            if cached is not None:
                return cached

        if yf is None:
            return FetchResult(symbol=symbol, ok=False, error="yfinance not installed")

        ticker_str = f"{symbol}.NS"
        last_err = None

        for attempt in range(1, self.max_retries + 1):
            try:
                ticker = yf.Ticker(ticker_str)
                info = ticker.info or {}

                if (
                    not info
                    or info.get("regularMarketPrice") is None
                    and info.get("currentPrice") is None
                ):
                    # Sometimes yfinance returns a near-empty dict for delisted/invalid symbols
                    if attempt == self.max_retries:
                        return FetchResult(
                            symbol=symbol,
                            ok=False,
                            error="No data returned (invalid/delisted symbol?)",
                        )
                    raise ValueError("Empty info payload")

                financials = self._safe_df(lambda: ticker.financials)
                balance_sheet = self._safe_df(lambda: ticker.balance_sheet)
                cashflow = self._safe_df(lambda: ticker.cashflow)
                quarterly_financials = self._safe_df(lambda: ticker.quarterly_financials)
                history = self._safe_df(lambda: ticker.history(period="5y", interval="1mo"))

                result = FetchResult(
                    symbol=symbol,
                    ok=True,
                    info=info,
                    financials=financials,
                    balance_sheet=balance_sheet,
                    cashflow=cashflow,
                    quarterly_financials=quarterly_financials,
                    history=history,
                )
                self._save_cache(symbol, result)

                # Jittered pause to be polite to the upstream API and reduce 429s
                time.sleep(self.request_jitter * random.random())
                return result

            except Exception as e:
                last_err = str(e)
                if attempt < self.max_retries:
                    backoff = self.base_delay * (2 ** (attempt - 1)) + random.random()
                    logger.info(
                        f"{symbol}: attempt {attempt} failed ({e}); retrying in {backoff:.1f}s"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(f"{symbol}: giving up after {self.max_retries} attempts ({e})")

        return FetchResult(symbol=symbol, ok=False, error=last_err or "Unknown fetch error")

    @staticmethod
    def _safe_df(fn) -> pd.DataFrame | None:
        try:
            df = fn()
            return df if isinstance(df, pd.DataFrame) else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Batch fetch helper with progress callback (for Streamlit progress bars)
# ---------------------------------------------------------------------------


def fetch_universe(
    symbols: list[str],
    source: DataSource | None = None,
    progress_callback=None,
    use_cache: bool = True,
) -> dict[str, FetchResult]:
    """
    Fetch a list of symbols sequentially (yfinance does not provide a safe bulk endpoint
    for this much fundamental data), reporting progress and isolating per-symbol failures.
    """
    source = source or YFinanceSource()
    results: dict[str, FetchResult] = {}

    for i, symbol in enumerate(symbols):
        try:
            results[symbol] = source.fetch(symbol, use_cache=use_cache)
        except Exception as e:
            results[symbol] = FetchResult(symbol=symbol, ok=False, error=str(e))

        if progress_callback:
            progress_callback(i + 1, len(symbols), symbol)

    return results


# ---------------------------------------------------------------------------
# Universe list loader (Nifty 50 / Nifty 500 / custom)
# ---------------------------------------------------------------------------

NIFTY500_LIVE_URL = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
NIFTY500_FALLBACK_PATH = Path(__file__).resolve().parent.parent / "data" / "nifty500_fallback.csv"


def _load_universe_impl(index: str = "NIFTY500") -> pd.DataFrame:
    """
    Pure, Streamlit-independent implementation. Used directly by headless scripts
    (e.g. scripts/export_daily.py for GitHub Actions) and wrapped by `load_universe`
    below for the interactive Streamlit app's caching.

    Returns a DataFrame with columns: Symbol, Company Name, Industry.
    Tries the live NSE Indices CSV first; falls back to a bundled static snapshot
    if the network call fails (rate-limited, blocked, offline, endpoint moved, etc).
    """
    if index in ("NIFTY500", "NIFTY 500"):
        try:
            df = pd.read_csv(NIFTY500_LIVE_URL)
            df = df.rename(columns={c: c.strip() for c in df.columns})
            required = {"Symbol", "Company Name", "Industry"}
            if required.issubset(set(df.columns)):
                return df[["Symbol", "Company Name", "Industry"]].dropna(subset=["Symbol"])
        except Exception as e:
            logger.warning(f"Live Nifty 500 fetch failed ({e}); using bundled fallback list.")

        if NIFTY500_FALLBACK_PATH.exists():
            df = pd.read_csv(NIFTY500_FALLBACK_PATH)
            return df

        raise RuntimeError(
            "No Nifty 500 list available (live fetch failed and no fallback file found)."
        )

    elif index in ("NIFTY50", "NIFTY 50"):
        nifty50 = [
            "RELIANCE",
            "TCS",
            "HDFCBANK",
            "ICICIBANK",
            "INFY",
            "ITC",
            "LT",
            "SBIN",
            "BHARTIARTL",
            "AXISBANK",
            "KOTAKBANK",
            "BAJFINANCE",
            "HINDUNILVR",
            "ASIANPAINT",
            "MARUTI",
            "TITAN",
            "SUNPHARMA",
            "NTPC",
            "ONGC",
            "ADANIPORTS",
            "M&M",
            "TATAMOTORS",
            "TATASTEEL",
            "ULTRACEMCO",
            "WIPRO",
            "HCLTECH",
            "POWERGRID",
            "NESTLEIND",
            "GRASIM",
            "JSWSTEEL",
            "TECHM",
            "BAJAJFINSV",
            "DRREDDY",
            "CIPLA",
            "EICHERMOT",
            "BRITANNIA",
            "DIVISLAB",
            "APOLLOHOSP",
            "INDUSINDBK",
            "HDFCLIFE",
            "SBILIFE",
            "BAJAJ-AUTO",
            "COALINDIA",
            "HINDALCO",
            "TATACONSUM",
            "UPL",
            "SHRIRAMFIN",
            "LTIM",
            "ADANIENT",
            "HEROMOTOCO",
        ]
        return pd.DataFrame({"Symbol": nifty50, "Company Name": nifty50, "Industry": "Unknown"})

    else:
        raise ValueError(f"Unknown index: {index}")


@st.cache_data(ttl=60 * 60 * 24)
def load_universe(index: str = "NIFTY500") -> pd.DataFrame:
    """
    Streamlit-cached wrapper around `_load_universe_impl`, for use inside the
    interactive app (app/main.py). Headless scripts should call
    `_load_universe_impl` directly instead, to avoid any dependency on a live
    Streamlit runtime context.
    """
    return _load_universe_impl(index)

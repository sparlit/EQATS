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
Data source abstraction for the Indian Stock Tracker.

This module defines a common interface for fetching daily OHLCV (open, high,
low, close, volume) data from multiple providers. The application currently
supports:

  * NSE India (``nsepy``)        — primary source (official exchange feed)
  * Yahoo Finance (``yfinance``) — secondary / fallback source

Mutual funds are tracked separately via the dedicated ``mutual_funds.db``
database and the ``mutual_fund_db.py`` processing pipeline.

Relying on a single provider is fragile: rate limits, outages, or changes to a
provider's API can silently drop stocks from the database. By abstracting each
provider behind a common interface and falling back from one to the next, the
fetcher becomes far more resilient — if NSE is unavailable we can still
pull the same data from Yahoo Finance.
"""


import abc
from dataclasses import dataclass
from typing import List, Optional

import requests


@dataclass
class OHLCV:
    """Normalized daily price record returned by every data source."""

    date: datetime.date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    # Close of the previous trading session, if the source could determine
    # one. ``None`` means "unknown" — callers should treat that as 0.0% and
    # not attempt arithmetic. Populated by ``YFinanceSource.fetch_latest``
    # when at least two rows of history are available; NSE and MF sources
    # leave it as ``None`` for now.
    prev_close: float | None = None


def _strip_exchange_suffix(symbol: str) -> str:
    """
    Convert a Yahoo-style symbol (``RELIANCE.NS``) to a bare NSE/BSE ticker.

    NSE's official APIs expect bare tickers, so any ``.NS`` / ``.BO`` suffix
    is removed before the request is made.
    """
    return symbol.upper().replace(".NS", "").replace(".BO", "")


class DataSource(abc.ABC):
    """Abstract base class for all price data providers."""

    #: Human-readable name used for logging.
    name: str = "base"

    @abc.abstractmethod
    def fetch_latest(self, symbol: str) -> OHLCV | None:
        """
        Fetch the most recent available trading day's OHLCV for ``symbol``.

        Returns ``None`` if no data could be retrieved (so the caller can fall
        back to the next source).
        """
        raise NotImplementedError

    def fetch_name(self, symbol: str) -> str | None:
        """
        Best-effort lookup of a human-readable company name for ``symbol``.

        Returns ``None`` if the source cannot provide one; the caller will then
        try the next source or fall back to the raw symbol.
        """
        return None


class YFinanceSource(DataSource):
    """Yahoo Finance provider (wraps the ``yfinance`` library)."""

    name = "yfinance"

    def fetch_latest(self, symbol: str) -> OHLCV | None:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        # Pull the last few sessions to guarantee we have a complete row even
        # if the very latest session is still being finalized.
        hist = ticker.history(period="5d")
        if hist is None or hist.empty:
            return None

        latest = hist.iloc[-1]
        row_date = latest.name.date() if isinstance(latest.name, datetime.datetime) else latest.name

        # If we have at least two rows, capture the prior session's close so
        # callers (e.g. dashboard percentage change) don't have to make a
        # second round-trip. ``len(hist) >= 2`` guards against weekends /
        # freshly-listed tickers where only the current row exists.
        prev_close: float | None = None
        if len(hist) >= 2:
            try:
                prev_close = float(hist.iloc[-2]["Close"])
            except Exception:
                prev_close = None

        return OHLCV(
            date=row_date,
            open=float(latest["Open"]),
            high=float(latest["High"]),
            low=float(latest["Low"]),
            close=float(latest["Close"]),
            adj_close=float(latest.get("Adj Close", latest["Close"])),
            volume=float(latest["Volume"]),
            prev_close=prev_close,
        )

    def fetch_history(self, symbol: str, limit: int = 60) -> list[OHLCV]:
        """Fetch historical OHLCV data for a symbol."""
        import yfinance as yf

        try:
            ticker = yf.Ticker(symbol)
            # Fetch enough data to get at least 'limit' trading days
            # Using '6mo' should give us plenty of data
            hist = ticker.history(period="6mo")
            if hist is None or hist.empty:
                return []

            # Convert to OHLCV objects, most recent first
            records = []
            for idx, row in hist.iterrows():
                date = idx.date() if hasattr(idx, "date") else idx
                records.append(
                    OHLCV(
                        date=date,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        adj_close=float(row.get("Adj Close", row["Close"])),
                        volume=float(row["Volume"]),
                    )
                )

            # Return the most recent 'limit' records
            return records[-limit:]
        except Exception:
            return []

    def fetch_name(self, symbol: str) -> str | None:
        try:
            import yfinance as yf

            return yf.Ticker(symbol).info.get("shortName")
        except Exception:
            return None


class NSESource(DataSource):
    """
    NSE India official data via ``nsepy``.

    NSE symbols are bare tickers (``RELIANCE``), so Yahoo-style suffixes such
    as ``.NS`` are stripped before the request. This is the primary source;
    Yahoo Finance is used as a fallback when NSE is unavailable.
    """

    name = "nse"

    def fetch_latest(self, symbol: str) -> OHLCV | None:
        try:
            from nsepy import get_history
        except ImportError:
            return None

        nse_symbol = _strip_exchange_suffix(symbol)
        end = datetime.date.today()
        start = end - datetime.timedelta(days=7)
        try:
            hist = get_history(symbol=nse_symbol, start=start, end=end)
        except Exception:
            return None

        if hist is None or len(hist) == 0:
            return None

        latest = hist.iloc[-1]
        row_date = latest.name.date() if isinstance(latest.name, datetime.datetime) else latest.name
        # nsepy columns: Open, High, Low, Close, Volume (plus Last, VWAP, etc.)
        return OHLCV(
            date=row_date,
            open=float(latest["Open"]),
            high=float(latest["High"]),
            low=float(latest["Low"]),
            close=float(latest["Close"]),
            adj_close=float(latest["Close"]),
            volume=float(latest["Volume"]),
        )

    def fetch_name(self, symbol: str) -> str | None:
        try:
            from nsepy import get_quote

            nse_symbol = _strip_exchange_suffix(symbol)
            quote = get_quote(nse_symbol)
            if isinstance(quote, dict):
                return quote.get("companyName") or quote.get("symbol")
        except Exception:
            return None
        return None


class MutualFundSource(DataSource):
    """
    Mutual fund NAV data via ``mfapi.in``.

    This source fetches the latest Net Asset Value (NAV) for a given mutual
    fund scheme. The mfapi.in API returns a JSON array of daily NAV records;
    we extract the most recent one and convert it to an OHLCV record where
    open = high = low = close = adj_close = NAV and volume = 0 (since NAV
    is not a traded volume).
    """

    name = "mutual_fund"

    def fetch_latest(self, symbol: str) -> OHLCV | None:
        """
        Fetch the latest NAV for a mutual fund scheme.

        ``symbol`` should be the mfapi.in scheme code (e.g., "0P0000XVTS").
        """
        try:
            # mfapi.in returns a JSON array of daily NAV records
            response = requests.get(f"https://api.mfapi.in/mf/{symbol}", timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data or "data" not in data or not data["data"]:
                return None

            latest = data["data"][0]  # mfapi.in returns newest-first; [0] is most recent
            nav = float(latest["nav"])
            date_str = latest["date"]

            # Parse date (format: "DD-MM-YYYY")
            day, month, year = map(int, date_str.split("-"))
            nav_date = datetime.date(year, month, day)

            return OHLCV(
                date=nav_date,
                open=nav,
                high=nav,
                low=nav,
                close=nav,
                adj_close=nav,
                volume=0.0,  # NAV has no volume
            )
        except Exception:
            return None

    def fetch_name(self, symbol: str) -> str | None:
        """
        Fetch the mutual fund scheme name from mfapi.in.
        """
        try:
            response = requests.get(f"https://api.mfapi.in/mf/{symbol}", timeout=10)
            response.raise_for_status()
            data = response.json()

            if data and "meta" in data:
                return data["meta"].get("scheme_name")
        except Exception:
            pass
        return None

    def fetch_history(self, symbol: str, limit: int = 60) -> list[OHLCV]:
        """
        Fetch the most recent ``limit`` NAV records for a scheme so that
        scoring (which needs prior NAVs to compute returns) has history to
        work with. mfapi.in returns records newest-first.
        """
        try:
            response = requests.get(f"https://api.mfapi.in/mf/{symbol}", timeout=10)
            response.raise_for_status()
            data = response.json()
            if not data or "data" not in data or not data["data"]:
                return []

            records = []
            for rec in data["data"][:limit]:
                nav = float(rec["nav"])
                day, month, year = map(int, rec["date"].split("-"))
                nav_date = datetime.date(year, month, day)
                records.append(OHLCV(date=nav_date, open=nav, high=nav, low=nav, close=nav, adj_close=nav, volume=0.0))
            # Return the most recent 'limit' records
            return records[-limit:]
        except Exception:
            return []


# Ordered list of sources tried by the fetcher. NSE is first (official
# exchange feed); yfinance is the fallback for resilience.
# Mutual funds are tracked separately via mutual_funds.db and mutual_fund_db.py.
DEFAULT_SOURCES: list[DataSource] = [NSESource(), YFinanceSource()]


def fetch_with_fallback(symbol: str, sources: list[DataSource] | None = None) -> OHLCV | None:
    """
    Try each data source in order and return the first successful result.

    Returns ``None`` only if *every* source failed for ``symbol``.
    """
    sources = sources or DEFAULT_SOURCES
    last_error: Exception | None = None
    for source in sources:
        try:
            result = source.fetch_latest(symbol)
            if result is not None:
                return result
        except Exception as exc:  # keep trying the next source
            last_error = exc
            continue
    if last_error:
        print(f"All data sources failed for {symbol}: {last_error}")
    return None


def resolve_name(symbol: str, sources: list[DataSource] | None = None) -> str | None:
    """
    Resolve a company name for ``symbol`` using the first source that can
    provide one. Returns ``None`` if no source succeeds.
    """
    sources = sources or DEFAULT_SOURCES
    for source in sources:
        try:
            name = source.fetch_name(symbol)
            if name:
                return name
        except Exception:
            continue
    return None

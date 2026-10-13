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


"""Data ingestion layer — yfinance download with backoff and resumable batching.

Design notes
------------
* Downloads are keyed by *symbol*. If the cache already covers the requested
  date range for a symbol, no network call is made (unless force=True).
* Exponential backoff with jitter is used to survive yfinance rate limits.
* ``download_universe`` is the primary entry point; it updates the cache in-place
  and returns the set of symbols that were successfully downloaded.
* The ``NSE_ALPHA_OFFLINE`` environment variable disables all network calls
  (used in CI where tests must not hit the network).

Pricing columns returned by yfinance for each symbol::

    Open  High  Low  Close  Adj Close  Volume
"""


import logging
import os
import time
from collections.abc import Sequence

import pandas as pd
import yfinance as yf
from nse_alpha.data.cache import get_cached_range, save_to_cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BATCH_SIZE: int = 10  # symbols per yfinance batch call
SLEEP_BETWEEN_BATCHES: float = 1.5  # seconds
MAX_RETRIES: int = 5
BASE_BACKOFF: float = 2.0  # seconds; doubles each retry
MAX_BACKOFF: float = 120.0  # seconds


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def download_universe(
    symbols: Sequence[str],
    start: str,
    end: str,
    *,
    force: bool = False,
    batch_size: int = BATCH_SIZE,
) -> set[str]:
    """Download OHLCV data for *symbols* between *start* and *end*, using cache.

    Parameters
    ----------
    symbols:
        List of ticker symbols (e.g. with the ``.NS`` suffix for NSE).
    start:
        ISO-8601 date string, e.g. ``"2015-01-01"``.
    end:
        ISO-8601 date string (exclusive upper bound for yfinance).
    force:
        If ``True``, re-download even if covered by cache.
    batch_size:
        Number of tickers to download per yfinance call.

    Returns
    -------
    set[str]
        Symbols that were successfully loaded (from cache or freshly downloaded).
    """
    if os.environ.get("NSE_ALPHA_OFFLINE"):
        logger.warning(
            "NSE_ALPHA_OFFLINE is set — all network calls are disabled. "
            "Only cached data will be used."
        )
        return _load_from_cache_only(symbols, start, end)

    successful: set[str] = set()
    to_download: list[str] = []

    for sym in symbols:
        if not force:
            cached = get_cached_range(sym)
            if cached is not None and cached["start"] <= start and cached["end"] >= end:
                logger.debug("Cache hit for %s (%s → %s)", sym, start, end)
                successful.add(sym)
                continue
        to_download.append(sym)

    logger.info(
        "%d symbols cached, %d to download",
        len(successful),
        len(to_download),
    )

    if to_download:
        downloaded = _download_batches(to_download, start, end, batch_size=batch_size)
        successful.update(downloaded)

    return successful


def download_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    force: bool = False,
) -> bool:
    """Download OHLCV data for a single *symbol* between *start* and *end*."""
    result = download_universe([symbol], start, end, force=force, batch_size=1)
    return symbol in result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_from_cache_only(symbols: Sequence[str], start: str, end: str) -> set[str]:
    """Return symbols whose cache covers the requested range (offline mode)."""
    successful: set[str] = set()
    for sym in symbols:
        cached = get_cached_range(sym)
        if cached is not None and cached["start"] <= start and cached["end"] >= end:
            successful.add(sym)
        else:
            logger.debug("Cache miss for %s — skipping (offline mode)", sym)
    return successful


def _download_batches(
    symbols: list[str],
    start: str,
    end: str,
    batch_size: int = BATCH_SIZE,
) -> set[str]:
    """Download *symbols* in batches of ``batch_size``, with backoff."""
    successful: set[str] = set()

    for batch_start in range(0, len(symbols), batch_size):
        batch = symbols[batch_start : batch_start + batch_size]
        logger.info(
            "Downloading batch %d–%d of %d: %s",
            batch_start + 1,
            min(batch_start + batch_size, len(symbols)),
            len(symbols),
            batch,
        )
        result = _download_with_retry(batch, start, end)
        successful.update(result)

        if batch_start + batch_size < len(symbols):
            logger.debug("Sleeping %.1fs between batches", SLEEP_BETWEEN_BATCHES)
            time.sleep(SLEEP_BETWEEN_BATCHES)

    return successful


def _download_with_retry(
    symbols: list[str],
    start: str,
    end: str,
) -> set[str]:
    """Download one batch with exponential backoff. Returns successfully saved symbols."""
    delay = BASE_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # yfinance download
            raw = yf.download(
                tickers=symbols if len(symbols) > 1 else symbols[0],
                start=start,
                end=end,
                auto_adjust=False,
                progress=False,
                threads=len(symbols) > 1,
                group_by="ticker",
            )
            if raw is None or raw.empty:
                logger.warning("yfinance returned empty DataFrame for %s", symbols)
                return set()
            return _unpack_and_cache(raw, symbols, start, end)
        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.error(
                    "Failed to download %s after %d attempts: %s",
                    symbols,
                    MAX_RETRIES,
                    exc,
                )
                return set()
            jitter = delay * 0.25
            sleep_time = min(delay + jitter, MAX_BACKOFF)
            logger.warning(
                "Attempt %d/%d for %s failed (%s). Retrying in %.1fs",
                attempt,
                MAX_RETRIES,
                symbols,
                exc,
                sleep_time,
            )
            time.sleep(sleep_time)
            delay = min(delay * 2, MAX_BACKOFF)
    return set()


def _unpack_and_cache(
    raw: pd.DataFrame,
    symbols: list[str],
    start: str,
    end: str,
) -> set[str]:
    """Unpack yfinance DataFrame, normalise columns, and cache each symbol."""
    saved: set[str] = set()

    for sym in symbols:
        sym_df = _extract_symbol_slice(raw, sym, symbols)
        if sym_df is None or sym_df.empty:
            logger.warning("Symbol %s missing or empty in yfinance response", sym)
            continue

        df = _normalise_single(sym_df, sym)
        if df is not None:
            save_to_cache(sym, df, start, end)
            saved.add(sym)

    return saved


def _extract_symbol_slice(
    raw: pd.DataFrame,
    sym: str,
    all_symbols: list[str],
) -> pd.DataFrame | None:
    """Extract the price DataFrame for a given symbol from the raw yfinance result."""
    if raw.empty:
        return None

    if isinstance(raw.columns, pd.MultiIndex):
        level_0_values = list(raw.columns.get_level_values(0))
        level_1_values = list(raw.columns.get_level_values(1)) if raw.columns.nlevels > 1 else []

        if sym in level_0_values:
            val_0 = raw[sym]
            return val_0.to_frame() if isinstance(val_0, pd.Series) else pd.DataFrame(val_0).copy()
        elif sym in level_1_values:
            val_1 = raw.xs(sym, level=1, axis=1)
            return val_1.to_frame() if isinstance(val_1, pd.Series) else pd.DataFrame(val_1).copy()
        elif len(all_symbols) == 1:
            # Single ticker download with unexpected level names
            return raw.droplevel(0, axis=1).copy() if raw.columns.nlevels > 1 else raw.copy()
        return None
    else:
        # Flat single-index columns
        if len(all_symbols) == 1:
            return raw.copy()
        return None


def _normalise_single(raw: pd.DataFrame, sym: str) -> pd.DataFrame | None:
    """Rename yfinance columns to our internal schema and validate."""
    if raw.empty:
        return None

    df = raw.copy()

    # If columns is a MultiIndex, flatten to single level
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    # Build case-insensitive lookup
    col_lookup = {str(col).strip().lower(): col for col in df.columns}

    canonical_map = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "adj close": "adj_close",
        "adj_close": "adj_close",
        "volume": "volume",
    }

    found_cols: dict[str, str] = {}
    for key, canonical in canonical_map.items():
        if key in col_lookup and canonical not in found_cols.values():
            found_cols[col_lookup[key]] = canonical

    # Check required core price columns
    req_price_cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in req_price_cols if c not in found_cols.values()]
    if missing:
        logger.warning(
            "Symbol %s missing required columns %s (available: %s)",
            sym,
            missing,
            list(df.columns),
        )
        return None

    out = pd.DataFrame(index=df.index)
    for orig_col, target_col in found_cols.items():
        out[target_col] = pd.to_numeric(df[orig_col], errors="coerce")

    if "adj_close" not in out.columns:
        out["adj_close"] = out["close"]

    # Normalise index dates (ensure timezone-naive datetime)
    if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
        out.index = out.index.tz_convert(None)
    out.index = pd.to_datetime(out.index).normalize()
    out.index.name = "date"

    # Drop rows where close is NaN
    out = out[out["close"].notna()]
    if out.empty:
        logger.warning("Symbol %s has no valid non-null rows — skipping", sym)
        return None

    # Compute turnover_value using raw close * volume
    out["turnover_value"] = out["close"] * out["volume"]

    # Ensure all required columns exist in standard order
    required = ["open", "high", "low", "close", "adj_close", "volume", "turnover_value"]
    for col in required:
        if col not in out.columns:
            logger.warning("Symbol %s missing calculated column %s", sym, col)
            return None

    return out[required].sort_index()

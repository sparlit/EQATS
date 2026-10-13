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


"""Parquet cache layer.

Layout on disk::

    cache/
      raw/
        <SYMBOL>.parquet   ← one file per symbol, all dates in a single file
      meta/
        <SYMBOL>.json      ← {"start": "2015-01-01", "end": "2024-12-31"}

The meta file is the source of truth for whether a symbol is fully cached.
We never partially append; we always overwrite the symbol file when we save.
"""


import json
import logging
import shutil
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_CACHE_ROOT = Path("cache")
_RAW_DIR = _CACHE_ROOT / "raw"
_META_DIR = _CACHE_ROOT / "meta"

REQUIRED_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume", "turnover_value"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_cached_range(symbol: str) -> dict[str, str] | None:
    """Return ``{"start": ..., "end": ...}`` if symbol is cached, else ``None``."""
    meta_path = _META_DIR / f"{_safe(symbol)}.json"
    if not meta_path.exists():
        return None
    with meta_path.open() as f:
        return json.load(f)  # type: ignore[no-any-return]


def load_symbol(symbol: str) -> pd.DataFrame | None:
    """Load all cached rows for *symbol*.  Returns ``None`` if not cached."""
    path = _RAW_DIR / f"{_safe(symbol)}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"
    return df


def save_to_cache(
    symbol: str,
    df: pd.DataFrame,
    start: str,
    end: str,
) -> None:
    """Persist *df* for *symbol* and update the meta file."""
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    _META_DIR.mkdir(parents=True, exist_ok=True)

    # Normalize dates before saving
    df = df.copy()
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"

    # If there's existing cached data, merge and deduplicate
    existing = load_symbol(symbol)
    if existing is not None:
        df = pd.concat([existing, df])
        df = df[~df.index.duplicated(keep="last")].sort_index()

    path = _RAW_DIR / f"{_safe(symbol)}.parquet"
    df.to_parquet(path, engine="pyarrow", compression="snappy")

    # Update meta with the actual date range in the file
    actual_start = str(df.index.min().date())
    actual_end = str(df.index.max().date())
    meta_path = _META_DIR / f"{_safe(symbol)}.json"
    with meta_path.open("w") as f:
        json.dump({"start": actual_start, "end": actual_end}, f)

    logger.debug("Cached %s: %d rows (%s → %s)", symbol, len(df), actual_start, actual_end)


def clear_cache(symbol: str | None = None) -> None:
    """Clear cached data for a specific symbol or all symbols."""
    if symbol is not None:
        parquet_path = _RAW_DIR / f"{_safe(symbol)}.parquet"
        meta_path = _META_DIR / f"{_safe(symbol)}.json"
        if parquet_path.exists():
            parquet_path.unlink()
        if meta_path.exists():
            meta_path.unlink()
        logger.info("Cleared cache for symbol %s", symbol)
    else:
        if _RAW_DIR.exists():
            shutil.rmtree(_RAW_DIR)
        if _META_DIR.exists():
            shutil.rmtree(_META_DIR)
        logger.info("Cleared all cache")


def load_panel(
    symbols: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """Build the tidy MultiIndex panel for *symbols* filtered to [start, end].

    Returns a ``pd.DataFrame`` with ``MultiIndex(date, symbol)`` and columns:
    ``open, high, low, close, adj_close, volume, turnover_value``.

    Symbols with no cached data are silently skipped (warning logged).
    """
    frames: list[pd.DataFrame] = []
    for sym in symbols:
        df = load_symbol(sym)
        if df is None:
            logger.warning("No cached data for %s — skipping", sym)
            continue
        # Filter date range
        df = df.loc[start:end].copy()
        if df.empty:
            logger.warning("No data for %s in range %s–%s — skipping", sym, start, end)
            continue
        df.index.name = "date"
        df["symbol"] = sym
        frames.append(df.reset_index().set_index(["date", "symbol"]))

    if not frames:
        return pd.DataFrame(
            columns=REQUIRED_COLUMNS,
            index=pd.MultiIndex.from_tuples([], names=["date", "symbol"]),
        )

    panel = pd.concat(frames).sort_index()

    # Validate columns
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing_cols:
        raise ValueError(f"Panel is missing required columns: {missing_cols}")

    return panel[REQUIRED_COLUMNS]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe(symbol: str) -> str:
    """Replace characters unsafe for filenames (e.g. '.' → '_')."""
    return symbol.replace(".", "_").replace("/", "_").replace("&", "AND")

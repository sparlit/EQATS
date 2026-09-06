"""
NIFTY 50 Market Data Service.

Fetches NIFTY 50 index data from Yahoo Finance (yfinance) and caches
it in the local SQLite database for performance and resilience.

Supported ranges: 1D, 1W, 1M, 3M, 1Y.

Cache-first strategy:
  1. Check DB cache for sufficiently fresh data.
  2. If stale/missing, fetch from yfinance.
  3. Validate and store the fresh data.
  4. If yfinance fails, return the most recent valid cached data.
  5. If neither has data, raise a clear exception.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

from models import MarketIndexPrice, get_session

logger = logging.getLogger(__name__)

NIFTY_SYMBOL = "^NSEI"
NIFTY_NAME = "NIFTY 50"

RANGE_CONFIG: Dict[str, Dict[str, str]] = {
    "1D": {"period": "1d", "interval": "5m"},
    "1W": {"period": "5d", "interval": "15m"},
    "1M": {"period": "1mo", "interval": "1d"},
    "3M": {"period": "3mo", "interval": "1d"},
    "1Y": {"period": "1y", "interval": "1d"},
}

CACHE_TTL: Dict[str, int] = {
    "1D": 300,
    "1W": 900,
    "1M": 3600,
    "3M": 3600,
    "1Y": 7200,
}


class Range(str):
    """Supported NIFTY 50 time-range values."""
    D1 = "1D"
    W1 = "1W"
    M1 = "1M"
    M3 = "3M"
    Y1 = "1Y"

    @classmethod
    def values(cls) -> List[str]:
        return [cls.D1, cls.W1, cls.M1, cls.M3, cls.Y1]


@dataclass
class NiftyDataPoint:
    """A single NIFTY 50 data point for the chart."""
    timestamp: str
    value: float


@dataclass
class NiftyDataResult:
    """Result container for NIFTY 50 data requests."""
    symbol: str = NIFTY_SYMBOL
    name: str = NIFTY_NAME
    range: str = "1D"
    data: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "cache"
    cached: bool = False
    stale: bool = False
    last_updated: Optional[str] = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _df_to_series(df) -> List[Dict[str, Any]]:
    """Convert a yfinance DataFrame to a list of {timestamp, value} dicts."""
    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []
    for idx, row in df.iterrows():
        ts = idx
        if hasattr(ts, 'tz') and ts.tz is not None:
            ts_kolkata = ts.astimezone(timezone(timedelta(hours=5, minutes=30)))
        else:
            ts_kolkata = ts.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))

        close_val = row.get("Close")
        if close_val is None or (isinstance(close_val, float) and close_val != close_val):
            continue

        records.append({
            "timestamp": ts_kolkata.isoformat(),
            "value": round(float(close_val), 2),
        })

    return records


def _validate_series(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove invalid data points (NaN, None, zero values)."""
    valid: List[Dict[str, Any]] = []
    for point in series:
        val = point.get("value")
        ts = point.get("timestamp")
        if ts and val is not None and val == val and val > 0:
            valid.append(point)
    return valid


def _get_cached_from_db(symbol: str, interval: str) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent cached data from the database."""
    session = get_session()
    try:
        rows = (
            session.query(MarketIndexPrice)
            .filter(
                MarketIndexPrice.symbol == symbol,
                MarketIndexPrice.interval == interval,
            )
            .order_by(MarketIndexPrice.timestamp.asc())
            .all()
        )
        if not rows:
            return None

        records: Dict[str, Dict[str, Any]] = {}
        last_updated = None
        for row in rows:
            ts_iso = row.timestamp.isoformat() if hasattr(row.timestamp, 'isoformat') else str(row.timestamp)
            if ts_iso not in records:
                records[ts_iso] = {
                    "timestamp": ts_iso,
                    "value": round(float(row.close), 2) if row.close else None,
                }
            # Use created_at (when we cached the row) for freshness checks
            row_created = getattr(row, 'created_at', None)
            if row_created is not None:
                if isinstance(row_created, str):
                    try:
                        row_created = datetime.fromisoformat(row_created.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        row_created = None
                if last_updated is None or (row_created is not None and row_created > last_updated):
                    last_updated = row_created

        if not records:
            return None

        return {
            "data": sorted(records.values(), key=lambda x: x["timestamp"]),
            "last_updated": last_updated.isoformat() if last_updated else None,
        }
    except Exception as e:
        logger.warning(f"Failed to read cache from DB: {e}")
        return None
    finally:
        session.close()


def _save_to_db(symbol: str, interval: str, series: List[Dict[str, Any]]) -> None:
    """Save fetched data points to the database cache.

    Uses no_autoflush to prevent the session from flushing pending
    queries before our explicit duplicate check runs.
    """
    if not series:
        return

    session = get_session()
    try:
        with session.no_autoflush:
            # Parse and normalize timestamps (convert tz-aware to UTC-naive)
            parsed = []
            for point in series:
                ts_str = point.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    # Normalize: convert to UTC and strip tzinfo for SQLite compat
                    if ts.tzinfo is not None:
                        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
                    val = point.get("value")
                    if val is not None and val == val and val > 0:
                        parsed.append((ts, val))
                except (ValueError, TypeError):
                    continue

            if not parsed:
                return

            # Check which timestamps already exist
            ts_values = [ts for ts, _ in parsed]
            existing_rows = (
                session.query(MarketIndexPrice.timestamp)
                .filter(
                    MarketIndexPrice.symbol == symbol,
                    MarketIndexPrice.interval == interval,
                    MarketIndexPrice.timestamp.in_(ts_values),
                )
                .all()
            )
            existing_ts_set = set(r[0] for r in existing_rows)

            new_count = 0
            for ts, val in parsed:
                if ts in existing_ts_set:
                    continue
                row = MarketIndexPrice(
                    symbol=symbol,
                    timestamp=ts,
                    interval=interval,
                    close=val,
                    open=val,
                    high=val,
                    low=val,
                    created_at=_now_utc().isoformat(),
                )
                session.add(row)
                new_count += 1

            if new_count > 0:
                session.commit()
                logger.info(f"Cached {new_count} new data points for {symbol} ({interval})")
    except Exception as e:
        logger.error(f"Failed to save to cache DB: {e}")
        session.rollback()
    finally:
        session.close()


def _is_cache_fresh(cached_result: Optional[Dict[str, Any]], range_key: str) -> bool:
    """Check if cached data is fresh enough for the requested range."""
    if cached_result is None:
        return False

    last_updated_str = cached_result.get("last_updated")
    if not last_updated_str:
        return False

    try:
        last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False

    ttl = CACHE_TTL.get(range_key, 3600)
    age = (_now_utc() - last_updated).total_seconds()
    return age < ttl


def fetch_nifty_data(range_key: str = "1D") -> NiftyDataResult:
    """
    Fetch NIFTY 50 data for the requested range.

    Raises:
        ValueError: If the range_key is invalid.
        RuntimeError: If both yfinance and cache fail.
    """
    if range_key not in RANGE_CONFIG:
        raise ValueError(f"Invalid range '{range_key}'. Supported: {list(RANGE_CONFIG.keys())}")

    config = RANGE_CONFIG[range_key]
    period = config["period"]
    interval = config["interval"]

    result = NiftyDataResult(range=range_key)

    # 1. Check cache freshness
    cached = _get_cached_from_db(NIFTY_SYMBOL, interval)
    cache_fresh = _is_cache_fresh(cached, range_key)

    if cache_fresh and cached:
        logger.info(f"Cache hit for {NIFTY_SYMBOL} ({range_key})")
        result.data = cached["data"] or []
        result.source = "cache"
        result.cached = True
        result.stale = False
        result.last_updated = cached.get("last_updated")
        return result

    # 2. Try yfinance
    logger.info(f"Fetching {NIFTY_SYMBOL} from yfinance (period={period}, interval={interval})")
    try:
        ticker = yf.Ticker(NIFTY_SYMBOL)
        df = ticker.history(period=period, interval=interval)

        if df is None or df.empty:
            logger.warning(f"yfinance returned empty DataFrame for {NIFTY_SYMBOL}")
            if cached and cached.get("data"):
                result.data = cached["data"]
                result.source = "cache"
                result.cached = True
                result.stale = True
                result.last_updated = cached.get("last_updated")
                return result
            raise RuntimeError(f"No data available for {NIFTY_SYMBOL}")

        series = _df_to_series(df)
        series = _validate_series(series)

        if not series:
            logger.warning(f"No valid data points after validation for {NIFTY_SYMBOL}")
            if cached and cached.get("data"):
                result.data = cached["data"]
                result.source = "cache"
                result.cached = True
                result.stale = True
                result.last_updated = cached.get("last_updated")
                return result
            raise RuntimeError(f"No valid data points for {NIFTY_SYMBOL}")

        _save_to_db(NIFTY_SYMBOL, interval, series)

        result.data = series
        result.source = "yfinance"
        result.cached = False
        result.stale = False
        result.last_updated = _now_utc().isoformat()

        logger.info(f"Successfully fetched {len(series)} data points for {NIFTY_SYMBOL} ({range_key})")
        return result

    except Exception as e:
        logger.error(f"yfinance fetch failed for {NIFTY_SYMBOL}: {e}")
        if cached and cached.get("data"):
            result.data = cached["data"]
            result.source = "cache"
            result.cached = True
            result.stale = True
            result.last_updated = cached.get("last_updated")
            return result
        raise RuntimeError(f"Failed to fetch NIFTY 50 data: {e}")


def get_nifty_data(range_key: str = "1D") -> Dict[str, Any]:
    """
    Public wrapper that returns a JSON-serializable dict.
    Called by Flask routes.
    """
    try:
        result = fetch_nifty_data(range_key)
        return {
            "symbol": result.symbol,
            "name": result.name,
            "range": result.range,
            "data": result.data,
            "source": result.source,
            "cached": result.cached,
            "stale": result.stale,
            "last_updated": result.last_updated,
            "status": "success",
        }
    except ValueError as e:
        return {
            "symbol": NIFTY_SYMBOL,
            "name": NIFTY_NAME,
            "range": range_key,
            "data": [],
            "source": "error",
            "cached": False,
            "stale": False,
            "last_updated": None,
            "status": "error",
            "message": str(e),
        }
    except Exception as e:
        logger.error(f"Unexpected error fetching NIFTY data: {e}")
        return {
            "symbol": NIFTY_SYMBOL,
            "name": NIFTY_NAME,
            "range": range_key,
            "data": [],
            "source": "error",
            "cached": False,
            "stale": False,
            "last_updated": None,
            "status": "error",
            "message": "Unable to fetch NIFTY 50 data. Please try again later.",
        }

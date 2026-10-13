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
Upstox data adapter — replaces yfinance for historical NSE intraday candles.

Provides 1-2 years of 5-minute data vs yfinance's 60-day limit.

Setup (one-time):
    python upstox_setup.py

Usage:
    from upstox_data import fetch_upstox
    df = fetch_upstox("HDFCBANK", "2025-01-01", "2025-12-31", interval="5minute")
"""

import gzip
import io
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import upstox_client
from upstox_client.rest import ApiException

IST = ZoneInfo("Asia/Kolkata")

_BASE_DIR = os.path.dirname(__file__)
_DATA_DIR = os.path.join(_BASE_DIR, "..", "data")
_TOKEN_FILE = os.path.join(_DATA_DIR, "upstox_token.json")
_INSTRUMENTS_FILE = os.path.join(_DATA_DIR, "upstox_instruments.csv")

# Upstox historical API only supports: 1minute, 30minute, day, week, month
# For 5m/15m we fetch 1-minute data then resample.
# fetch_interval: what we request from Upstox
# resample_to:    pandas resample rule to apply after fetch (None = no resample)
_INTERVAL_MAP = {
    "1m": ("1minute", None),
    "5m": ("1minute", "5min"),
    "15m": ("1minute", "15min"),
    "30m": ("30minute", None),
    "1h": ("30minute", "60min"),
    "1d": ("day", None),
    # native Upstox strings pass through
    "1minute": ("1minute", None),
    "30minute": ("30minute", None),
    "day": ("day", None),
}

# ── Token management ──────────────────────────────────────────────────────────


def get_access_token() -> str | None:
    if not os.path.exists(_TOKEN_FILE):
        return None
    with open(_TOKEN_FILE) as f:
        return json.load(f).get("access_token")


def save_access_token(token: str) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_TOKEN_FILE, "w") as f:
        json.dump({"access_token": token}, f)


def is_configured() -> bool:
    return bool(get_access_token())


def _api_client() -> upstox_client.ApiClient:
    token = get_access_token()
    if not token:
        raise RuntimeError("Upstox token not set. Run: python backend/upstox_setup.py")
    cfg = upstox_client.Configuration()
    cfg.access_token = token
    return upstox_client.ApiClient(cfg)


# ── Instrument master ─────────────────────────────────────────────────────────


def _load_instruments(refresh: bool = False) -> pd.DataFrame:
    """Load NSE equity instrument master. Downloads if missing or refresh=True."""
    if not os.path.exists(_INSTRUMENTS_FILE) or refresh:
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(gzip.decompress(r.content)))
        eq = df[(df["exchange"] == "NSE_EQ") & (df["instrument_type"] == "EQUITY")]
        os.makedirs(_DATA_DIR, exist_ok=True)
        eq.to_csv(_INSTRUMENTS_FILE, index=False)
        return eq
    return pd.read_csv(_INSTRUMENTS_FILE)


def symbol_to_key(symbol: str) -> str:
    """Convert NSE trading symbol (e.g. 'HDFCBANK') to Upstox instrument key."""
    sym = symbol.replace(".NS", "").upper()
    df = _load_instruments()
    row = df[df["tradingsymbol"] == sym]
    if row.empty:
        # Try refresh once — symbol might be new
        df = _load_instruments(refresh=True)
        row = df[df["tradingsymbol"] == sym]
    if row.empty:
        raise ValueError(f"Symbol '{sym}' not found in NSE instrument master")
    return row.iloc[0]["instrument_key"]


# ── Historical candle fetch ───────────────────────────────────────────────────


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1-minute OHLCV to a coarser interval."""
    agg = (
        df.resample(rule, closed="left", label="left")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open"])
    )
    return agg


def fetch_upstox(
    symbol: str,
    start: str,
    end: str,
    interval: str = "5m",
) -> pd.DataFrame:
    """
    Fetch historical OHLCV candles from Upstox.

    Args:
        symbol:   NSE trading symbol (e.g. 'HDFCBANK' or 'HDFCBANK.NS')
        start:    'YYYY-MM-DD'
        end:      'YYYY-MM-DD'
        interval: '1m', '5m', '15m', '30m', '1h', '1d'

    Returns:
        DataFrame with columns [open, high, low, close, volume], IST index.

    Note:
        Upstox historical API only supports 1minute / 30minute / day / week / month.
        5-minute and 15-minute data are fetched as 1-minute then resampled.
    """
    api_interval, resample_rule = _INTERVAL_MAP.get(interval, (interval, None))
    instrument = symbol_to_key(symbol)
    client = _api_client()
    api = upstox_client.HistoryApi(client)

    # Upstox allows up to 365 days per request for 1-minute data
    chunk_days = 29 if api_interval == "1minute" else 364

    frames = []
    cur_start = datetime.strptime(start, "%Y-%m-%d")
    cur_end = datetime.strptime(end, "%Y-%m-%d")

    while cur_start <= cur_end:
        chunk_to = min(cur_start + timedelta(days=chunk_days), cur_end)
        candles = []
        for attempt in (1, 2):
            try:
                resp = api.get_historical_candle_data1(
                    instrument_key=instrument,
                    interval=api_interval,
                    to_date=chunk_to.strftime("%Y-%m-%d"),
                    from_date=cur_start.strftime("%Y-%m-%d"),
                    api_version="2.0",
                )
                candles = resp.data.candles if resp.data else []
                break
            except ApiException as e:
                if "401" in str(e):
                    raise RuntimeError(
                        "Upstox token expired. Run: python backend/upstox_setup.py"
                    ) from e
                if attempt == 2:
                    # Skip this chunk — some ranges 400 sporadically; a hole in
                    # the cache is better than losing the whole symbol.
                    candles = []
                else:
                    import time as _t

                    _t.sleep(1.0)

        if candles:
            df = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(IST)
            df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]].sort_index()
            frames.append(df)

        cur_start = chunk_to + timedelta(days=1)

    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    result = pd.concat(frames).sort_index()
    result = result[~result.index.duplicated(keep="first")]

    if resample_rule:
        result = _resample_ohlcv(result, resample_rule)

    return result

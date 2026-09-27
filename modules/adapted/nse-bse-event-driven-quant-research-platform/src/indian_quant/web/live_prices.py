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


"""Live price service using Upstox Market Quotes API.

Resolves NSE symbols to Upstox instrument keys, fetches live/delayed quotes,
and caches results to avoid excessive API calls.
"""


import csv
import gzip
import json
import logging
import subprocess
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from indian_quant.adapters.upstox.rest import UpstoxRestClient
from indian_quant.config.settings import load_settings

log = logging.getLogger(__name__)

MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
MASTER_CACHE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "upstox_master.csv.gz"
TOKEN_FILE = Path(__file__).resolve().parent.parent.parent.parent / "upstox_tokens.json"
CACHE_TTL_SECONDS = 30


def _refresh_token() -> str | None:
    """Attempt to refresh the Upstox access token using the stored refresh token."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
        refresh_token = data.get("extended_token") or data.get("refresh_token")
        if not refresh_token:
            return None
        import os

        api_key = os.environ.get("UPSTOX_API_KEY", "")
        api_secret = os.environ.get("UPSTOX_API_SECRET", "")
        if not api_key or not api_secret:
            return None
        resp = httpx.post(
            "https://api.upstox.com/v2/login/authorization/token",
            data={
                "code": refresh_token,
                "client_id": api_key,
                "client_secret": api_secret,
                "grant_type": "refresh_token",
                "redirect_uri": os.environ.get("UPSTOX_REDIRECT_URI", ""),
            },
            timeout=15,
        )
        if resp.status_code == 200:
            new_data = resp.json()
            data["access_token"] = new_data["access_token"]
            if "refresh_token" in new_data:
                data["extended_token"] = new_data["refresh_token"]
            TOKEN_FILE.write_text(json.dumps(data, indent=2))
            log.info("Token refreshed successfully")
            return new_data["access_token"]
        log.warning("Token refresh failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("Token refresh error: %s", e)
    return None


class LivePriceService:
    """Batch-fetch live prices from Upstox for NSE symbols."""

    def __init__(self) -> None:
        self._client: UpstoxRestClient | None = None
        self._symbol_to_key: dict[str, str] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_time: dict[str, float] = {}
        self._master_loaded = False

    def _get_client(self) -> UpstoxRestClient:
        if self._client is None:
            settings = load_settings()
            token = settings.upstox.resolve_token()
            self._client = UpstoxRestClient(access_token=token)
        return self._client

    def _ensure_token(self) -> str | None:
        """Get a valid token, refreshing if needed."""
        client = self._get_client()
        if client.access_token:
            return client.access_token
        # Try refresh
        new_token = _refresh_token()
        if new_token:
            client.access_token = new_token
            return new_token
        return None

    def _load_master(self) -> None:
        """Download and parse Upstox instrument master CSV."""
        if self._master_loaded:
            return
        MASTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
        try:
            if MASTER_CACHE.exists():
                age_hours = (time.time() - MASTER_CACHE.stat().st_mtime) / 3600
                if age_hours > 168:  # 7 days
                    self._download_master()
            else:
                self._download_master()
            self._parse_master()
        except Exception as e:
            log.warning("Failed to load Upstox master: %s", e)
            self._master_loaded = True  # Don't retry every call

    def _download_master(self) -> None:
        log.info("Downloading Upstox instrument master...")
        resp = httpx.get(MASTER_URL, timeout=60)
        resp.raise_for_status()
        MASTER_CACHE.write_bytes(resp.content)
        log.info("Downloaded master: %d bytes", len(resp.content))

    def _parse_master(self) -> None:
        with gzip.open(MASTER_CACHE, "rt") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("exchange") == "NSE_EQ" and row.get("instrument_type") == "EQUITY":
                    symbol = row.get("tradingsymbol", "")
                    key = row.get("instrument_key", "")
                    if symbol and key:
                        self._symbol_to_key[symbol.upper()] = key
        self._master_loaded = True
        log.info("Loaded %d NSE_EQ symbols from master", len(self._symbol_to_key))

    def resolve_key(self, symbol: str) -> str | None:
        """Convert NSE symbol to Upstox instrument key (e.g. RELIANCE -> NSE_EQ|INE002A01018)."""
        self._load_master()
        return self._symbol_to_key.get(symbol.upper())

    def resolve_keys(self, symbols: list[str]) -> dict[str, str]:
        """Batch resolve symbols to instrument keys. Returns {symbol: key}."""
        self._load_master()
        result = {}
        for s in symbols:
            key = self._symbol_to_key.get(s.upper())
            if key:
                result[s.upper()] = key
        return result

    def get_live_prices(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Batch fetch live prices for symbols.

        Returns {symbol: {last_price, open, high, low, close, volume, net_change, ...}}
        Uses cache to avoid redundant API calls within CACHE_TTL_SECONDS.
        """
        now = time.time()
        result = {}
        to_fetch = []

        # Check cache first
        for sym in symbols:
            key = sym.upper()
            if key in self._cache and (now - self._cache_time.get(key, 0)) < CACHE_TTL_SECONDS:
                result[key] = self._cache[key]
            else:
                to_fetch.append(key)

        if not to_fetch:
            return result

        # Resolve instrument keys
        key_map = self.resolve_keys(to_fetch)
        if not key_map:
            return result

        instrument_keys = list(key_map.values())
        symbol_by_key = {v: k for k, v in key_map.items()}

        # Batch in groups of 20 to avoid URL length limits
        BATCH_SIZE = 20
        merged_quotes = {}
        for i in range(0, len(instrument_keys), BATCH_SIZE):
            batch = instrument_keys[i : i + BATCH_SIZE]
            try:
                client = self._get_client()
                self._ensure_token()
                batch_quotes = client.get_quotes(batch)
                merged_quotes.update(batch_quotes)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    log.info("Token expired, attempting refresh...")
                    new_token = _refresh_token()
                    if new_token:
                        client.access_token = new_token
                        try:
                            batch_quotes = client.get_quotes(batch)
                            merged_quotes.update(batch_quotes)
                        except Exception as e2:
                            log.warning("Quotes batch failed after refresh: %s", e2)
                    else:
                        log.warning("Token refresh failed, cannot fetch live prices")
                else:
                    log.warning("Upstox quotes batch failed: %s", e)
            except Exception as e:
                log.warning("Upstox quotes batch error: %s", e)

        # Parse response
        for raw_key, data in merged_quotes.items():
            symbol = symbol_by_key.get(raw_key) or raw_key.split(":")[-1]
            last_price = data.get("last_price")
            if last_price is None:
                continue
            parsed = {
                "last_price": float(last_price),
                "open": float(data.get("ohlc", {}).get("open", 0)),
                "high": float(data.get("ohlc", {}).get("high", 0)),
                "low": float(data.get("ohlc", {}).get("low", 0)),
                "close": float(data.get("ohlc", {}).get("close", 0)),
                "volume": int(data.get("volume", 0)),
                "net_change": float(data.get("net_change", 0)),
                "average_price": float(data.get("average_price", 0)),
                "upper_circuit": float(data.get("upper_circuit_limit", 0)),
                "lower_circuit": float(data.get("lower_circuit_limit", 0)),
                "timestamp": data.get("timestamp", ""),
            }
            result[symbol] = parsed
            self._cache[symbol] = parsed
            self._cache_time[symbol] = now

        return result

    def get_single_price(self, symbol: str) -> float | None:
        """Get live price for a single symbol."""
        prices = self.get_live_prices([symbol])
        data = prices.get(symbol.upper())
        return data["last_price"] if data else None

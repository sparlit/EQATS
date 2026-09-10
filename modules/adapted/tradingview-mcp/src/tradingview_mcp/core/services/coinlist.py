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


import os
from functools import lru_cache
from typing import Dict, FrozenSet, List

from ..utils.validators import COINLIST_DIR


def load_symbols(exchange: str) -> list[str]:
    """Load symbols for a given exchange, with multiple fallback strategies.

    Cached per exchange (the coinlist files ship with the package and don't
    change at runtime) — every scan used to re-read and re-parse the file.
    Returns a fresh copy so callers can't poison the cache by mutating it.
    """
    return list(_load_symbols_cached(exchange))


@lru_cache(maxsize=64)
def _load_symbols_cached(exchange: str) -> tuple:
    # Try multiple possible paths
    possible_paths = [
        os.path.join(COINLIST_DIR, f"{exchange}.txt"),
        os.path.join(COINLIST_DIR, f"{exchange.lower()}.txt"),
        # Fallback: relative to this file
        os.path.join(os.path.dirname(__file__), "..", "..", "coinlist", f"{exchange}.txt"),
        # Another fallback
        os.path.join(os.path.dirname(__file__), "..", "..", "coinlist", f"{exchange.lower()}.txt"),
    ]

    for path in possible_paths:
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                symbols = tuple(line.strip() for line in content.split("\n") if line.strip())
                if symbols:  # Only return if we actually got symbols
                    return symbols
        except (OSError, FileNotFoundError, UnicodeDecodeError):
            continue

    # If all fails, return empty tuple
    return ()


# "all.txt" is an aggregate of every exchange — suggesting it as an exchange
# would send the model straight back into an invalid `exchange` value.
_SUGGESTION_EXCLUDE = {"all"}


@lru_cache(maxsize=1)
def _coinlist_index() -> dict[str, frozenset[str]]:
    """EXCHANGE (upper) -> frozenset of its listed symbols, from local files.

    Built once per process (the coinlist directory ships with the package and
    doesn't change at runtime). Used only on error paths, so the one-time
    directory scan is not on any hot path.
    """
    index: dict[str, frozenset[str]] = {}
    try:
        names = os.listdir(COINLIST_DIR)
    except OSError:
        return index
    for name in names:
        if not name.endswith(".txt"):
            continue
        exch = name[:-4]
        if exch.lower() in _SUGGESTION_EXCLUDE:
            continue
        try:
            with open(os.path.join(COINLIST_DIR, name), encoding="utf-8") as f:
                # Lines ship as "EXCHANGE:TICKER" (e.g. "KUCOIN:HYPEUSDT");
                # index the bare ticker so lookups match either input form.
                symbols = frozenset(line.strip().upper().split(":")[-1] for line in f if line.strip())
        except (OSError, UnicodeDecodeError):
            continue
        if symbols:
            index[exch.upper()] = symbols
    return index


def exchanges_listing_symbol(symbol: str, max_results: int = 6) -> list[str]:
    """Exchanges (per the local coinlists) where *symbol* is listed.

    Zero network cost — reads only the bundled coinlist files. Accepts bare
    tickers ("HYPEUSDT") or prefixed ones ("BINANCE:HYPEUSDT"). Returns
    exchange names sorted alphabetically, capped at *max_results*; empty list
    when the ticker appears in no local list (likely a typo or an unsupported
    venue).
    """
    bare = symbol.strip().upper().split(":")[-1]
    if not bare:
        return []
    matches = sorted(exch for exch, symbols in _coinlist_index().items() if bare in symbols)
    return matches[:max_results]

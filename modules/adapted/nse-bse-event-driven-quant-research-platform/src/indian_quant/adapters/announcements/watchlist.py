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


import glob
import os
from pathlib import Path
from typing import Set

import pandas as pd

WATCHLIST_DIR = Path("/home/ubuntu/Documents/projects/real_investments/watch_list")


def _find_symbol_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        col_s = str(col).strip()
        if col_s.startswith("Symbol"):
            return col_s
    return None


class Watchlist:
    """Reads all Excel watchlist files and provides a set of stock symbols."""

    def __init__(self, watchlist_dir: str | Path = str(WATCHLIST_DIR)):
        self._dir = Path(watchlist_dir)
        self._symbols: set[str] | None = None

    def load(self) -> set[str]:
        if self._symbols is not None:
            return self._symbols
        self._symbols = set()
        if not self._dir.exists():
            return self._symbols
        for fpath in sorted(glob.glob(str(self._dir / "*.xlsx"))):
            try:
                df = pd.read_excel(fpath)
            except Exception:
                continue
            sym_col = _find_symbol_column(df)
            if sym_col:
                for val in df[sym_col].dropna():
                    sym = str(val).strip().upper()
                    if sym:
                        self._symbols.add(sym)
        return self._symbols

    @property
    def symbols(self) -> set[str]:
        return self.load()

    def __contains__(self, symbol: str) -> bool:
        return symbol.strip().upper() in self.symbols

    def __iter__(self):
        return iter(self.symbols)

    def __len__(self) -> int:
        return len(self.symbols)

    def to_list(self) -> list[str]:
        return sorted(self.symbols)

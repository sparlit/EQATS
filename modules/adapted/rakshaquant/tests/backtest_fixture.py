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


"""A deterministic multi-session daily-bar fixture for the backtest tests (plan M11.1)."""


from datetime import date

import numpy as np
import pandas as pd
from src.domain.calendar import get_calendar
from src.domain.types import Bar, Instrument, MarketDataSource, Timeframe
from src.engine.market import INDEX_KEY

REPLAY = MarketDataSource.REPLAY
START, END = date(2026, 10, 1), date(2026, 10, 16)  # the backtest window
SYMBOLS = (("INFY", "Information Technology", 1500.0), ("TCS", "Information Technology", 3900.0),
           ("SBIN", "Financial Services", 800.0), ("ITC", "Fast Moving Consumer Goods", 450.0))  # fmt: skip


def universe() -> list[Instrument]:
    return [Instrument.nse_equity(s, sector=sector) for s, sector, _ in SYMBOLS]


def _days() -> list[date]:
    history = [d.date() for d in pd.bdate_range("2025-01-01", "2025-12-31")]
    return history + get_calendar().trading_days(date(2026, 1, 1), END)


def _series(key: str, seed: int, last: float) -> list[Bar]:
    days = _days()
    rng = np.random.default_rng(seed)
    closes = last * np.exp(np.cumsum(rng.normal(0.0004, 0.014, len(days))) - 0.0)
    bars = []
    prev = closes[0]
    for day, close in zip(days, closes, strict=True):
        open_ = prev * (1 + rng.normal(0, 0.006))
        high = max(open_, close) * (1 + abs(rng.normal(0, 0.006)))
        low = min(open_, close) * (1 - abs(rng.normal(0, 0.006)))
        for adjusted in (False, True):
            bars.append(Bar(instrument_key=key, timeframe=Timeframe.D1, session_date=day,
                            open=round(open_, 2), high=round(high, 2), low=round(low, 2),
                            close=round(close, 2), volume=int(4_000_000 * (1 + rng.random())),
                            is_settled=True, adjusted=adjusted, source=REPLAY))  # fmt: skip
        prev = close
    return bars


def fixture_bars(seeds: tuple[int, ...] = (41, 42, 43, 44)) -> list[Bar]:
    bars = _series(INDEX_KEY, 5, 25_000.0)
    for (symbol, _, last), seed in zip(SYMBOLS, seeds, strict=True):
        bars += _series(f"NSE:EQ:{symbol}", seed, last)
    return bars

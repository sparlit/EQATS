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


"""Date-explicit market and sector regime classification for NSE Scanner V2."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import pandas as pd

from v2.indicators import hma

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class RegimeResult:
    as_of_date: str
    state: str
    score: int
    benchmark_above_hma: bool
    benchmark_hma_rising: bool
    breadth_above_50dma: float
    breadth_above_200dma: float

    def to_dict(self) -> dict:
        return asdict(self)


def classify_market_regime(
    benchmark: pd.DataFrame,
    breadth: pd.DataFrame,
    *,
    hma_length: int = 55,
    bull_50dma: float = 60.0,
    bull_200dma: float = 50.0,
    bear_50dma: float = 40.0,
    bear_200dma: float = 35.0,
) -> RegimeResult:
    """Classify BULL, NEUTRAL or BEAR from trend and breadth.

    `breadth` must provide `pct_above_50dma` and `pct_above_200dma` indexed on
    the same date domain as the benchmark. The latest common date is used.
    """
    required_benchmark = {"close"}
    required_breadth = {"pct_above_50dma", "pct_above_200dma"}
    if not required_benchmark.issubset(benchmark.columns):
        msg = "benchmark must contain close"
        raise ValueError(msg)
    if not required_breadth.issubset(breadth.columns):
        msg = "breadth must contain pct_above_50dma and pct_above_200dma"
        raise ValueError(msg)

    common = benchmark.index.intersection(breadth.index)
    if common.empty:
        msg = "benchmark and breadth have no common dates"
        raise ValueError(msg)
    date = common.max()
    close = pd.to_numeric(benchmark.loc[common, "close"], errors="coerce")
    baseline = hma(close, hma_length)
    current_close = float(close.loc[date])
    current_hma = float(baseline.loc[date])
    prior_hma = float(baseline.shift(1).loc[date])
    above_hma = current_close > current_hma
    rising_hma = current_hma > prior_hma
    above_50 = float(breadth.loc[date, "pct_above_50dma"])
    above_200 = float(breadth.loc[date, "pct_above_200dma"])

    score = int(above_hma) + int(rising_hma)
    score += int(above_50 >= bull_50dma) + int(above_200 >= bull_200dma)

    if above_hma and rising_hma and above_50 >= bull_50dma and above_200 >= bull_200dma:
        state = "BULL"
    elif (not above_hma) and (not rising_hma) and above_50 <= bear_50dma and above_200 <= bear_200dma:
        state = "BEAR"
    else:
        state = "NEUTRAL"

    return RegimeResult(
        as_of_date=pd.Timestamp(date).date().isoformat(),
        state=state,
        score=score,
        benchmark_above_hma=above_hma,
        benchmark_hma_rising=rising_hma,
        breadth_above_50dma=above_50,
        breadth_above_200dma=above_200,
    )


def rank_relative_strength(scores: Mapping[str, float]) -> pd.DataFrame:
    """Rank symbols without static sector preference or manual bias."""
    frame = pd.DataFrame([(symbol, value) for symbol, value in scores.items()], columns=["symbol", "rs_score"]).dropna()
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "rs_score", "rs_rank", "rs_percentile"])
    frame = frame.sort_values(["rs_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    frame["rs_rank"] = frame.index + 1
    count = len(frame)
    frame["rs_percentile"] = 100.0 * (count - frame["rs_rank"] + 1) / count
    return frame

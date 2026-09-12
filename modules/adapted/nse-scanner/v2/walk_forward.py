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


"""Parameter sensitivity and anchored walk-forward validation for V2."""

from dataclasses import asdict, dataclass

import pandas as pd

from .backtest import run_point_in_time_backtest
from .performance import summarize_performance


@dataclass(frozen=True)
class ValidationRow:
    label: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    minimum_score: float
    train_expectancy_r: float
    test_expectancy_r: float
    test_trades: int
    test_max_drawdown_r: float

    def to_dict(self) -> dict:
        return asdict(self)


def score_sensitivity(
    prices: pd.DataFrame,
    thresholds: tuple[float, ...] = (65.0, 70.0, 75.0, 80.0),
    **backtest_kwargs: object,
) -> list[dict]:
    rows = []
    for threshold in thresholds:
        trades = run_point_in_time_backtest(
            prices,
            minimum_score=threshold,
            **backtest_kwargs,
        )
        report = summarize_performance(trades)
        rows.append({"minimum_score": threshold, **report.to_dict()})
    return rows


def anchored_walk_forward(
    prices: pd.DataFrame,
    *,
    train_sessions: int = 252,
    test_sessions: int = 63,
    thresholds: tuple[float, ...] = (65.0, 70.0, 75.0, 80.0),
    warmup_sessions: int = 120,
    max_positions: int = 10,
) -> list[ValidationRow]:
    """Select a score threshold on past data and evaluate the next unseen block."""
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    dates = sorted(frame["trade_date"].drop_duplicates())
    rows: list[ValidationRow] = []
    test_start_index = train_sessions
    fold = 1
    while test_start_index < len(dates):
        test_end_index = min(test_start_index + test_sessions, len(dates))
        train_dates = dates[:test_start_index]
        test_dates = dates[:test_end_index]  # includes training history as warmup context
        training = frame[frame["trade_date"].isin(train_dates)]
        best_threshold = thresholds[0]
        best_expectancy = float("-inf")
        for threshold in thresholds:
            report = summarize_performance(
                run_point_in_time_backtest(
                    training,
                    minimum_score=threshold,
                    warmup_sessions=warmup_sessions,
                    max_positions=max_positions,
                )
            )
            if report.expectancy_r > best_expectancy:
                best_expectancy = report.expectancy_r
                best_threshold = threshold

        combined = frame[frame["trade_date"].isin(test_dates)]
        trades = run_point_in_time_backtest(
            combined,
            minimum_score=best_threshold,
            warmup_sessions=max(warmup_sessions, test_start_index),
            max_positions=max_positions,
        )
        test_start = pd.Timestamp(dates[test_start_index])
        test_end = pd.Timestamp(dates[test_end_index - 1])
        test_trades = [
            trade
            for trade in trades
            if trade.signal_date >= test_start.date().isoformat() and trade.signal_date <= test_end.date().isoformat()
        ]
        test_report = summarize_performance(test_trades)
        rows.append(
            ValidationRow(
                label=f"fold_{fold}",
                train_start=pd.Timestamp(train_dates[0]).date().isoformat(),
                train_end=pd.Timestamp(train_dates[-1]).date().isoformat(),
                test_start=test_start.date().isoformat(),
                test_end=test_end.date().isoformat(),
                minimum_score=best_threshold,
                train_expectancy_r=round(best_expectancy, 4),
                test_expectancy_r=test_report.expectancy_r,
                test_trades=test_report.entered_trades,
                test_max_drawdown_r=test_report.max_drawdown_r,
            )
        )
        fold += 1
        test_start_index = test_end_index
    return rows

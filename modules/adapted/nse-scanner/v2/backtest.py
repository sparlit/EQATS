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


"""Point-in-time backtesting for NSE Scanner V2.

Signals are evaluated only with information available on each scan date. Daily OHLC
execution reuses the production lifecycle processor and its conservative stop-first
collision policy.
"""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .candidates import evaluate_candidate
from .indicators import atr
from .lifecycle import Position, TradeState, new_position
from .lifecycle_processor import process_daily_bar

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class BacktestTrade:
    trade_id: str
    symbol: str
    horizon: str
    setup: str
    signal_date: str
    entry_date: str | None
    exit_date: str | None
    entry: float
    initial_stop: float
    target1: float
    target2: float
    exit_price: float | None
    state: str
    realised_r: float
    holding_sessions: int
    score: float
    exit_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _bar_with_atr(history: pd.DataFrame) -> dict[str, float]:
    row = history.iloc[-1].to_dict()
    atr14 = atr(history, 14).iloc[-1]
    if pd.notna(atr14):
        row["atr14"] = float(atr14)
    return row


def _realised_r(position: Position, initial_stop: float, partial_fraction: float) -> float:
    risk = position.entry - initial_stop
    if risk <= 0 or position.exit_price is None:
        return 0.0
    if position.realised_quantity <= 0:
        return 0.0
    # T1 is the only modeled partial realization before final exit.
    partial_qty = min(position.quantity * partial_fraction, position.realised_quantity)
    final_qty = max(0.0, position.realised_quantity - partial_qty)
    pnl = partial_qty * (position.target1 - position.entry)
    pnl += final_qty * (position.exit_price - position.entry)
    return float(pnl / (position.quantity * risk))


def run_point_in_time_backtest(
    prices: pd.DataFrame,
    regime_by_date: Mapping[str, str] | None = None,
    *,
    minimum_score: float = 70.0,
    warmup_sessions: int = 120,
    max_positions: int = 10,
    partial_fraction: float = 0.5,
    force_exit_at_end: bool = True,
) -> list[BacktestTrade]:
    """Run a deterministic portfolio backtest without future-data leakage."""
    required = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
    missing = required - set(prices.columns)
    if missing:
        msg = f"prices missing columns: {sorted(missing)}"
        raise ValueError(msg)
    data = prices.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"])
    data = data.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    dates = sorted(data["trade_date"].drop_duplicates())
    active: dict[str, dict] = {}
    completed: list[BacktestTrade] = []

    for scan_index, scan_date in enumerate(dates):
        date_text = pd.Timestamp(scan_date).date().isoformat()
        todays = data[data["trade_date"] == scan_date]

        # First process positions created on earlier dates against today's completed bar.
        for symbol in list(active):
            item = active[symbol]
            row = todays[todays["symbol"] == symbol]
            if row.empty:
                continue
            history = data[(data["symbol"] == symbol) & (data["trade_date"] <= scan_date)]
            events = process_daily_bar(
                item["position"],
                date_text,
                _bar_with_atr(history),
                partial_fraction=partial_fraction,
            )
            if events:
                item["position"] = events[-1].position
                if item["entry_date"] is None and any(event.event_type == "ENTER" for event in events):
                    item["entry_date"] = date_text
                item["holding_sessions"] += int(item["entry_date"] is not None)
            position = item["position"]
            if position.state in {TradeState.CLOSED, TradeState.CANCELLED}:
                completed.append(
                    BacktestTrade(
                        trade_id=position.trade_id,
                        symbol=symbol,
                        horizon=position.horizon,
                        setup=item["setup"],
                        signal_date=item["signal_date"],
                        entry_date=item["entry_date"],
                        exit_date=date_text,
                        entry=position.entry,
                        initial_stop=item["initial_stop"],
                        target1=position.target1,
                        target2=position.target2,
                        exit_price=position.exit_price,
                        state=position.state.value,
                        realised_r=_realised_r(position, item["initial_stop"], partial_fraction),
                        holding_sessions=item["holding_sessions"],
                        score=item["score"],
                        exit_reason=position.reason,
                    )
                )
                del active[symbol]

        if scan_index < warmup_sessions or len(active) >= max_positions:
            continue

        regime = (regime_by_date or {}).get(date_text, "NEUTRAL")
        available_slots = max_positions - len(active)
        candidates = []
        history_to_date = data[data["trade_date"] <= scan_date]
        for symbol, history in history_to_date.groupby("symbol"):
            symbol = str(symbol)
            if symbol in active:
                continue
            candidate = evaluate_candidate(
                symbol,
                history,
                regime,
                stale_data=False,
                minimum_score=minimum_score,
            )
            if candidate.selected:
                candidates.append(candidate)
        candidates.sort(key=lambda c: (-c.score, c.symbol))

        for candidate in candidates[:available_slots]:
            position = new_position(
                candidate.symbol,
                candidate.horizon,
                candidate.trade_date,
                candidate.entry,
                candidate.stop,
                candidate.target1,
                candidate.target2,
            )
            active[candidate.symbol] = {
                "position": position,
                "setup": candidate.setup,
                "signal_date": date_text,
                "entry_date": None,
                "initial_stop": candidate.stop,
                "holding_sessions": 0,
                "score": candidate.score,
            }

    if force_exit_at_end and dates:
        final_date = pd.Timestamp(dates[-1]).date().isoformat()
        for symbol, item in active.items():
            position = item["position"]
            final_row = data[data["symbol"] == symbol].iloc[-1]
            exit_price = float(final_row["close"])
            if position.state in {TradeState.OPEN, TradeState.PARTIAL, TradeState.TRAILING}:
                from .lifecycle import transition

                position = transition(position, "EXIT", final_date, price=exit_price, reason="backtest_end_exit")
            completed.append(
                BacktestTrade(
                    trade_id=position.trade_id,
                    symbol=symbol,
                    horizon=position.horizon,
                    setup=item["setup"],
                    signal_date=item["signal_date"],
                    entry_date=item["entry_date"],
                    exit_date=final_date,
                    entry=position.entry,
                    initial_stop=item["initial_stop"],
                    target1=position.target1,
                    target2=position.target2,
                    exit_price=position.exit_price,
                    state=position.state.value,
                    realised_r=_realised_r(position, item["initial_stop"], partial_fraction),
                    holding_sessions=item["holding_sessions"],
                    score=item["score"],
                    exit_reason=position.reason,
                )
            )
    return completed

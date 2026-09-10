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
Portfolio Tracker
─────────────────
Real-time intraday P&L and position-level mark-to-market tracking.

Tracks:
  - Open positions with entry price, qty, current price
  - Unrealized P&L per position
  - Total portfolio unrealized + realized P&L
  - Intraday equity curve

Missing from the original system — added to enable:
  - Real-time portfolio risk monitoring
  - Position-level stop management
  - Total exposure tracking
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("portfolio_tracker")


@dataclass
class Position:
    """A single open position."""

    symbol: str
    direction: str  # CALL / PUT
    entry_price: float
    current_price: float
    quantity: int
    entry_time: datetime
    stop_loss: float = 0.0
    target: float = 0.0
    order_id: str = ""

    @property
    def unrealized_pnl(self) -> float:
        if self.direction == "CALL":
            return (self.current_price - self.entry_price) * self.quantity
        return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        return self.unrealized_pnl / (self.entry_price * self.quantity) * 100

    @property
    def is_profitable(self) -> bool:
        return self.unrealized_pnl > 0


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state."""

    timestamp: datetime
    open_positions: int
    total_unrealized_pnl: float
    total_realized_pnl: float
    total_equity: float  # capital + unrealized + realized
    max_exposure: float  # sum of (entry_price * qty) across positions


class PortfolioTracker:
    """
    Tracks all open positions and computes real-time portfolio P&L.

    Usage:
      tracker = PortfolioTracker(capital=50000)
      tracker.open_position("NIFTY24500CE", "CALL", 200, 2, stop_loss=180, target=230)
      tracker.update_price("NIFTY24500CE", 210)
      print(tracker.summary())
      tracker.close_position("NIFTY24500CE", 225)
    """

    def __init__(self, capital: float = 50000.0):
        self.initial_capital = capital
        self._positions: dict[str, Position] = {}
        self._realized_pnl: float = 0.0
        self._closed_trades_today: int = 0
        self._current_date: date | None = None
        self._equity_curve: list[PortfolioSnapshot] = []

    def _reset_if_new_day(self):
        today = date.today()
        if today != self._current_date:
            self._current_date = today
            self._realized_pnl = 0.0
            self._closed_trades_today = 0
            self._equity_curve = []

    # ── Position Management ─────────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: int,
        stop_loss: float = 0.0,
        target: float = 0.0,
        order_id: str = "",
    ):
        """Register a new open position."""
        self._reset_if_new_day()

        if symbol in self._positions:
            logger.warning(f"Position already open for {symbol}. Updating.")

        self._positions[symbol] = Position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            current_price=entry_price,
            quantity=quantity,
            entry_time=datetime.now(),
            stop_loss=stop_loss,
            target=target,
            order_id=order_id,
        )
        logger.info(
            f"Position opened: {symbol} {direction} qty={quantity} entry={entry_price} SL={stop_loss} TGT={target}"
        )

    def close_position(self, symbol: str, exit_price: float) -> float:
        """
        Close a position and move P&L to realized.
        Returns the realized P&L for this trade.
        """
        if symbol not in self._positions:
            logger.warning(f"No open position for {symbol}")
            return 0.0

        pos = self._positions.pop(symbol)
        pos.current_price = exit_price
        pnl = pos.unrealized_pnl

        self._realized_pnl += pnl
        self._closed_trades_today += 1

        logger.info(
            f"Position closed: {symbol} exit={exit_price} PnL=₹{pnl:,.2f} (realized total: ₹{self._realized_pnl:,.2f})"
        )
        return pnl

    def update_price(self, symbol: str, current_price: float):
        """Update the current market price for an open position."""
        if symbol in self._positions:
            self._positions[symbol].current_price = current_price

    def update_prices(self, prices: dict[str, float]):
        """Bulk update prices from tick/bar data."""
        for symbol, price in prices.items():
            self.update_price(symbol, price)

    # ── Portfolio Metrics ───────────────────────────────────────────────

    @property
    def open_positions(self) -> list[Position]:
        return list(self._positions.values())

    @property
    def open_position_count(self) -> int:
        return len(self._positions)

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self._positions.values())

    @property
    def total_realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def total_pnl(self) -> float:
        return self._realized_pnl + self.total_unrealized_pnl

    @property
    def total_equity(self) -> float:
        return self.initial_capital + self.total_pnl

    @property
    def total_exposure(self) -> float:
        """Sum of entry_price * quantity across all open positions."""
        return sum(p.entry_price * p.quantity for p in self._positions.values())

    @property
    def daily_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return self.total_pnl / self.initial_capital * 100

    # ── Snapshot / Equity Curve ─────────────────────────────────────────

    def take_snapshot(self) -> PortfolioSnapshot:
        """Record current portfolio state for equity curve."""
        snap = PortfolioSnapshot(
            timestamp=datetime.now(),
            open_positions=self.open_position_count,
            total_unrealized_pnl=round(self.total_unrealized_pnl, 2),
            total_realized_pnl=round(self._realized_pnl, 2),
            total_equity=round(self.total_equity, 2),
            max_exposure=round(self.total_exposure, 2),
        )
        self._equity_curve.append(snap)
        return snap

    @property
    def equity_curve(self) -> list[PortfolioSnapshot]:
        return self._equity_curve

    # ── Summary ─────────────────────────────────────────────────────────

    def summary(self) -> str:
        """Human-readable portfolio summary."""
        lines = [
            "═" * 50,
            "PORTFOLIO STATUS",
            "═" * 50,
            f"  Open positions:   {self.open_position_count}",
            f"  Unrealized P&L:   ₹{self.total_unrealized_pnl:,.2f}",
            f"  Realized P&L:     ₹{self._realized_pnl:,.2f}",
            f"  Total P&L:        ₹{self.total_pnl:,.2f}",
            f"  Total equity:     ₹{self.total_equity:,.2f}",
            f"  Daily return:     {self.daily_return_pct:.2f}%",
            f"  Total exposure:   ₹{self.total_exposure:,.2f}",
            f"  Trades closed:    {self._closed_trades_today}",
        ]

        if self._positions:
            lines.append("─" * 50)
            lines.append("  OPEN POSITIONS:")
            for pos in self._positions.values():
                lines.append(
                    f"    {pos.symbol} {pos.direction} qty={pos.quantity} "
                    f"entry={pos.entry_price:.2f} curr={pos.current_price:.2f} "
                    f"PnL=₹{pos.unrealized_pnl:,.2f} ({pos.unrealized_pnl_pct:+.1f}%)"
                )

        lines.append("═" * 50)
        return "\n".join(lines)

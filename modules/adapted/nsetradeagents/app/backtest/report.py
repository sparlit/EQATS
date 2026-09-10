import csv
import datetime
import math
from datetime import date

import pytz
from app.core.config import settings

from ..engine import ClosedTrade


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


def _cagr(start_val: float, end_val: float, years: float) -> float:
    """Compound annual growth rate between two portfolio values."""
    if years <= 0 or start_val <= 0:
        return 0.0
    return (end_val / start_val) ** (1 / years) - 1


def _sharpe(daily_returns: list[float]) -> float:
    """Annualised Sharpe ratio from daily returns, assuming a zero risk-free rate."""
    n = len(daily_returns)
    if n < 2:
        return 0.0
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    std = math.sqrt(variance)
    return (mean / std) * math.sqrt(252) if std > 0 else 0.0


def _max_drawdown(equity_curve: list[tuple[date, float]]) -> float:
    """Largest peak-to-trough fall in the equity curve, as a percentage."""
    peak = 0.0
    max_dd = 0.0
    for _, val in equity_curve:
        peak = max(peak, val)
        if peak > 0:
            max_dd = max(max_dd, (peak - val) / peak)
    return max_dd


def _yearly_breakdown(trades: list[ClosedTrade], equity_curve: list[tuple[date, float]]):
    # Build year → (first_equity, last_equity) from the curve
    """Print per-year return, trade count, win rate, profit factor and drawdown."""
    year_equity: dict[int, tuple[float, float]] = {}
    for dt, val in equity_curve:
        y = dt.year
        if y not in year_equity:
            year_equity[y] = (val, val)
        else:
            year_equity[y] = (year_equity[y][0], val)

    completed = [t for t in trades if t.exit_reason != "end_of_backtest"]

    print()
    print("=" * 57)
    print("  YEAR-BY-YEAR BREAKDOWN")
    print(f"  {'Year':<6} {'Return':>8} {'Trades':>8} {'Win%':>7} {'PF':>6} {'MaxDD':>7}")
    print("-" * 57)

    all_years = sorted(year_equity.keys())
    for y in all_years:
        start_eq, end_eq = year_equity[y]
        (end_eq - start_eq) / start_eq * 100 if start_eq > 0 else 0.0

        year_trades = [t for t in completed if t.exit_date.year == y]
        [t for t in year_trades if t.pnl > 0]
        [t for t in year_trades if t.pnl <= 0]

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


import csv
import math
from datetime import date

from app.backtest.engine import ClosedTrade
from app.core.config import settings


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
        ret = (end_eq - start_eq) / start_eq * 100 if start_eq > 0 else 0.0

        year_trades = [t for t in completed if t.exit_date.year == y]
        wins = [t for t in year_trades if t.pnl > 0]
        losses = [t for t in year_trades if t.pnl <= 0]
        win_pct = len(wins) / len(year_trades) * 100 if year_trades else 0.0
        gross_loss = sum(t.pnl for t in losses)
        pf = sum(t.pnl for t in wins) / abs(gross_loss) if gross_loss != 0 else float("inf")

        # Max drawdown within the year
        year_curve = [(dt, v) for dt, v in equity_curve if dt.year == y]
        peak, max_dd = 0.0, 0.0
        for _, v in year_curve:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak * 100)

        pf_str = f"{pf:.2f}" if pf != float("inf") else "  ∞"
        print(f"  {y:<6} {ret:>+7.1f}%  {len(year_trades):>6}  {win_pct:>6.1f}%  {pf_str:>5}  {max_dd:>5.1f}%")

    print("=" * 57)


def _score_analysis(trades: list[ClosedTrade], all_scores: list[int]):
    """Print how scores were distributed and how each score band performed.

    Buckets are derived from the entry threshold rather than hardcoded, so
    they stay meaningful when the threshold moves.
    """
    threshold = int(settings.rules_confidence_threshold)

    # Buckets are derived, not hardcoded: the score scale and the entry
    # threshold have both moved before, and literals silently went stale.
    def _buckets(start: int) -> list[tuple[int, int]]:
        """10-wide buckets from `start`, with the last one closing on 100.

        A perfect score of 100 is reachable, so the top bucket must include it.
        """
        lows = list(range(start, 100, 10))
        return [(lo, lows[i + 1] - 1 if i + 1 < len(lows) else 100) for i, lo in enumerate(lows)]

    dist_buckets = _buckets(0)
    outcome_buckets = _buckets(threshold)

    print()
    print("=" * 57)
    print("  SCORE DISTRIBUTION  (all signals that passed tech gate)")
    print(f"  entry threshold = {threshold}  (marked ►)")
    print("=" * 57)
    total = len(all_scores)
    for lo, hi in dist_buckets:
        count = sum(1 for s in all_scores if lo <= s <= hi)
        bar = "█" * (count * 30 // max(total, 1))
        mark = "►" if lo <= threshold <= hi else " "
        label = f"{lo:>3}-{hi:>3}"
        print(f" {mark}{label} : {bar:<30} {count:>5}  ({count / max(total, 1) * 100:.1f}%)")

    print()
    print("=" * 57)
    print("  SCORE → OUTCOME  (entered trades only)")
    print(f"  {'Bucket':<8} {'Trades':>7} {'Win%':>7} {'AvgP&L%':>9} {'AvgHold':>9}")
    print("-" * 57)
    completed = [t for t in trades if t.exit_reason != "end_of_backtest"]
    for lo, hi in outcome_buckets:
        bucket = [t for t in completed if lo <= t.score <= hi]
        if not bucket:
            continue
        wins = [t for t in bucket if t.pnl > 0]
        win_pct = len(wins) / len(bucket) * 100
        avg_pnl = sum(t.pnl_pct for t in bucket) / len(bucket)
        avg_hold = sum((t.exit_date - t.entry_date).days for t in bucket) / len(bucket)
        print(f"  {lo}-{hi:<3}    {len(bucket):>7} {win_pct:>7.1f} {avg_pnl:>+9.2f} {avg_hold:>9.1f}d")
    print("=" * 57)


def print_report(
    trades: list[ClosedTrade],
    equity_curve: list[tuple[date, float]],
    all_scores: list[int] | None = None,
    csv_path: str = "backtest_trades.csv",
):
    """Print the full backtest report and optionally write the trade log to CSV.

    Covers headline metrics, the yearly breakdown, and the score analysis when
    candidate scores are supplied.
    """
    if not equity_curve:
        print("No equity curve - did not ingest run")
        return

    start_val = equity_curve[0][1]
    end_val = equity_curve[-1][1]
    start_date = equity_curve[0][0]
    end_date = equity_curve[-1][0]
    years = (end_date - start_date).days / 365.25

    total_return = (end_val - start_val) / start_val * 100
    cagr = _cagr(start_val, end_val, years) * 100

    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev, curr = equity_curve[i - 1][1], equity_curve[i][1]
        if prev > 0:
            daily_returns.append((curr - prev) / prev)

    sharpe = _sharpe(daily_returns)
    max_dd = _max_drawdown(equity_curve) * 100

    completed = [t for t in trades if t.exit_reason != "end_of_backtest"]
    wins = [t for t in completed if t.pnl > 0]
    losses = [t for t in completed if t.pnl <= 0]

    win_rate = len(wins) / len(completed) * 100 if completed else 0.0
    gross_loss = sum(t.pnl for t in losses)
    profit_factor = sum(t.pnl for t in wins) / abs(gross_loss) if gross_loss != 0 else float("inf")
    avg_hold = sum((t.exit_date - t.entry_date).days for t in completed) / len(completed) if completed else 0.0

    exit_counts: dict[str, int] = {}
    for t in completed:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    print()
    print("=" * 57)
    print("  BACKTEST RESULTS")
    print("=" * 57)
    print(f"  Period         : {start_date} → {end_date}")
    print(f"  Starting cap   : ₹{start_val:>12,.0f}")
    print(f"  Ending cap     : ₹{end_val:>12,.0f}")
    print(f"  Total return   : {total_return:>+.1f}%")
    print(f"  CAGR           : {cagr:>+.1f}%")
    print(f"  Sharpe ratio   : {sharpe:.2f}")
    print(f"  Max drawdown   : {max_dd:.1f}%")
    print("-" * 57)
    print(f"  Total trades   : {len(completed)}")
    print(f"  Win rate       : {win_rate:.1f}%")
    print(f"  Profit factor  : {profit_factor:.2f}")
    print(f"  Avg hold days  : {avg_hold:.1f}")
    print(
        f"  Exits          : stop={exit_counts.get('stop', 0)}  "
        f"target={exit_counts.get('target', 0)}  "
        f"timeout={exit_counts.get('timeout', 0)}  "
        f"trail={exit_counts.get('trail', 0)}"
    )
    print("=" * 57)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ticker",
                "entry_date",
                "exit_date",
                "entry_price",
                "exit_price",
                "shares",
                "pnl",
                "pnl_pct",
                "exit_reason",
                "score",
            ],
        )
        writer.writeheader()
        for t in trades:
            writer.writerow(
                {
                    "ticker": t.ticker,
                    "entry_date": t.entry_date.isoformat(),
                    "exit_date": t.exit_date.isoformat(),
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "shares": t.shares,
                    "pnl": round(t.pnl, 2),
                    "pnl_pct": round(t.pnl_pct, 2),
                    "exit_reason": t.exit_reason,
                    "score": t.score,
                }
            )

    print(f"\n  Trade log → {csv_path}")

    _yearly_breakdown(trades, equity_curve)

    if all_scores:
        _score_analysis(trades, all_scores)

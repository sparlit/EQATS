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
Validation harness for the cross-sectional "stocks in play" scan mode.

Walk-forward: arm_history is bootstrapped strictly before the test window;
the engine records each test day only after deciding it, so nothing leaks.

Usage:
    python scan_validate.py [start] [end] [history_days]
"""

import os
import sqlite3
import sys

os.environ.setdefault("ALGO_CACHE_ONLY", "1")  # cache-only: no API storms

import selector as sel
from backtest import run


def purge_old_versions() -> None:
    """Drop arm_history rows from older feature versions (they're ignored by
    the selector anyway, but they make has_day() trigger full-day rebuilds)."""
    with sqlite3.connect(sel.DB_PATH) as con:
        n = con.execute(
            "DELETE FROM arm_history WHERE features NOT LIKE ?",
            (f'%"__feature_version": {sel.FEATURE_VERSION}%',),
        ).rowcount
    print(f"Purged {n} stale arm_history rows")


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "2026-04-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-05-29"
    history_days = int(sys.argv[3]) if len(sys.argv) > 3 else 180

    sel.init_history()
    purge_old_versions()

    results = run(
        symbols=[],  # scan mode supplies the universe
        start_date=start,
        end_date=end,
        capital=500_000,
        interval="5m",
        save_to_db=False,
        scan_universe=True,
        max_positions=3,
        history_days=history_days,
    )

    s = results["summary"]
    print("\n══ SCAN-MODE VALIDATION ══")
    print(f"{start} → {end}   capital ₹5,00,000")
    for k in (
        "total_trades",
        "wins",
        "losses",
        "win_rate",
        "pnl",
        "return_pct",
        "profit_factor",
        "expectancy",
        "avg_win",
        "avg_loss",
        "max_drawdown",
        "sharpe",
    ):
        print(f"  {k:<14} {s[k]}")

    by_sym: dict = {}
    by_strat: dict = {}
    for t in results["trades"]:
        by_sym.setdefault(t.symbol, []).append(t.pnl)
        by_strat.setdefault(t.strategy, []).append(t.pnl)
    print("\n  By strategy:")
    for k, v in sorted(by_strat.items()):
        print(f"    {k:<28} n={len(v):<3} pnl={sum(v):+10.2f}")
    print("\n  By symbol:")
    for k, v in sorted(by_sym.items(), key=lambda kv: -sum(kv[1])):
        print(f"    {k:<14} n={len(v):<3} pnl={sum(v):+10.2f}")


if __name__ == "__main__":
    main()

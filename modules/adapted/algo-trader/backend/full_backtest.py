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
full_backtest.py — comprehensive long-range backtest in yearly batches.

Runs year-by-year so you see progress after each batch and partial results
are saved even if it crashes partway through.

Data availability:
    Upstox:   1-minute history from ~2023-01-01 (resampled to 5m)
    yfinance: 5m limited to last 60 days (fallback for recent data only)

Usage:
    python full_backtest.py
    python full_backtest.py --start 2023-01-01 --end 2026-05-30
    python full_backtest.py --symbols HDFCBANK ICICIBANK RELIANCE SBIN TCS
    python full_backtest.py --out my_report.md
"""

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date

DEFAULT_SYMBOLS = [
    "HDFCBANK",
    "ICICIBANK",
    "RELIANCE",
    "BAJFINANCE",
    "SBIN",
]


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default=date.today().strftime("%Y-%m-%d"))
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--out", default=None)
    p.add_argument("--symbols", nargs="+", default=None)
    return p.parse_args()


def _year_batches(start: str, end: str) -> list[tuple[str, str]]:
    """Split [start, end] into per-year chunks."""
    s_year = int(start[:4])
    e_year = int(end[:4])
    batches = []
    for y in range(s_year, e_year + 1):
        b_start = start if y == s_year else f"{y}-01-01"
        b_end = end if y == e_year else f"{y}-12-31"
        batches.append((b_start, b_end))
    return batches


def _period_stats(trades: list, period_label: str) -> dict:
    if not trades:
        return {
            "period": period_label,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "pnl": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_sum = sum(t.pnl for t in wins)
    loss_sum = abs(sum(t.pnl for t in losses))
    n = len(trades)
    return {
        "period": period_label,
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1),
        "pnl": round(sum(t.pnl for t in trades), 2),
        "profit_factor": round(win_sum / loss_sum, 2) if loss_sum else 99.99,
        "avg_win": round(win_sum / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-loss_sum / len(losses), 2) if losses else 0.0,
    }


def _group_by(trades, key_fn):
    groups = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)
    return groups


def _clean(v):
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, dict):
        return {k: _clean(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_clean(i) for i in v]
    return v


def _build_report(all_trades, all_daily_pnl, all_regime_stats, args, symbols, capital) -> str:
    lines = []
    lines.append("# Backtest Report")
    lines.append("")
    lines.append(f"**Range:** {args.start} → {args.end}  ")
    lines.append(f"**Symbols:** {', '.join(s.replace('.NS', '') for s in symbols)}  ")
    lines.append(f"**Capital:** ₹{capital:,.0f}  ")
    lines.append("**Strategy:** ORB with regime-aware selection  ")
    lines.append("")

    # Overall summary
    wins = [t for t in all_trades if t.pnl > 0]
    losses = [t for t in all_trades if t.pnl <= 0]
    win_sum = sum(t.pnl for t in wins)
    loss_sum = abs(sum(t.pnl for t in losses))
    total_pnl = sum(t.pnl for t in all_trades)
    n = len(all_trades)

    import numpy as np

    if len(all_daily_pnl) >= 5:
        sorted_days = sorted(all_daily_pnl)
        daily_returns = [all_daily_pnl[d] / capital for d in sorted_days]
        mean_r = np.mean(daily_returns)
        std_r = np.std(daily_returns)
        sharpe = round((mean_r / std_r) * np.sqrt(252), 2) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    eq = capital
    peak = capital
    max_dd = 0.0
    for d in sorted(all_daily_pnl):
        eq += all_daily_pnl[d]
        peak = max(peak, eq)
        max_dd = min(max_dd, (eq - peak) / peak * 100)

    summary = {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1) if n else 0,
        "pnl": round(total_pnl, 2),
        "return_pct": round(total_pnl / capital * 100, 2),
        "profit_factor": round(win_sum / loss_sum, 2) if loss_sum else 99.99,
        "avg_win": round(win_sum / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-loss_sum / len(losses), 2) if losses else 0.0,
        "max_drawdown": round(max_dd, 2),
        "sharpe": sharpe,
        "start_eq": capital,
        "end_eq": round(capital + total_pnl, 2),
    }

    lines.append("## Overall Summary")
    lines.append("```json")
    lines.append(json.dumps(_clean(summary), indent=2))
    lines.append("```")
    lines.append("")

    # Regime breakdown
    lines.append("## Regime Breakdown")
    lines.append("```json")
    lines.append(json.dumps(_clean(all_regime_stats), indent=2))
    lines.append("```")
    lines.append("")

    # Per-symbol
    sym_groups = _group_by(all_trades, lambda t: t.symbol.replace(".NS", ""))
    per_sym = sorted([_period_stats(sym_groups[s], s) for s in sym_groups], key=lambda x: x["pnl"], reverse=True)
    lines.append("## Per-Symbol Breakdown")
    lines.append("```json")
    lines.append(json.dumps(_clean(per_sym), indent=2))
    lines.append("```")
    lines.append("")

    # Yearly
    year_groups = _group_by(all_trades, lambda t: t.date[:4])
    yearly = [_period_stats(year_groups[y], y) for y in sorted(year_groups)]
    lines.append("## Yearly Breakdown")
    lines.append("```json")
    lines.append(json.dumps(_clean(yearly), indent=2))
    lines.append("```")
    lines.append("")

    # Monthly
    month_groups = _group_by(all_trades, lambda t: t.date[:7])
    monthly = [_period_stats(month_groups[m], m) for m in sorted(month_groups)]
    lines.append("## Monthly Breakdown")
    lines.append("```json")
    lines.append(json.dumps(_clean(monthly), indent=2))
    lines.append("```")
    lines.append("")

    # Daily (only days with trades)
    day_groups = _group_by(all_trades, lambda t: t.date)
    daily = [_period_stats(day_groups[d], d) for d in sorted(day_groups)]
    lines.append("## Daily Breakdown")
    lines.append("```json")
    lines.append(json.dumps(_clean(daily), indent=2))
    lines.append("```")
    lines.append("")

    # Raw trades
    raw = [
        {
            "date": t.date,
            "symbol": t.symbol.replace(".NS", ""),
            "side": t.side,
            "regime": t.regime,
            "strategy": t.strategy,
            "entry_time": str(t.entry_time),
            "exit_time": str(t.exit_time),
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "sl_price": t.sl_price,
            "tp_price": t.tp_price,
            "shares": t.shares,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "exit_reason": t.exit_reason,
        }
        for t in all_trades
    ]
    lines.append("## All Trades")
    lines.append("```json")
    lines.append(json.dumps(_clean(raw), indent=2))
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main():
    args = _parse_args()

    raw_symbols = args.symbols or DEFAULT_SYMBOLS
    symbols = [s if s.endswith(".NS") else f"{s}.NS" for s in raw_symbols]

    out_file = args.out or f"report_{args.start}_{args.end}.md"
    if not os.path.isabs(out_file):
        out_file = os.path.join(os.path.dirname(__file__), out_file)

    try:
        from upstox_data import is_configured

        if not is_configured():
            print("WARNING: Upstox token not configured. Run: python backend/upstox_setup.py")
    except ImportError:
        pass

    sys.path.insert(0, os.path.dirname(__file__))
    from backtest import run

    batches = _year_batches(args.start, args.end)

    print(f"\n{'=' * 60}")
    print(f"  Full Backtest — {len(batches)} yearly batch(es)")
    print(f"  Range   : {args.start} → {args.end}")
    print(f"  Symbols : {', '.join(s.replace('.NS', '') for s in symbols)}")
    print(f"  Capital : ₹{args.capital:,.0f}")
    print(f"  Output  : {out_file}")
    print(f"{'=' * 60}\n")

    all_trades = []
    all_daily_pnl = {}
    all_regime_stats = {
        "trending": {"trades": 0, "wins": 0, "pnl": 0.0, "days": 0},
        "sideways": {"trades": 0, "wins": 0, "pnl": 0.0, "days": 0},
        "high_vol": {"trades": 0, "wins": 0, "pnl": 0.0, "days": 0},
    }
    running_capital = args.capital  # equity carries forward across years

    for i, (b_start, b_end) in enumerate(batches):
        print(f"\n[Batch {i + 1}/{len(batches)}] {b_start} → {b_end}  (equity: ₹{running_capital:,.0f})")
        try:
            results = run(
                symbols=symbols,
                start_date=b_start,
                end_date=b_end,
                capital=running_capital,
                save_to_db=True,
            )
        except Exception as e:
            print(f"  ERROR in batch {i + 1}: {e}")
            print("  Skipping to next batch...")
            continue

        batch_trades = results["trades"]
        batch_summary = results["summary"]
        all_trades.extend(batch_trades)
        all_daily_pnl.update(results["daily_pnl"])

        # Merge regime stats
        for rg, rs in results["regime_stats"].items():
            for k in ("trades", "wins", "days"):
                all_regime_stats[rg][k] += rs.get(k, 0)
            all_regime_stats[rg]["pnl"] += rs.get("pnl", 0.0)

        # Equity rolls forward into the next batch
        running_capital = batch_summary.get("end_eq", running_capital)

        print(
            f"  trades={batch_summary['total_trades']}  "
            f"WR={batch_summary['win_rate']}%  "
            f"PnL=₹{batch_summary['pnl']:+,.0f}  "
            f"equity=₹{running_capital:,.0f}"
        )

        # Write partial report after every batch so you have something even if interrupted
        partial_report = _build_report(all_trades, all_daily_pnl, all_regime_stats, args, symbols, args.capital)
        with open(out_file, "w") as f:
            f.write(partial_report)
        print(f"  → partial report saved ({len(all_trades)} trades total)")

    # Final win-rate stats on regime_stats
    for rg, rs in all_regime_stats.items():
        rs["win_rate"] = round(rs["wins"] / rs["trades"] * 100, 1) if rs["trades"] else 0.0

    print(f"\n{'=' * 60}")
    print("  FINAL RESULTS")
    print(f"  Total trades : {len(all_trades)}")
    if all_trades:
        wins = [t for t in all_trades if t.pnl > 0]
        total_pnl = sum(t.pnl for t in all_trades)
        print(f"  Win rate     : {round(len(wins) / len(all_trades) * 100, 1)}%  (breakeven: 28.6%)")
        print(f"  Total PnL    : ₹{total_pnl:+,.2f}")
        print(f"  Return       : {round(total_pnl / args.capital * 100, 2):+.2f}%")
        print(f"  Final equity : ₹{running_capital:,.0f}")
    print(f"  Report       : {out_file}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()

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
Fast walk-forward — Backtester path.
Verdict is PF-driven. Every run is logged to strategy_runs.

Usage:
  python fast_wf.py                     # 3y / 400 syms / 3R full-exit
  python fast_wf.py --tranche           # tranche exits (1/3 @ 2R, 1/3 @ 3R, trail)
  python fast_wf.py --r 2.5             # target override (full-exit only)
  python fast_wf.py --years 4 --symbols 500
  python fast_wf.py --max-pos 8
  python fast_wf.py --no-log
  python fast_wf.py --help
"""
import argparse
import datetime as dt
import time

import db
import numpy as np
from backtest import Backtester, BacktestResult
from universe_helper import band_universe


def _verdict(n, wr, pf):
    if n < 30:
        return f"INSUFFICIENT TRADES (n={n}, need >=30)"
    if pf >= 1.60 and wr >= 0.38:
        return "STRONG EDGE"
    if pf >= 1.40 and wr >= 0.33:
        return "SOLID EDGE"
    if pf >= 1.20 and wr >= 0.35:
        return "TRADEABLE EDGE — size carefully"
    if pf >= 1.00:
        return "MARGINAL — positive expectancy, small edge"
    return "NO EDGE — negative expectancy"


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--r", type=float, default=None, help="TARGET_R override (full-exit mode only)")
    p.add_argument("--years", type=float, default=3.0, help="lookback years (default 3.0)")
    p.add_argument("--symbols", type=int, default=400, help="symbol count (default 400)")
    p.add_argument("--max-pos", type=int, default=None, help="max concurrent positions (default 5)")
    p.add_argument(
        "--tranche", action="store_true", help="enable tranche exits (1/3 @ 2R, 1/3 @ 3R, trail)"
    )
    p.add_argument("--no-log", action="store_true", help="skip strategy_runs DB logging")
    return p.parse_args()


def main():
    t0 = time.time()
    args = _parse_args()

    target_r = args.r if args.r is not None else Backtester.TARGET_R
    mode = "TRANCHED" if args.tranche else f"{target_r}R full-exit"
    if args.tranche:
        Backtester.TRANCHES_ENABLED = True
        print("[WF] TRANCHE mode ON (1/3 @ 2R, 1/3 @ 3R, trail EMA10)")
    elif args.r is not None:
        Backtester.TARGET_R = args.r
        print(f"[WF] override Backtester.TARGET_R = {args.r}")

    conn = db.get_conn()
    syms = band_universe(conn, limit=args.symbols)
    conn.close()

    end = dt.date.today()
    start = end - dt.timedelta(days=int(365 * args.years))

    result_obj = BacktestResult()
    if args.max_pos is not None:
        result_obj.max_positions = args.max_pos
    print(
        f"[WF] {len(syms)} symbols, {start.isoformat()} to "
        f"{end.isoformat()} ({args.years}y) | mode={mode}"
    )

    bt = Backtester(result=result_obj)
    result = bt.run([s + ".NS" for s in syms], start.isoformat(), end.isoformat())

    trades = result.trades
    n = len(trades)
    dt_sec = time.time() - t0

    if n == 0:
        print(f"[WF] NO TRADES in {dt_sec:.1f}s")
        return

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    wr = len(wins) / n
    avg_w = float(np.mean([t.pnl_pct for t in wins])) if wins else 0.0
    avg_l = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0
    pf = (
        (sum(t.pnl_pct for t in wins) / abs(sum(t.pnl_pct for t in losses)))
        if losses and sum(t.pnl_pct for t in losses)
        else 999.0
    )
    expectancy_r = wr * abs(avg_w / avg_l) - (1 - wr) if avg_l else 0.0
    verdict = _verdict(n, wr, pf)

    print()
    print("=" * 60)
    print(f"WALK-FORWARD RESULT ({dt_sec:.1f}s) | {mode}")
    print("=" * 60)
    print(f"trades            : {n}")
    print(f"wins / losses     : {len(wins)} / {len(losses)}")
    print(f"win rate          : {wr:.1%}")
    print(f"avg win           : {avg_w * 100:+.2f}%")
    print(f"avg loss          : {avg_l * 100:+.2f}%")
    print(f"R-multiple (avg)  : {abs(avg_w / avg_l):.2f}")
    print(f"expectancy / trade: {expectancy_r:+.3f} R")
    print(f"profit factor     : {pf:.2f}")
    print(f"total return      : {result.total_return * 100:+.2f}%")
    print(f"max drawdown      : {result.max_drawdown * 100:.2f}%")
    print(f"avg holding days  : {result.avg_holding_days:.1f}")
    print()
    print(f"VERDICT: {verdict}")

    if not args.no_log:
        try:
            import strategy_runs

            strategy_runs.log(
                {
                    "target_r": target_r if not args.tranche else 0.0,
                    "years": args.years,
                    "symbols": len(syms),
                    "max_pos": result_obj.max_positions,
                    "trades": n,
                    "wins": len(wins),
                    "losses": len(losses),
                    "win_rate": round(wr, 4),
                    "avg_win": round(avg_w, 4),
                    "avg_loss": round(avg_l, 4),
                    "expectancy_r": round(expectancy_r, 4),
                    "pf": round(pf, 3),
                    "total_return": round(result.total_return, 4),
                    "max_dd": round(result.max_drawdown, 4),
                    "holding_days": round(result.avg_holding_days, 2),
                    "verdict": f"{mode} | {verdict}",
                    "run_seconds": round(dt_sec, 1),
                }
            )
            print("[WF] logged to strategy_runs")
        except Exception as e:
            print(f"[WF] logging skipped: {e}")


if __name__ == "__main__":
    main()

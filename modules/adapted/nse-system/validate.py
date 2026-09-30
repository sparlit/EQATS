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
Validation harness — is the edge real?
v3 (2026-09-12): walk_forward now delegates to Backtester (fast path).
Backtester precomputes indicators once per symbol → 100x faster than
the naive slice-and-eval approach.
"""
import datetime as dt
import json
import random
import sys

import db
import numpy as np
import pandas as pd


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS validation_log(
        run_date TEXT, mode TEXT, payload TEXT,
        PRIMARY KEY (run_date, mode))""")


def _graded_trades(conn):
    rows = conn.execute(
        "SELECT symbol, entry_trigger, stop, target, outcome "
        "FROM swing_signals "
        "WHERE outcome IN ('WIN','LOSS','TIMEOUT')"
    ).fetchall()
    trades = []
    for _sym, trig, stop, tgt, out in rows:
        if not trig or not stop or trig <= stop:
            continue
        if out == "WIN":
            r = (tgt - trig) / (trig - stop)
        elif out == "LOSS":
            r = -1.0
        else:
            r = 0.0
        trades.append(r)
    return trades


def monte_carlo(conn=None, n_sim=10000, seed=7):
    own = conn is None
    if own:
        conn = db.get_conn()
    trades = _graded_trades(conn)
    if own:
        conn.close()
    if len(trades) < 15:
        return {"error": f"need >=15 graded trades, have {len(trades)}"}
    rng = random.Random(seed)
    n = len(trades)
    wrs, exps, dds, totals = [], [], [], []
    for _ in range(n_sim):
        eq = 0.0
        peak = 0.0
        mdd = 0.0
        wins = 0
        for _i in range(n):
            r = trades[rng.randrange(n)]
            if r > 0:
                wins += 1
            eq += r
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        wrs.append(wins / n)
        exps.append(eq / n)
        dds.append(mdd)
        totals.append(eq)

    def pct(a, p):
        return round(float(np.percentile(a, p)), 3)

    return {
        "n_trades": n,
        "n_sim": n_sim,
        "win_rate": {"p5": pct(wrs, 5), "p50": pct(wrs, 50), "p95": pct(wrs, 95)},
        "expectancy_r": {"p5": pct(exps, 5), "p50": pct(exps, 50), "p95": pct(exps, 95)},
        "total_r": {"p5": pct(totals, 5), "p50": pct(totals, 50), "p95": pct(totals, 95)},
        "max_dd_r": {"p50": pct(dds, 50), "p95": pct(dds, 95)},
        "p_negative_total": round(sum(1 for t in totals if t < 0) / n_sim, 3),
    }


def walk_forward(conn=None, n_symbols=500, seed=7, years=5):
    """
    Fast walk-forward via Backtester (precomputed indicators).
    Runs the full strategy on the last `years` of data across
    `n_symbols` from the band. Reports the aggregate stats.
    """
    from backtest import Backtester
    from universe_helper import band_universe

    own = conn is None
    if own:
        conn = db.get_conn()
    syms = band_universe(conn, limit=n_symbols)
    if own:
        conn.close()

    end = dt.date.today()
    start = end - dt.timedelta(days=365 * years)
    print(f"[VALIDATE] WF — {len(syms)} symbols, {start.isoformat()} to {end.isoformat()}")

    bt = Backtester()
    result = bt.run([s + ".NS" for s in syms], start.isoformat(), end.isoformat())

    trades = result.trades
    n = len(trades)
    if n == 0:
        return {"n_symbols": len(syms), "n_trades": 0, "verdict": "NO TRADES — check regime gate / data"}

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

    if n < 20:
        verdict = f"INSUFFICIENT TRADES (n={n}, need >=20)"
    elif wr >= 0.45 and pf >= 1.5:
        verdict = "EDGE HOLDS (WR >=45%, PF >=1.5)"
    elif wr >= 0.40 and pf >= 1.2:
        verdict = "WEAK EDGE — tradeable with tight sizing"
    else:
        verdict = "NO EDGE at current params — review filters"

    return {
        "n_symbols": len(syms),
        "n_trades": n,
        "win_rate": round(wr, 3),
        "wins": len(wins),
        "losses": len(losses),
        "avg_win_pct": round(avg_w * 100, 3),
        "avg_loss_pct": round(avg_l * 100, 3),
        "profit_factor": round(pf, 3),
        "total_return_pct": round(result.total_return * 100, 2),
        "max_drawdown_pct": round(result.max_drawdown * 100, 2),
        "avg_holding_days": round(result.avg_holding_days, 1),
        "verdict": verdict,
    }


def run_mode(mode):
    conn = db.get_conn()
    _ensure(conn)
    today = dt.date.today().isoformat()
    if mode == "mc":
        out = monte_carlo(conn)
    elif mode == "wf":
        out = walk_forward(conn)
    else:
        out = {"error": "unknown mode"}
    conn.execute("INSERT OR REPLACE INTO validation_log VALUES (?,?,?)", (today, mode, json.dumps(out, default=str)))
    conn.commit()
    conn.close()
    print(f"[VALIDATE] {mode}:")
    print(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "mc"
    if mode == "all":
        run_mode("mc")
        run_mode("wf")
    else:
        run_mode(mode)

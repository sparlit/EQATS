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
Strategy run ledger — records every fast_wf sweep for comparison.
Table: strategy_runs
"""
import datetime as dt
import json

import db


def _ensure(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS strategy_runs(
        run_at TEXT PRIMARY KEY,
        target_r REAL,
        years REAL,
        symbols INTEGER,
        max_pos INTEGER,
        trades INTEGER,
        wins INTEGER,
        losses INTEGER,
        win_rate REAL,
        avg_win REAL,
        avg_loss REAL,
        expectancy_r REAL,
        pf REAL,
        total_return REAL,
        max_dd REAL,
        holding_days REAL,
        verdict TEXT,
        payload TEXT
    )
    """)


def log(result: dict):
    conn = db.get_conn()
    _ensure(conn)
    conn.execute(
        """
    INSERT OR REPLACE INTO strategy_runs VALUES
    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
        (
            dt.datetime.now().isoformat(timespec="seconds"),
            result.get("target_r"),
            result.get("years"),
            result.get("symbols"),
            result.get("max_pos"),
            result.get("trades"),
            result.get("wins"),
            result.get("losses"),
            result.get("win_rate"),
            result.get("avg_win"),
            result.get("avg_loss"),
            result.get("expectancy_r"),
            result.get("pf"),
            result.get("total_return"),
            result.get("max_dd"),
            result.get("holding_days"),
            result.get("verdict"),
            json.dumps(result, default=str),
        ),
    )
    conn.commit()
    conn.close()


def history(n=20):
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        """
    SELECT run_at, target_r, years, symbols, trades,
           win_rate, pf, expectancy_r, total_return, max_dd, verdict
    FROM strategy_runs
    ORDER BY run_at DESC LIMIT ?
    """,
        (n,),
    ).fetchall()
    conn.close()
    cols = [
        "run_at",
        "target_r",
        "years",
        "symbols",
        "trades",
        "win_rate",
        "pf",
        "expectancy_r",
        "total_return",
        "max_dd",
        "verdict",
    ]
    return [dict(zip(cols, r, strict=False)) for r in rows]


def summary_by_target():
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute("""
    SELECT target_r,
           COUNT(*)            AS runs,
           AVG(pf)             AS avg_pf,
           AVG(win_rate)       AS avg_wr,
           AVG(expectancy_r)   AS avg_exp,
           AVG(max_dd)         AS avg_dd,
           SUM(trades)         AS total_trades
    FROM strategy_runs
    GROUP BY target_r
    ORDER BY target_r
    """).fetchall()
    conn.close()
    cols = ["target_r", "runs", "avg_pf", "avg_wr", "avg_exp", "avg_dd", "total_trades"]
    return [dict(zip(cols, r, strict=False)) for r in rows]


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "history"
    if cmd == "history":
        print("RECENT RUNS")
        print("-" * 110)
        for h in history():
            print(
                f"{h['run_at']:<20} "
                f"R={h['target_r']:<4} "
                f"y={h['years']:<3} "
                f"n={h['trades']:<4} "
                f"wr={h['win_rate']:.1%} "
                f"pf={h['pf']:.2f} "
                f"exp={h['expectancy_r']:+.3f}R "
                f"ret={h['total_return'] * 100:+.1f}% "
                f"dd={h['max_dd'] * 100:.1f}% "
                f"| {h['verdict']}"
            )
    elif cmd == "summary":
        print("SUMMARY BY TARGET_R")
        print("-" * 110)
        for s in summary_by_target():
            print(
                f"R={s['target_r']:<4} "
                f"runs={s['runs']:<3} "
                f"trades={s['total_trades']:<5} "
                f"avg_pf={s['avg_pf']:.2f} "
                f"avg_wr={s['avg_wr']:.1%} "
                f"avg_exp={s['avg_exp']:+.3f}R "
                f"avg_dd={s['avg_dd'] * 100:.1f}%"
            )

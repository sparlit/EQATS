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
mc : Monte-Carlo bootstrap on graded live trades (R-multiples).
wf : walk-forward check of the setup detector (in-sample vs out-of-sample).
Results stored in validation_log(run_date, mode, payload).
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


def _simulate(df, i, st):
    """Grade one signal: trigger within 3 bars, then stop-first path."""
    h = df["High"].values
    l = df["Low"].values
    trig, stop, tgt = st.entry_price, st.stop_loss, st.target_price
    trig_bar = None
    for j in range(i + 1, min(i + 4, len(df))):
        if h[j] >= trig:
            trig_bar = j
            break
    if trig_bar is None:
        return "EXPIRED"
    for j in range(trig_bar, min(trig_bar + 31, len(df))):
        if l[j] <= stop:
            return "LOSS"
        if h[j] >= tgt:
            return "WIN"
    return "TIMEOUT"


def walk_forward(conn=None, n_symbols=120, step=5, seed=7):
    own = conn is None
    if own:
        conn = db.get_conn()
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM universe_broad "
            "WHERE mcap_cr BETWEEN 1000 AND 8000 "
            "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
            "ORDER BY mcap_cr DESC LIMIT ?",
            (n_symbols,),
        ).fetchall()
    ]
    data = {}
    for s in syms:
        data[s] = conn.execute(
            "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date", (s,)
        ).fetchall()
    if own:
        conn.close()
    from setup import SetupDetector

    is_w = is_l = is_n = 0
    oos_w = oos_l = oos_n = 0
    for s in syms:
        rows = data[s]
        if len(rows) < 750:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "Close", "High", "Low", "Volume"]).set_index("date")
        df.index = pd.to_datetime(df.index)
        split = int(len(df) * 0.6)
        last_i = -10
        for i in range(280, len(df) - 31, step):
            if i - last_i < 10:
                continue
            st = SetupDetector.detect(df.iloc[: i + 1], s)
            if not st.triggered:
                continue
            last_i = i
            out = _simulate(df, i, st)
            if i < split:
                is_n += 1
                if out == "WIN":
                    is_w += 1
                elif out == "LOSS":
                    is_l += 1
            else:
                oos_n += 1
                if out == "WIN":
                    oos_w += 1
                elif out == "LOSS":
                    oos_l += 1
    is_gl = is_w + is_l
    oos_gl = oos_w + oos_l
    is_wr = round(is_w / is_gl, 3) if is_gl else None
    oos_wr = round(oos_w / oos_gl, 3) if oos_gl else None
    if oos_gl < 20:
        verdict = "INSUFFICIENT OOS TRADES"
    elif oos_wr >= 0.45 and oos_wr >= (is_wr or 0) - 0.10:
        verdict = "EDGE HOLDS OUT-OF-SAMPLE"
    else:
        verdict = "OVERFIT RISK — review params"
    return {
        "in_sample": {"wins": is_w, "losses": is_l, "win_rate": is_wr, "signals": is_n},
        "out_sample": {"wins": oos_w, "losses": oos_l, "win_rate": oos_wr, "signals": oos_n},
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

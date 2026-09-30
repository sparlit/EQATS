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
Template Sequence Matching (DTW) v2 — adds historical backfill.
Compares the live price shape against ideal pattern templates using
Dynamic Time Warping. Pure numpy, no extra dependencies.

Templates: VCP, HIGH_TIGHT_FLAG, BULL_FLAG, DOUBLE_BOTTOM.
Score: similarity 0-100 (higher = closer shape match).
Stores matches in template_scores(date, symbol, template, similarity).

Usage:
  python template_match.py SYMBOL          -> sims for one symbol
  python template_match.py run [N]         -> scan band today, store
  python template_match.py backfill [S] [N]-> store HISTORY (one-time)
  python template_match.py top [N]         -> show latest stored matches
"""
import datetime as dt
import math
import sys

import db
import numpy as np

LOOKBACK = 90  # daily closes used per symbol
N_POINTS = 60  # resampled sequence length
MIN_SIM_TO_STORE = 70.0


def _from_points(pts, n=N_POINTS):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xi = np.linspace(0, n - 1, n)
    return np.interp(xi, xs, ys)


TEMPLATES = {
    "VCP": _from_points([(0, 0), (10, 12), (20, 30), (26, 22), (32, 32), (38, 28), (44, 34), (50, 32), (60, 34)]),
    "HIGH_TIGHT_FLAG": _from_points([(0, 0), (12, 18), (30, 70), (38, 62), (45, 55), (52, 56), (60, 58)]),
    "BULL_FLAG": _from_points([(0, 0), (14, 10), (30, 30), (38, 26), (45, 24), (52, 24), (60, 25)]),
    "DOUBLE_BOTTOM": _from_points([(0, 0), (8, -8), (15, -18), (25, -6), (32, -12), (38, -16), (48, -4), (60, 6)]),
}


def _dtw(a, b):
    n, m = len(a), len(b)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        ai = a[i - 1]
        row_prev = D[i - 1]
        row = D[i]
        for j in range(1, m + 1):
            c = abs(ai - b[j - 1])
            row[j] = c + min(row_prev[j], row[j - 1], row_prev[j - 1])
    return float(D[n, m] / max(n, m))


def _shape(closes, n=N_POINTS):
    c = np.asarray(closes, dtype=float)
    if len(c) < 40:
        return None
    idx = np.linspace(0, len(c) - 1, n).astype(int)
    c = c[idx]
    base = c[0]
    if base <= 0:
        return None
    return (c / base - 1.0) * 100.0


def _sim(dist):
    return 100.0 * math.exp(-dist / 10.0)


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS template_scores(
        date TEXT, symbol TEXT, template TEXT, similarity REAL,
        created_at TEXT,
        PRIMARY KEY(date, symbol, template))""")


def _symbols(conn, limit=600):
    rows = conn.execute(
        "SELECT symbol FROM universe_broad "
        "WHERE mcap_cr BETWEEN 1000 AND 8000 "
        "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
        "ORDER BY mcap_cr DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r[0] for r in rows]


def scan_symbol(symbol, conn=None, lookback=LOOKBACK):
    own = conn is None
    if own:
        conn = db.get_conn()
    rows = conn.execute(
        "SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?", (symbol, lookback)
    ).fetchall()
    if own:
        conn.close()
    if not rows or len(rows) < 40:
        return []
    closes = [r[0] for r in reversed(rows)]
    shape = _shape(closes)
    if shape is None:
        return []
    out = []
    for name, tpl in TEMPLATES.items():
        d = _dtw(shape, tpl)
        out.append({"template": name, "dist": round(d, 2), "similarity": round(_sim(d), 1)})
    out.sort(key=lambda x: -x["similarity"])
    return out


def run(limit=600, min_sim=MIN_SIM_TO_STORE):
    conn = db.get_conn()
    _ensure(conn)
    syms = _symbols(conn, limit)
    today = dt.date.today().isoformat()
    now = dt.datetime.now().isoformat(timespec="seconds")
    saved = 0
    best = []
    for i, sym in enumerate(syms, 1):
        res = scan_symbol(sym, conn=conn)
        for r in res:
            if r["similarity"] >= min_sim:
                conn.execute(
                    "INSERT OR REPLACE INTO template_scores VALUES (?,?,?,?,?)",
                    (today, sym, r["template"], r["similarity"], now),
                )
                saved += 1
            best.append((r["similarity"], sym, r["template"]))
        if i % 100 == 0:
            conn.commit()
            print(f"[TEMPLATE] progress {i}/{len(syms)}, saved {saved}")
    conn.commit()
    best.sort(reverse=True)
    print(f"[TEMPLATE] complete: scanned {len(syms)}, saved {saved}")
    print("[TEMPLATE] top 20 shape matches today:")
    for sim, sym, tpl in best[:20]:
        print(f"   {sim:5.1f}  {sym:<12} {tpl}")
    conn.close()
    return saved


def backfill(step=10, limit=300, min_sim=MIN_SIM_TO_STORE):
    """One-time: store HISTORICAL template scores every `step` days
    so the meta-model can learn dtw_sim as a feature."""
    conn = db.get_conn()
    _ensure(conn)
    syms = _symbols(conn, limit)
    conn.close()
    now = dt.datetime.now().isoformat(timespec="seconds")
    total = len(syms)
    saved = 0
    print(f"[TEMPLATE-BF] backfilling {total} symbols (step={step})")
    for i, sym in enumerate(syms, 1):
        conn = db.get_conn()
        rows = conn.execute("SELECT date, close FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)).fetchall()
        conn.close()
        if len(rows) < 150:
            continue
        dates = [str(r[0])[:10] for r in rows]
        closes = [r[1] for r in rows]
        batch = []
        for j in range(120, len(rows) + 1, step):
            d = dates[j - 1]
            win = closes[max(0, j - 90) : j]
            shape = _shape(win)
            if shape is None:
                continue
            for name, tpl in TEMPLATES.items():
                sim = _sim(_dtw(shape, tpl))
                if sim >= min_sim:
                    batch.append((d, sym, name, round(sim, 1), now))
        if batch:
            conn = db.get_conn()
            existing = {
                r[0] for r in conn.execute("SELECT date FROM template_scores WHERE symbol=?", (sym,)).fetchall()
            }
            todo = [b for b in batch if b[0] not in existing]
            if todo:
                conn.executemany("INSERT OR REPLACE INTO template_scores VALUES (?,?,?,?,?)", todo)
                conn.commit()
                saved += len(todo)
            conn.close()
        if i % 25 == 0:
            print(f"[TEMPLATE-BF] {i}/{total} symbols, saved {saved}")
    print(f"[TEMPLATE-BF] complete: saved {saved} historical scores")
    return saved


def top(n=20):
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        "SELECT date, symbol, template, similarity FROM template_scores "
        "WHERE date=(SELECT MAX(date) FROM template_scores) "
        "ORDER BY similarity DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    if not rows:
        print("No template matches stored. Run: python template_match.py run")
        return []
    for d, sym, tpl, sim in rows:
        print(f"{d}  {sim:5.1f}  {sym:<12} {tpl}")
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "top"
    if cmd == "run":
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else 600
        run(limit=lim)
    elif cmd == "backfill":
        st = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        lm = int(sys.argv[3]) if len(sys.argv) > 3 else 300
        backfill(step=st, limit=lm)
    elif cmd == "top":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        top(n)
    else:
        for r in scan_symbol(cmd.upper()):
            print(f"{r['template']:<18} sim {r['similarity']:5.1f}  (dist {r['dist']})")

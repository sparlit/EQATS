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
Long-Term Value Radar — quality names in downturns, for accumulation.
Authorized 2026-09-12 (Feature B). v3 (2026-09-12): uses canonical
universe_helper for symbol list (ID7 consolidation).
"""
import datetime as dt
import json
import statistics
import sys

import db
from universe_helper import band_universe


def _quality_score(row):
    score = 0
    notes = []
    roce = row.get("roce")
    if roce is not None:
        if roce >= 15:
            score += 30
            notes.append(f"ROCE {roce:.0f}")
        elif roce >= 10:
            score += 15
            notes.append(f"ROCE {roce:.0f}")
    de = row.get("debt_to_equity")
    if de is not None:
        if de <= 1.0:
            score += 20
            notes.append(f"D/E {de:.2f}")
        elif de <= 2.0:
            score += 10
            notes.append(f"D/E {de:.2f}")
    prom = row.get("promoter_holding")
    if prom is not None:
        if prom >= 40:
            score += 20
            notes.append(f"Prom {prom:.0f}%")
        elif prom >= 25:
            score += 10
            notes.append(f"Prom {prom:.0f}%")
    if row.get("cfo_positive") == 1:
        score += 15
        notes.append("CFO+")
    pg = row.get("profit_growth_3y")
    if pg is not None:
        if pg >= 15:
            score += 15
            notes.append(f"Profit3Y {pg:.0f}%")
        elif pg >= 8:
            score += 8
            notes.append(f"Profit3Y {pg:.0f}%")
    return score, notes


def _value_score(last, hi52, pe, sector_median_pe):
    score = 0
    notes = []
    if hi52 and hi52 > 0:
        below = (hi52 - last) / hi52
        if below >= 0.40:
            score += 70
            notes.append(f"{below * 100:.0f}% below 52w high")
        elif below >= 0.25:
            score += 40
            notes.append(f"{below * 100:.0f}% below 52w high")
    if pe is not None and pe > 0 and sector_median_pe:
        ratio = pe / sector_median_pe
        if ratio <= 0.7:
            score += 50
            notes.append(f"PE {ratio:.2f}x sector")
        elif ratio <= 1.0:
            score += 30
            notes.append(f"PE {ratio:.2f}x sector")
    return score, notes


def _sector_pe_medians(conn):
    rows = conn.execute(
        "SELECT s.sector, f.pe FROM fundamentals f "
        "JOIN stocks s ON s.symbol=f.symbol "
        "WHERE f.pe IS NOT NULL AND f.pe>0 AND s.sector IS NOT NULL"
    ).fetchall()
    by = {}
    for sec, pe in rows:
        by.setdefault(sec, []).append(pe)
    return {sec: statistics.median(v) for sec, v in by.items()}


def _ensure(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS value_radar(
        date TEXT, symbol TEXT, sector TEXT,
        last_price REAL, below_52w REAL, pe REAL, sector_pe REAL,
        quality_score REAL, value_score REAL, composite REAL,
        tier TEXT, notes TEXT,
        PRIMARY KEY(date, symbol)
    )
    """)


def compute(conn=None, limit=1500):
    own = conn is None
    if own:
        conn = db.get_conn()
    _ensure(conn)
    today = dt.date.today().isoformat()
    sector_med = _sector_pe_medians(conn)

    fund_cols = [r[1] for r in conn.execute("PRAGMA table_info(fundamentals)")]
    has_fund = bool(fund_cols)

    syms = band_universe(conn, limit=limit)

    rows_out = []
    for sym in syms:
        prows = conn.execute(
            "SELECT high, low, close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 260", (sym,)
        ).fetchall()
        if len(prows) < 200:
            continue
        prows = list(reversed(prows))
        highs = [r[0] for r in prows if r[0] is not None]
        if len(highs) < 200:
            continue
        hi52 = max(highs[-252:])
        last = prows[-1][2]
        if not hi52 or not last:
            continue

        f = {}
        if has_fund:
            frow = conn.execute("SELECT * FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
            if frow:
                f = dict(zip(fund_cols, frow, strict=False))

        sector = None
        srow = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()
        if srow:
            sector = srow[0]

        q_score, q_notes = _quality_score(f)
        pe = f.get("pe")
        sec_med = sector_med.get(sector)
        v_score, v_notes = _value_score(last, hi52, pe, sec_med)

        below = (hi52 - last) / hi52 if hi52 else 0
        if below < 0.25:
            continue
        composite = round(0.6 * v_score + 0.4 * q_score, 1)

        if q_score >= 50 and v_score >= 60:
            tier = "A"
        elif composite >= 80:
            tier = "B"
        else:
            tier = "C"

        rows_out.append(
            {
                "date": today,
                "symbol": sym,
                "sector": sector,
                "last_price": round(last, 2),
                "below_52w": round(below, 3),
                "pe": pe,
                "sector_pe": sec_med,
                "quality_score": q_score,
                "value_score": v_score,
                "composite": composite,
                "tier": tier,
                "notes": " | ".join(q_notes + v_notes),
            }
        )

    rows_out.sort(key=lambda r: -r["composite"])
    rows_out = rows_out[:75]

    conn.execute("DELETE FROM value_radar WHERE date=?", (today,))
    for r in rows_out:
        conn.execute(
            "INSERT OR REPLACE INTO value_radar VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["date"],
                r["symbol"],
                r["sector"],
                r["last_price"],
                r["below_52w"],
                r["pe"],
                r["sector_pe"],
                r["quality_score"],
                r["value_score"],
                r["composite"],
                r["tier"],
                r["notes"],
            ),
        )
    conn.commit()
    if own:
        conn.close()
    return rows_out


def top(n=25, tier=None):
    conn = db.get_conn()
    _ensure(conn)
    today = conn.execute("SELECT MAX(date) FROM value_radar").fetchone()[0]
    if not today:
        conn.close()
        return []
    if tier:
        rows = conn.execute(
            "SELECT symbol, sector, last_price, below_52w, pe, sector_pe, "
            "quality_score, value_score, composite, tier, notes "
            "FROM value_radar WHERE date=? AND tier=? "
            "ORDER BY composite DESC LIMIT ?",
            (today, tier, n),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT symbol, sector, last_price, below_52w, pe, sector_pe, "
            "quality_score, value_score, composite, tier, notes "
            "FROM value_radar WHERE date=? "
            "ORDER BY composite DESC LIMIT ?",
            (today, n),
        ).fetchall()
    conn.close()
    return [
        {
            "symbol": r[0],
            "sector": r[1],
            "last_price": r[2],
            "below_52w": r[3],
            "pe": r[4],
            "sector_pe": r[5],
            "quality_score": r[6],
            "value_score": r[7],
            "composite": r[8],
            "tier": r[9],
            "notes": r[10],
        }
        for r in rows
    ]


def _fmt_tg(rows):
    if not rows:
        return "📉 VALUE RADAR — no candidates this week."
    lines = ["📉 VALUE RADAR — quality names in downturns", f"{len(rows)} candidates (top 8 shown)"]
    for r in rows[:8]:
        lines.append(
            f"[{r['tier']}] {r['symbol']}  "
            f"₹{r['last_price']}  "
            f"{r['below_52w'] * 100:.0f}% off high  "
            f"q{r['quality_score']}/v{r['value_score']}"
        )
    return "\n".join(lines)


def report(n=25, send_tg=True):
    rows = top(n)
    print("=" * 60)
    print("VALUE RADAR")
    print("=" * 60)
    if not rows:
        print("(no candidates)")
    for r in rows:
        print(
            f"[{r['tier']}] {r['symbol']:<12} "
            f"₹{r['last_price']:>8.2f}  "
            f"{r['below_52w'] * 100:>4.0f}% off high  "
            f"q{r['quality_score']:>3}/v{r['value_score']:>3}  "
            f"{r['notes']}"
        )
    if send_tg:
        try:
            from alerts import send

            send(_fmt_tg(rows))
            print("[VR] telegram sent")
        except Exception as e:
            print(f"[VR] telegram skipped: {e}")
    return rows


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        compute()
        report()
    elif cmd == "top":
        report(n=int(sys.argv[2]) if len(sys.argv) > 2 else 25)
    else:
        report()

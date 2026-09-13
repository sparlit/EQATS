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
Positional Scanner — long-term holds (months to years).
v3 (2026-09-12): uses canonical universe_helper (ID7).
Score = 0.4*quality + 0.3*trend + 0.3*valuation
Tiers: S (>=80 all pillars), A (>=65), B (>=50), C (ranked below).
Runs weekly Sat 10:00 IST.
"""
import datetime as dt
import statistics
import sys

import db
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("positional")


def _ensure(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS positional_picks(
        date TEXT, symbol TEXT, sector TEXT, last_price REAL,
        quality_score REAL, trend_score REAL, value_score REAL,
        composite REAL, tier TEXT, notes TEXT,
        PRIMARY KEY(date, symbol)
    )
    """)


def _quality_score(f):
    score = 0
    notes = []
    roce = f.get("roce")
    if roce is not None:
        if roce >= 25:
            score += 30
            notes.append(f"ROCE {roce:.0f}")
        elif roce >= 15:
            score += 22
            notes.append(f"ROCE {roce:.0f}")
        elif roce >= 10:
            score += 12
    de = f.get("debt_to_equity")
    if de is not None:
        if de <= 0.5:
            score += 20
            notes.append(f"D/E {de:.2f}")
        elif de <= 1.0:
            score += 14
        elif de <= 2.0:
            score += 6
    pg = f.get("profit_growth_3y")
    if pg is not None:
        if pg >= 20:
            score += 25
            notes.append(f"Profit3Y {pg:.0f}%")
        elif pg >= 15:
            score += 18
        elif pg >= 8:
            score += 10
    sg = f.get("sales_growth_3y")
    if sg is not None and sg >= 10:
        score += 15
        notes.append(f"Sales3Y {sg:.0f}%")
    if f.get("cfo_positive") == 1:
        score += 10
        notes.append("CFO+")
    return min(100, score), notes


def _trend_score(price, dma200, dma200_prev, ema50, hi52, lo52):
    score = 0
    notes = []
    if dma200 and price > dma200:
        score += 30
        notes.append("above 200DMA")
    if dma200 and dma200_prev and dma200 > dma200_prev:
        score += 20
        notes.append("200DMA rising")
    if ema50 and price > ema50:
        score += 20
        notes.append("above EMA50")
    if hi52 and price and hi52 > 0:
        ratio = price / hi52
        if ratio >= 0.95:
            score += 25
            notes.append(f"{ratio * 100:.0f}% of 52w high")
        elif ratio >= 0.85:
            score += 15
            notes.append(f"{ratio * 100:.0f}% of 52w high")
        elif ratio >= 0.70:
            score += 5
    if lo52 and price and lo52 > 0:
        ratio = price / lo52
        if ratio <= 1.30:
            score += 10
            notes.append("near 52w low (early)")
    return min(100, score), notes


def _value_score(pe, sector_pe, peg):
    score = 0
    notes = []
    if pe and pe > 0 and sector_pe:
        ratio = pe / sector_pe
        if ratio <= 0.7:
            score += 50
            notes.append(f"PE {ratio:.2f}x sector")
        elif ratio <= 1.0:
            score += 35
            notes.append(f"PE {ratio:.2f}x sector")
        elif ratio <= 1.3:
            score += 15
    if peg and peg > 0:
        if peg <= 1.0:
            score += 50
            notes.append(f"PEG {peg:.2f}")
        elif peg <= 1.5:
            score += 30
            notes.append(f"PEG {peg:.2f}")
        elif peg <= 2.0:
            score += 15
    return min(100, score), notes


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


def compute(conn=None, limit=1500):
    own = conn is None
    if own:
        conn = db.get_conn()
    _ensure(conn)
    today = dt.date.today().isoformat()
    sector_med = _sector_pe_medians(conn)

    fund_cols = [r[1] for r in conn.execute("PRAGMA table_info(fundamentals)")]
    if not fund_cols:
        if own:
            conn.close()
        log.warning("no fundamentals table — run fundamentals_tv.py first")
        return []

    syms = band_universe(conn, limit=limit)

    rows_out = []
    for sym in syms:
        prows = conn.execute(
            "SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 260", (sym,)
        ).fetchall()
        if len(prows) < 210:
            continue
        closes = [r[0] for r in reversed(prows) if r[0] is not None]
        if len(closes) < 210:
            continue
        price = closes[-1]
        dma200 = sum(closes[-200:]) / 200
        dma200_prev = sum(closes[-220:-20]) / 200
        ema50 = sum(closes[-50:]) / 50
        hi52 = max(closes[-252:]) if len(closes) >= 252 else max(closes)
        lo52 = min(closes[-252:]) if len(closes) >= 252 else min(closes)

        frow = conn.execute("SELECT * FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
        if not frow:
            continue
        f = dict(zip(fund_cols, frow, strict=False))
        sector = f.get("sector") or None

        q, q_notes = _quality_score(f)
        t, t_notes = _trend_score(price, dma200, dma200_prev, ema50, hi52, lo52)
        pe = f.get("pe")
        sec_med = sector_med.get(sector)
        pg = f.get("profit_growth_3y")
        peg = (pe / pg) if (pe and pg and pg > 0) else None
        v, v_notes = _value_score(pe, sec_med, peg)

        composite = round(0.4 * q + 0.3 * t + 0.3 * v, 1)

        if composite >= 80 and q >= 60 and t >= 60 and v >= 60:
            tier = "S"
        elif composite >= 65:
            tier = "A"
        elif composite >= 50:
            tier = "B"
        else:
            tier = "C"

        rows_out.append(
            {
                "date": today,
                "symbol": sym,
                "sector": sector,
                "last_price": round(price, 2),
                "quality_score": q,
                "trend_score": t,
                "value_score": v,
                "composite": composite,
                "tier": tier,
                "notes": " | ".join(q_notes + t_notes + v_notes),
            }
        )

    rows_out.sort(key=lambda r: -r["composite"])
    rows_out = rows_out[:50]

    conn.execute("DELETE FROM positional_picks WHERE date=?", (today,))
    for r in rows_out:
        conn.execute(
            "INSERT OR REPLACE INTO positional_picks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r["date"],
                r["symbol"],
                r["sector"],
                r["last_price"],
                r["quality_score"],
                r["trend_score"],
                r["value_score"],
                r["composite"],
                r["tier"],
                r["notes"],
            ),
        )
    conn.commit()
    if own:
        conn.close()
    log.info(f"positional picks computed: {len(rows_out)}")
    return rows_out


def top(n=25, tier=None):
    conn = db.get_conn()
    _ensure(conn)
    today = conn.execute("SELECT MAX(date) FROM positional_picks").fetchone()[0]
    if not today:
        conn.close()
        return []
    if tier:
        rows = conn.execute(
            "SELECT symbol, sector, last_price, quality_score, "
            "trend_score, value_score, composite, tier, notes "
            "FROM positional_picks WHERE date=? AND tier=? "
            "ORDER BY composite DESC LIMIT ?",
            (today, tier, n),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT symbol, sector, last_price, quality_score, "
            "trend_score, value_score, composite, tier, notes "
            "FROM positional_picks WHERE date=? "
            "ORDER BY composite DESC LIMIT ?",
            (today, n),
        ).fetchall()
    conn.close()
    return [
        {
            "symbol": r[0],
            "sector": r[1],
            "last_price": r[2],
            "quality_score": r[3],
            "trend_score": r[4],
            "value_score": r[5],
            "composite": r[6],
            "tier": r[7],
            "notes": r[8],
        }
        for r in rows
    ]


def _fmt_tg(rows):
    if not rows:
        return "📈 POSITIONAL — no candidates this week."
    lines = ["📈 POSITIONAL PICKS — long-term holds", f"{len(rows)} candidates (top 8 shown)"]
    for r in rows[:8]:
        lines.append(
            f"[{r['tier']}] {r['symbol']}  ₹{r['last_price']}  "
            f"Q{r['quality_score']}/T{r['trend_score']}/V{r['value_score']}  "
            f"composite {r['composite']}"
        )
    return "\n".join(lines)


def report(n=25, send_tg=True):
    rows = top(n)
    print("=" * 60)
    print("POSITIONAL PICKS")
    print("=" * 60)
    if not rows:
        print("(no candidates)")
    for r in rows:
        print(
            f"[{r['tier']}] {r['symbol']:<12} "
            f"₹{r['last_price']:>8.2f}  "
            f"Q{r['quality_score']:>3}/T{r['trend_score']:>3}/"
            f"V{r['value_score']:>3}  "
            f"comp {r['composite']:>5}  {r['notes']}"
        )
    if send_tg:
        try:
            from alerts import send

            send(_fmt_tg(rows))
            print("[POS] telegram sent")
        except Exception as e:
            print(f"[POS] telegram skipped: {e}")
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

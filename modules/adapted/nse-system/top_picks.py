"""
Top Picks — daily shortlist.

Composite score:
  50% ML P(WIN)
  30% institutional accumulation
  20% sector leadership
  +10% bonus if live Gabani setup exists

Stores result in top_picks table.
"""

import datetime as dt
import pandas as pd

import db
import meta_model
import institutional
import sector_gate


def _ensure(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS top_picks(
            date TEXT,
            symbol TEXT,
            p_win REAL,
            accum REAL,
            sector_rs REAL,
            sector TEXT,
            setup INTEGER,
            composite REAL
        )
    """)


def _sector_rs_map(conn):
    """
    Build symbol -> sector relative strength map.

    Top sector = 1.0
    Bottom sector = 0.0
    Unknown sector = 0.5
    """
    try:
        g = sector_gate.sector_perf(conn)
        if g is None or g.empty:
            return {}, {}

        n = len(g)
        sector_rank = {}

        for i, (_, row) in enumerate(g.iterrows()):
            sec = row["sector"]
            sector_rank[sec] = 1.0 - (i / max(1, n - 1))

        symbol_sector = {}
        rows = conn.execute(
            "SELECT symbol, sector FROM stocks "
            "WHERE sector IS NOT NULL AND sector!=''"
        ).fetchall()

        for sym, sec in rows:
            symbol_sector[sym] = sec

        symbol_rs = {
            sym: sector_rank.get(sec, 0.5)
            for sym, sec in symbol_sector.items()
        }

        return symbol_rs, symbol_sector

    except Exception as e:
        print(f"[TOPPICKS] sector rs skipped: {e}")
        return {}, {}


def _detect_setup(conn, sym):
    """
    Detect live Gabani setup for shortlist symbols only.
    Kept separate so full universe computation remains fast.
    """
    try:
        from setup import SetupDetector

        rows = conn.execute(
            "SELECT date, close, high, low, volume FROM prices_daily "
            "WHERE symbol=? ORDER BY date",
            (sym,),
        ).fetchall()

        if len(rows) < 280:
            return 0

        df = pd.DataFrame(
            list(rows),
            columns=["date", "Close", "High", "Low", "Volume"],
        ).set_index("date")

        df.index = pd.to_datetime(df.index)

        st = SetupDetector.detect(df, sym)
        return 1 if st.triggered else 0

    except Exception as e:
        print(f"[TOPPICKS] setup detect skipped for {sym}: {e}")
        return 0


def _latest_accumulation_map(conn):
    acc = {}

    try:
        rows = conn.execute("""
            SELECT symbol, accum
            FROM institutional
            WHERE date=(SELECT MAX(date) FROM institutional)
        """).fetchall()

        for sym, a in rows:
            if a is not None:
                acc[sym] = float(a)

    except Exception as e:
        print(f"[TOPPICKS] accumulation map skipped: {e}")

    return acc


def _universe(conn, limit=600):
    rows = conn.execute(
        "SELECT symbol FROM universe_broad "
        "WHERE mcap_cr BETWEEN 1000 AND 8000 "
        "AND symbol NOT LIKE '%$%' "
        "AND symbol NOT LIKE '% %' "
        "ORDER BY mcap_cr DESC LIMIT ?",
        (limit,),
    ).fetchall()

    return [r[0] for r in rows]


def compute(force=False):
    conn = db.get_conn()
    _ensure(conn)

    today = dt.date.today().isoformat()

    if not force:
        existing = conn.execute(
            "SELECT COUNT(*) FROM top_picks WHERE date=?",
            (today,),
        ).fetchone()[0]

        if existing > 0:
            conn.close()
            return

    conn.execute("DELETE FROM top_picks WHERE date=?", (today,))

    symbol_rs, symbol_sector = _sector_rs_map(conn)
    accum_map = _latest_accumulation_map(conn)
    syms = _universe(conn, limit=600)

    rows = []

    for sym in syms:
        try:
            r = meta_model.score_symbol(sym, use_yahoo=False)
        except Exception as e:
            print(f"[TOPPICKS] pwin skipped {sym}: {e}")
            continue

        if not r or r.get("p_win") is None:
            continue

        p_win = float(r["p_win"])

        accum = accum_map.get(sym)
        if accum is None:
            try:
                accum = institutional.accumulation_score(sym, conn)
            except Exception:
                accum = None

        if accum is None:
            accum = 0.5

        sector_rs = symbol_rs.get(sym, 0.5)
        sector = symbol_sector.get(sym)

        composite = (
            0.50 * p_win +
            0.30 * float(accum) +
            0.20 * float(sector_rs)
        )

        rows.append([
            today,
            sym,
            round(p_win, 3),
            round(float(accum), 3),
            round(float(sector_rs), 3),
            sector,
            0,
            round(composite, 3),
        ])

    rows.sort(key=lambda x: -x[7])

    # Only check live setup on top 50 to keep it fast.
    top50 = rows[:50]

    for row in top50:
        sym = row[1]
        setup = _detect_setup(conn, sym)
        row[6] = setup

        if setup:
            row[7] = round(row[7] + 0.10, 3)

    top50.sort(key=lambda x: -x[7])

    conn.executemany(
        "INSERT INTO top_picks VALUES (?,?,?,?,?,?,?,?)",
        top50,
    )

    conn.commit()
    conn.close()

    print(f"[TOPPICKS] computed {len(rows)} candidates -> stored {len(top50)}")


def top(n=15):
    conn = db.get_conn()
    _ensure(conn)

    rows = conn.execute(
        "SELECT symbol, p_win, accum, sector_rs, sector, setup, composite "
        "FROM top_picks "
        "WHERE date=(SELECT MAX(date) FROM top_picks) "
        "ORDER BY composite DESC LIMIT ?",
        (n,),
    ).fetchall()

    conn.close()

    return [
        {
            "symbol": s,
            "p_win": p,
            "accum": a,
            "sector_rs": sr,
            "sector": sec,
            "setup": bool(st),
            "composite": c,
        }
        for s, p, a, sr, sec, st, c in rows
    ]


if __name__ == "__main__":
    compute(force=True)

    print("TOP PICKS")
    print("-" * 70)

    for r in top(15):
        setup_tag = " 🏄 LIVE SETUP" if r["setup"] else ""
        print(
            f"{r['symbol']:<14} "
            f"comp {r['composite']:.2f} | "
            f"P(WIN) {r['p_win']:.0%} | "
            f"accum {r['accum']:.2f} | "
            f"sectorRS {r['sector_rs']:.2f} | "
            f"{r['sector'] or 'Unknown'}"
            f"{setup_tag}"
        )
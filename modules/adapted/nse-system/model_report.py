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
Model run ledger — every train / lift-test records its metrics.
Powers C3 lift re-test tracking + the Ledger UI panel (next batch).
"""
import datetime as dt

import db


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS model_runs(
        run_date TEXT, note TEXT, rows INTEGER, winners REAL,
        auc REAL, base_win REAL, top10_win REAL, n_features INTEGER,
        price_only_auc REAL, delta_auc REAL, delta_top10 REAL,
        PRIMARY KEY (run_date, note))""")


def record(m, note=None):
    conn = db.get_conn()
    _ensure(conn)
    today = dt.date.today().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO model_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            today,
            note or m.get("note", "train"),
            m.get("rows"),
            m.get("winners"),
            m.get("auc"),
            m.get("base_win"),
            m.get("top10_win"),
            m.get("n_features"),
            m.get("price_only_auc"),
            m.get("delta_auc"),
            m.get("delta_top10"),
        ),
    )
    conn.commit()
    conn.close()


def history(n=10):
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        "SELECT run_date, note, rows, auc, base_win, top10_win, "
        "price_only_auc, delta_auc, delta_top10 FROM model_runs "
        "ORDER BY run_date DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [
        {
            "run_date": r[0],
            "note": r[1],
            "rows": r[2],
            "auc": r[3],
            "base_win": r[4],
            "top10_win": r[5],
            "price_only_auc": r[6],
            "delta_auc": r[7],
            "delta_top10": r[8],
        }
        for r in rows
    ]


def run_lift():
    import meta_model

    return meta_model.lift_test()


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "history"
    if cmd == "lift":
        run_lift()
    else:
        for r in history():
            print(r)

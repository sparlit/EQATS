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
A3 — FII/DII daily cash-flow macro layer.
Sources: NSE archives (session-based, best-effort) or manual entry.

Usage:
  python macro.py            -> try auto-fetch (today, then up to 4 days back)
  python macro.py set F D    -> manual entry for today (in crores)
"""
import csv
import datetime as dt
import io
import sys

import db
import requests


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS macro_flow(
        date TEXT PRIMARY KEY, fii_net_cr REAL, dii_net_cr REAL)""")


def _parse_csv(text):
    """Parse NSE fii_stats CSV -> (fii_net_cr, dii_net_cr) or None."""
    fii_net = 0.0
    dii_net = 0.0
    found = False
    for row in csv.reader(io.StringIO(text)):
        if not row or len(row) < 5:
            continue
        client = row[0].strip().upper()
        try:
            net_val = float(row[4].replace(",", "").replace('"', "")) / 1e7
        except Exception:
            continue
        if "FII" in client or "FPI" in client:
            fii_net += net_val
            found = True
        elif "DII" in client or "MUTUAL" in client:
            dii_net += net_val
            found = True
    return (round(fii_net, 1), round(dii_net, 1)) if found else None


def _fetch_nse(day=None):
    """Best-effort fetch of one day's FII/DII provisional cash data."""
    d = day or dt.date.today()
    url = f"https://archives.nseindia.com/content/fo/fii_stats_{d.strftime('%d%m%Y')}.csv"
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36",
            "Accept": "text/csv,*/*;q=0.8",
            "Referer": "https://www.nseindia.com/",
        }
    )
    try:
        session.get("https://www.nseindia.com/", timeout=10)
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return None
        return _parse_csv(r.text)
    except Exception:
        return None


def set_flow(fii_net_cr, dii_net_cr, day=None):
    """Manual entry (crores)."""
    d = (day or dt.date.today()).isoformat()
    conn = db.get_conn()
    _ensure(conn)
    conn.execute("INSERT OR REPLACE INTO macro_flow VALUES (?,?,?)", (d, float(fii_net_cr), float(dii_net_cr)))
    conn.commit()
    conn.close()
    print(f"[MACRO] manual entry saved: {d} FII {fii_net_cr} / DII {dii_net_cr}")


def refresh():
    """Auto-fetch today, else most recent available day (up to 4 back)."""
    conn = db.get_conn()
    _ensure(conn)
    last = conn.execute("SELECT MAX(date) FROM macro_flow").fetchone()[0]
    conn.close()
    for back in range(5):
        day = dt.date.today() - dt.timedelta(days=back)
        iso = day.isoformat()
        if last and iso <= last:
            break  # nothing newer to fetch
        got = _fetch_nse(day)
        if got is None:
            continue
        fii, dii = got
        conn = db.get_conn()
        conn.execute("INSERT OR REPLACE INTO macro_flow VALUES (?,?,?)", (iso, fii, dii))
        conn.commit()
        conn.close()
        print(f"[MACRO] stored {iso}: FII {fii:+.1f} cr, DII {dii:+.1f} cr")
        return True
    print("[MACRO] no new FII/DII data (NSE blocked / holiday)")
    return False


def latest():
    conn = db.get_conn()
    _ensure(conn)
    row = conn.execute("SELECT date, fii_net_cr, dii_net_cr FROM macro_flow ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return None
    return {"date": row[0], "fii_net": row[1], "dii_net": row[2], "net_flow": round(row[1] + row[2], 1)}


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "set":
        set_flow(float(sys.argv[2]), float(sys.argv[3]))
    else:
        refresh()
    print(latest())

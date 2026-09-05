"""
A3 — FII/DII daily cash-flow macro layer.
Sources: NSE archives (session-based, best-effort) or manual entry.

Usage:
  python macro.py            -> try auto-fetch for today
  python macro.py set F D    -> manual entry for today (in crores)
"""
import sys
import datetime as dt
import requests
import db
import io
import csv

def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS macro_flow(
        date TEXT PRIMARY KEY, fii_net_cr REAL, dii_net_cr REAL)""")

def _parse_csv(text):
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
    return (fii_net, dii_net) if found else None

def _fetch_nse():
    d = dt.date.today()
    url = ("https://archives.nseindia.com/content/fo/"
           f"fii_stats_{d.strftime('%d%m%Y')}.csv")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Accept": "text/csv,*/*;q=0.8",
        "Referer": "https://www.nseindia.com/",
    })
    try:
        session.get("https://www.nseindia.com/", timeout=10)
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return None
        if "<html" in r.text[:300].lower():
            return None
        return _parse_csv(r.text)
    except Exception as e:
        print(f"[MACRO] NSE fetch failed: {e}")
        return None

def set_flow(fii, dii):
    conn = db.get_conn()
    _ensure(conn)
    today = dt.date.today().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO macro_flow(date, fii_net_cr, dii_net_cr) "
        "VALUES (?,?,?)", (today, round(fii, 2), round(dii, 2)))
    conn.commit()
    conn.close()
    print(f"[MACRO] manual set: FII {fii:+.0f}Cr, DII {dii:+.0f}Cr")

def refresh():
    res = _fetch_nse()
    if res:
        set_flow(*res)
        print(f"[MACRO] fetched: FII {res[0]:+.0f}Cr, DII {res[1]:+.0f}Cr")
    else:
        print("[MACRO] auto-fetch skipped (NSE blocked / market closed). "
              "Use: python macro.py set <fii> <dii>")

def latest():
    conn = db.get_conn()
    _ensure(conn)
    row = conn.execute(
        "SELECT date, fii_net_cr, dii_net_cr FROM macro_flow "
        "ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return None
    return {"date": row[0], "fii_net": row[1], "dii_net": row[2],
            "net_flow": row[1] + row[2]}

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "set":
        set_flow(float(sys.argv[2]), float(sys.argv[3]))
    else:
        refresh()
    print(latest())
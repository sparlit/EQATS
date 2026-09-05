import sys
import datetime as dt
import requests
import db

URL = "https://scanner.tradingview.com/india/scan"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MIN_MCAP_CR = 1000

COLS = ["description", "close", "market_cap_basic",
        "price_earnings_ttm", "Perf.1M", "Perf.3M",
        "relative_volume_1D", "volume", "average_volume_10D_calc"]

def classify(p1, p3, rv):
    p1 = p1 or 0
    p3 = p3 or 0
    if rv is not None and rv >= 2:
        return "VOL"
    if p1 >= 10 and p3 >= 8:
        return "MOM"
    if p1 >= 7 and p3 <= 0:
        return "TURN"
    return None

def fetch():
    body = {
        "filter": [
            {"left": "exchange", "operation": "equal", "right": "NSE"},
            {"left": "market_cap_basic", "operation": "egreater",
             "right": MIN_MCAP_CR * 1e7},
        ],
        "options": {"lang": "en"},
        "range": [0, 3000],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "symbols": {"query": {"types": ["stock"]}, "tickers": []},
        "columns": COLS,
    }
    r = requests.post(URL, headers=HEADERS, json=body, timeout=40)
    if r.status_code != 200:
        print("HTTP", r.status_code, r.text[:500])
        return []
    return r.json().get("data", [])

def run():
    conn = db.get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS universe_broad(
        symbol TEXT PRIMARY KEY, name TEXT, mcap_cr REAL, close REAL,
        pe REAL, perf1m REAL, perf3m REAL, relvol REAL,
        updated_at TEXT)""")
    data = fetch()
    if not data:
        print("No data — paste me everything above this line")
        return
    now = dt.datetime.now().isoformat()
    n = 0
    pings = []
    for item in data:
        sym = item["s"].split(":")[-1]
        d = dict(zip(COLS, item["d"]))
        mcap = d.get("market_cap_basic")
        rv = d.get("relative_volume_1D")
        vol = d.get("volume")
        avg = d.get("average_volume_10D_calc")
        if rv is None and vol and avg:
            rv = vol / avg
        p1 = d.get("Perf.1M")
        p3 = d.get("Perf.3M")
        conn.execute(
            "INSERT OR REPLACE INTO universe_broad "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sym, d.get("description"),
             None if mcap is None else mcap / 1e7,
             d.get("close"), d.get("price_earnings_ttm"),
             p1, p3, rv, now))
        n += 1
        tag = classify(p1, p3, rv)
        if tag:
            pings.append((sym, tag, p1 or 0, rv))
    conn.commit()
    print(f"Broad universe stored: {n} stocks")
    print(f"Emerging pings today: {len(pings)}")
    for sym, tag, p1, rv in pings[:25]:
        rvs = f" vol {rv:.1f}x" if rv is not None else ""
        print(f"   [{tag}] {sym}: 1M {p1:+.1f}%{rvs}")
    conn.close()

if len(sys.argv) > 1 and sys.argv[1] == "run":
    run()
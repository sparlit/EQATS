import sys
import time
import datetime as dt
import yfinance as yf
import db
from config import HISTORY_YEARS, SLEEP_SECONDS

def fetch_one(conn, symbol):
    meta = conn.execute(
        "SELECT last_date FROM price_meta WHERE symbol=?", (symbol,)).fetchone()
    last = meta[0] if meta else None
    if last:
        start = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
    else:
        start = (dt.date.today() - dt.timedelta(days=365 * HISTORY_YEARS)).isoformat()
    if start > dt.date.today().isoformat():
        return 0

    tk = yf.Ticker(symbol + ".NS")
    df = tk.history(start=start, auto_adjust=True)
    if df.empty:
        return 0

    rows = [(symbol, str(idx.date()), float(o), float(h), float(l), float(c), float(v))
            for idx, o, h, l, c, v in
            zip(df.index, df["Open"], df["High"], df["Low"], df["Close"], df["Volume"])]
    conn.executemany("INSERT OR REPLACE INTO prices_daily VALUES (?,?,?,?,?,?,?)", rows)

    last_row = conn.execute(
        "SELECT MAX(date), COUNT(*) FROM prices_daily WHERE symbol=?",
        (symbol,)).fetchone()
    conn.execute("INSERT OR REPLACE INTO price_meta VALUES (?,?,?,?)",
                 (symbol, last_row[0], last_row[1], dt.datetime.now().isoformat()))
    conn.commit()
    return len(rows)

def run(show_every=1):
    conn = db.get_conn()
    symbols = [r[0] for r in conn.execute(
        "SELECT symbol FROM stocks WHERE active=1 ORDER BY symbol")]
    total = len(symbols)
    failed = []
    for i, sym in enumerate(symbols, 1):
        ok = False
        for attempt in range(3):
            try:
                n = fetch_one(conn, sym)
                if show_every:
                    print(f"[{i}/{total}] {sym}: +{n} rows")
                ok = True
                break
            except Exception as e:
                print(f"[{i}/{total}] {sym} attempt {attempt+1} failed: {e}")
                time.sleep(5 * (attempt + 1))
        if not ok:
            failed.append(sym)
        time.sleep(SLEEP_SECONDS)

    print("FAILED SYMBOLS:", failed if failed else "none")
    total_rows = conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
    print(f"Total price rows in database: {total_rows}")
    conn.close()
    return failed

if len(sys.argv) > 1 and sys.argv[1] == "run":
    run()
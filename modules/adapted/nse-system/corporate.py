import sys
import datetime as dt
import yfinance as yf
import db

BANK_KEYS = ["BANK", "FINANC", "NBFC"]

TAG_RULES = [
    ("RESULTS", ["results", "profit", "loss", "earnings",
                 "quarter", "revenue"]),
    ("DIVIDEND", ["dividend"]),
    ("BUYBACK/SPLIT/BONUS", ["buyback", "bonus", "split"]),
    ("DEALS/STAKE", ["block deal", "bulk deal", "stake",
                     "acquisition", "merger"]),
    ("ORDERS/CONTRACTS", ["order", "contract", "bagged", "deal win"]),
    ("REGULATORY/RED", ["sebi", "probe", "penalty", "fraud",
                        "notice", "default", "allegation"]),
]

def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS corp_calendar(
        symbol TEXT, event_date TEXT, kind TEXT, detail TEXT)""")

def is_financial(sector):
    s = (sector or "").upper()
    for k in BANK_KEYS:
        if k in s:
            return True
    return False

def fetch_calendar(symbol):
    conn = db.get_conn()
    ensure(conn)
    conn.execute("DELETE FROM corp_calendar WHERE symbol=?", (symbol,))
    tk = yf.Ticker(symbol + ".NS")
    n = 0
    try:
        ed = tk.earnings_dates
        if ed is not None and len(ed) > 0:
            for idx in ed.index:
                d = str(idx)[:10]
                conn.execute(
                    "INSERT INTO corp_calendar VALUES (?,?,?,?)",
                    (symbol, d, "RESULTS", "earnings date"))
                n += 1
    except Exception as e:
        print("earnings dates failed:", e)
    try:
        act = tk.actions
        if act is not None and len(act) > 0:
            for idx, r in act.iterrows():
                d = str(idx)[:10]
                div = r.get("Dividends")
                spl = r.get("Stock Splits")
                if div is not None and div == div and div != 0:
                    conn.execute(
                        "INSERT INTO corp_calendar VALUES (?,?,?,?)",
                        (symbol, d, "DIVIDEND", f"Rs {round(div,2)}"))
                    n += 1
                if spl is not None and spl == spl and spl != 0:
                    conn.execute(
                        "INSERT INTO corp_calendar VALUES (?,?,?,?)",
                        (symbol, d, "SPLIT", f"ratio {spl}"))
                    n += 1
    except Exception as e:
        print("actions failed:", e)
    conn.commit()
    conn.close()
    return n

def tag_headlines(conn, symbol):
    rows = conn.execute(
        "SELECT title, age_days, label FROM sentiment_headlines "
        "WHERE symbol=? ORDER BY age_days", (symbol,)).fetchall()
    out = []
    for title, age, label in rows:
        t = title.lower()
        tags = [name for name, keys in TAG_RULES
                if any(k in t for k in keys)]
        out.append((title, age, label, tags))
    return out

def red_flags(conn, symbol):
    flags = []
    cols = [c[1] for c in conn.execute("PRAGMA table_info(fundamentals)")]
    row = conn.execute(
        "SELECT * FROM fundamentals WHERE symbol=?", (symbol,)).fetchone()
    sec = conn.execute(
        "SELECT sector FROM stocks WHERE symbol=?", (symbol,)).fetchone()
    sector = sec[0] if sec else None
    if row:
        m = dict(zip(cols, row))
        de = m.get("debt_to_equity")
        if de is not None and de > 1.5 and not is_financial(sector):
            flags.append(f"HIGH DEBT: D/E {de:.2f}")
        pl = m.get("pledge_pct")
        if pl is not None and pl > 5:
            flags.append(f"PLEDGE: {pl:.1f}%")
        if m.get("cfo_positive") == 0:
            flags.append("NEGATIVE OPERATING CASH FLOW")
    neg = conn.execute(
        "SELECT COUNT(*) FROM sentiment_headlines "
        "WHERE symbol=? AND label='negative' AND age_days<=7",
        (symbol,)).fetchone()[0]
    if neg >= 2:
        flags.append(f"{neg} NEGATIVE NEWS IN 7 DAYS")
    today = dt.date.today()
    soon = conn.execute(
        "SELECT event_date FROM corp_calendar "
        "WHERE symbol=? AND kind='RESULTS' AND event_date>=? "
        "AND event_date<=? ORDER BY event_date LIMIT 1",
        (symbol, today.isoformat(),
         (today + dt.timedelta(days=7)).isoformat())).fetchone()
    if soon:
        flags.append(f"RESULTS ON {soon[0]} (event risk)")
    t = conn.execute(
        "SELECT above200, rsi FROM technicals_daily "
        "WHERE symbol=? ORDER BY date DESC LIMIT 1",
        (symbol,)).fetchone()
    if t:
        if t[0] == 0:
            flags.append("BELOW 200-DAY AVERAGE")
        if t[1] is not None and t[1] >= 75:
            flags.append(f"OVERBOUGHT RSI {t[1]:.0f}")
        if t[1] is not None and t[1] <= 25:
            flags.append(f"OVERSOLD RSI {t[1]:.0f}")
    return flags

def report(symbol):
    conn = db.get_conn()
    print("UPCOMING CORPORATE EVENTS:")
    for r in conn.execute(
            "SELECT event_date, kind, detail FROM corp_calendar "
            "WHERE symbol=? AND event_date>=? "
            "ORDER BY event_date LIMIT 8",
            (symbol, dt.date.today().isoformat())):
        print("  ", r)
    print("TAGGED HEADLINES:")
    for title, age, label, tags in tag_headlines(conn, symbol)[:8]:
        print(f"   [{age}d|{label}] {title} {tags}")
    print("RED FLAGS:")
    fl = red_flags(conn, symbol)
    if fl:
        for f in fl:
            print("   🚩", f)
    else:
        print("   none")
    conn.close()

if len(sys.argv) > 2 and sys.argv[1] == "run":
    for s in sys.argv[2:]:
        s = s.upper()
        print(f"--- {s} ---")
        fetch_calendar(s)
        report(s)
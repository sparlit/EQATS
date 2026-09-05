import sys
import datetime as dt
import db

def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS events(
        date TEXT, symbol TEXT, kind TEXT, text TEXT)""")

def detect():
    conn = db.get_conn()
    ensure(conn)
    today = dt.date.today().isoformat()
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM technicals_daily "
        "ORDER BY date DESC LIMIT 2")]
    if len(dates) < 2:
        print("Events: run again tomorrow (needs 2 days)")
        return
    prev = dates[1]
    conn.execute("DELETE FROM events WHERE date=?", (today,))
    cur = {r[0]: r for r in conn.execute(
        "SELECT * FROM technicals_daily WHERE date=?", (today,))}
    pre = {r[0]: r for r in conn.execute(
        "SELECT * FROM technicals_daily WHERE date=?", (prev,))}
    ev = []
    for sym, t in cur.items():
        p = pre.get(sym)
        if p is None:
            continue
        if p[11] == 0 and t[11] == 1:
            ev.append((sym, "CROSS_UP_200",
                       f"{sym} crossed ABOVE 200-day average"))
        if p[11] == 1 and t[11] == 0:
            ev.append((sym, "CROSS_DOWN_200",
                       f"{sym} fell BELOW 200-day average"))
        if t[7] >= 2.5:
            ev.append((sym, "VOL_SPIKE",
                       f"{sym} volume {t[7]:.1f}x 20-day average"))
        if t[2] >= t[8] * 0.995 and p[2] < p[8] * 0.995:
            ev.append((sym, "NEW_52W_HIGH", f"{sym} touched 52-week high"))
        if p[3] <= p[4] and t[3] > t[4]:
            ev.append((sym, "GOLDEN_CROSS",
                       f"{sym} 20DMA crossed above 50DMA"))
        if p[3] >= p[4] and t[3] < t[4]:
            ev.append((sym, "DEATH_CROSS",
                       f"{sym} 20DMA crossed below 50DMA"))
        if t[6] >= 70:
            ev.append((sym, "OVERBOUGHT", f"{sym} RSI {t[6]:.0f}"))
        if t[6] <= 30:
            ev.append((sym, "OVERSOLD", f"{sym} RSI {t[6]:.0f}"))
    rec_now = {r[0] for r in conn.execute(
        "SELECT symbol FROM pipeline WHERE status='Recommended'")}
    seen = {r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM events WHERE kind='NEW_RECOMMENDED'")}
    for sym in rec_now - seen:
        ev.append((sym, "NEW_RECOMMENDED", f"{sym} entered Recommended"))
    for sym, kind, text in ev:
        conn.execute("INSERT INTO events VALUES (?,?,?,?)",
                     (today, sym, kind, text))
    conn.commit()
    print(f"Events detected today: {len(ev)}")
    conn.close()

if len(sys.argv) > 1 and sys.argv[1] == "run":
    detect()
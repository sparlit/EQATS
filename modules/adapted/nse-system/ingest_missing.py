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


"""One-time: download history for tracked symbols missing recent data."""
import datetime as dt
import time

import data_quality
import db
import yfinance as yf


def main():
    conn = db.get_conn()
    r = conn.execute("SELECT MAX(date) FROM prices_daily").fetchone()
    latest = data_quality._parse_date(r[0])
    cutoff = (latest - dt.timedelta(days=10)).isoformat()
    recent = {x[0] for x in conn.execute("SELECT DISTINCT symbol FROM prices_daily WHERE date>=?", (cutoff,))}
    tracked = data_quality._get_universe_symbols(conn)
    missing = [s for s in tracked if s not in recent]
    conn.close()
    print(f"missing symbols: {len(missing)}")

    conn = db.get_conn()
    done = 0
    for sym in missing:
        try:
            d = yf.Ticker(sym + ".NS").history(period="5y", auto_adjust=True)
        except Exception:
            continue
        if d is None or len(d) < 200:
            continue
        rows = []
        for idx, row in d.iterrows():
            rows.append(
                (
                    sym,
                    str(idx.date())[:10],
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    float(row["Volume"]),
                )
            )
        conn.executemany(
            "INSERT OR REPLACE INTO prices_daily (symbol, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        done += 1
        if done % 25 == 0:
            print(f"  ...{done}/{len(missing)}")
        time.sleep(0.2)
    conn.close()
    print(f"ingested {done} symbols")


if __name__ == "__main__":
    main()

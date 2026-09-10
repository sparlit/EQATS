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


import datetime as dt
import math

import db
import joblib
import numpy as np
import scoring
import yfinance as yf


def download_prices(conn, symbol):
    tk = yf.Ticker(symbol + ".NS")
    df = tk.history(period="5y", auto_adjust=True)
    if df is None or df.empty:
        return 0
    rows = []
    for idx, r in df.iterrows():
        o = float(r["Open"])
        h = float(r["High"])
        l = float(r["Low"])
        c = float(r["Close"])
        v = float(r["Volume"])
        if any(math.isnan(x) for x in (o, h, l, c, v)):
            continue
        rows.append((symbol, str(idx.date()), o, h, l, c, v))
    conn.executemany("INSERT OR REPLACE INTO prices_daily VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def predict_one(conn, symbol):
    rows = conn.execute(
        "SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 300", (symbol,)
    ).fetchall()
    rows = [r for r in rows if r[0] is not None]
    if len(rows) < 252:
        return None
    c = np.array([r[0] for r in reversed(rows)])
    feat = [
        c[-1] / c[-21] - 1,
        c[-1] / c[-63] - 1,
        c[-1] / c[-126] - 1,
        c[-1] / c[-252] - 1,
        float(np.std(np.diff(np.log(c))[-63:])),
        c[-1] / float(np.max(c[-252:])),
        c[-1] / float(np.min(c[-252:])),
        1 if c[-1] > np.mean(c[-50:]) else 0,
        1 if c[-1] > np.mean(c[-200:]) else 0,
    ]
    bundle = joblib.load("data/ml_models.pkl")
    p6 = float(bundle["m6"].predict(np.array([feat]))[0])
    p12 = float(bundle["m12"].predict(np.array([feat]))[0])
    final = round(50 * p6 + 50 * p12, 1)
    today = dt.date.today().isoformat()
    conn.execute("DELETE FROM ml_predictions WHERE prediction_date=? AND symbol=?", (today, symbol))
    conn.execute(
        "INSERT INTO ml_predictions VALUES (?,?,?,?,?,?,?)",
        (symbol, today, p6 * 100, p12 * 100, final, 50.0, bundle["version"]),
    )
    conn.commit()
    return final


def score_one(conn, symbol):
    today = dt.date.today().isoformat()
    medians = scoring.sector_pe_medians(conn)
    r = scoring.score_stock(conn, symbol, medians)
    if r is None:
        return None
    passed_all = all(g[1] for g in r["gates"])
    conn.execute("DELETE FROM scan_results WHERE scan_date=? AND symbol=?", (today, symbol))
    conn.execute(
        "INSERT INTO scan_results VALUES (?,?,?,?,?,?,?)",
        (today, symbol, 1 if passed_all else 0, r["composite"], None, "", None),
    )
    conn.execute("DELETE FROM scan_reasons WHERE scan_date=? AND symbol=?", (today, symbol))
    for name, ok, actual, expected, reason in r["gates"]:
        conn.execute(
            "INSERT INTO scan_reasons VALUES (?,?,?,?,?,?,?)",
            (
                today,
                symbol,
                name,
                1 if ok else 0,
                actual if isinstance(actual, (int, float)) else None,
                str(expected),
                reason,
            ),
        )
    for name, sc, w in [("ROCE", r["roce_s"], 40), ("Growth", r["growth_s"], 30), ("Valuation", r["val_s"], 30)]:
        conn.execute(
            "INSERT INTO scan_reasons VALUES (?,?,?,?,?,?,?)",
            (
                today,
                symbol,
                f"BAND {name} (w{w}%)",
                1 if sc is not None else 0,
                sc,
                "",
                f"{name} score {sc}" if sc is not None else f"{name} data missing",
            ),
        )
    conn.commit()
    return r["composite"]


def ensure_symbol(symbol):
    conn = db.get_conn()
    have = conn.execute("SELECT COUNT(*) FROM prices_daily WHERE symbol=?", (symbol,)).fetchone()[0]
    if have < 100:
        n = download_prices(conn, symbol)
        if n == 0:
            conn.close()
            return False
    havef = conn.execute("SELECT COUNT(*) FROM fundamentals WHERE symbol=?", (symbol,)).fetchone()[0]
    if havef == 0:
        import fundamentals_compute as fc

        nm = conn.execute("SELECT name FROM universe_broad WHERE symbol=?", (symbol,)).fetchone()
        name = nm[0] if nm else symbol
        sc = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (symbol,)).fetchone()
        sector = sc[0] if sc else None
        try:
            fc.fetch_one(conn, symbol, name, sector)
        except Exception as e:
            print("fundamentals failed:", e)
    predict_one(conn, symbol)
    score_one(conn, symbol)
    conn.close()
    return True

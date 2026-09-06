import sys
import datetime as dt
import numpy as np
import joblib
import db

def predict_all():
    conn = db.get_conn()
    bundle = joblib.load("data/ml_models.pkl")
    m6 = bundle["m6"]
    m12 = bundle["m12"]

    today = dt.date.today().isoformat()
    symbols = [r[0] for r in conn.execute(
        "SELECT symbol FROM stocks WHERE active=1")]
    rows_out = []
    for sym in symbols:
        rows = conn.execute(
            "SELECT close FROM prices_daily "
            "WHERE symbol=? ORDER BY date DESC LIMIT 300",
            (sym,)).fetchall()
        rows = [r for r in rows if r[0] is not None]
        if len(rows) < 252:
            continue
        c = np.array([r[0] for r in reversed(rows)])
        ret_1m = c[-1] / c[-21] - 1
        ret_3m = c[-1] / c[-63] - 1
        ret_6m = c[-1] / c[-126] - 1
        ret_12m = c[-1] / c[-252] - 1
        rets = np.diff(np.log(c))
        vol_3m = float(np.std(rets[-63:]))
        hi = float(np.max(c[-252:]))
        lo = float(np.min(c[-252:]))
        dist_high = c[-1] / hi
        dist_low = c[-1] / lo
        ma50 = float(np.mean(c[-50:]))
        ma200 = float(np.mean(c[-200:]))
        above_ma50 = 1 if c[-1] > ma50 else 0
        above_ma200 = 1 if c[-1] > ma200 else 0
        feat = [ret_1m, ret_3m, ret_6m, ret_12m, vol_3m,
                dist_high, dist_low, above_ma50, above_ma200]
        p6 = float(m6.predict(np.array([feat]))[0])
        p12 = float(m12.predict(np.array([feat]))[0])
        final = round(50 * p6 + 50 * p12, 1)
        rows_out.append([sym, p6 * 100, p12 * 100, final])

    rows_out.sort(key=lambda r: -r[3])
    n = len(rows_out)
    results = []
    for i, r in enumerate(rows_out):
        rank = round(100 * (n - i) / n, 1)
        results.append((r[0], today, r[1], r[2], r[3],
                        rank, bundle["version"]))

    conn.execute("DELETE FROM ml_predictions "
                 "WHERE prediction_date=?", (today,))
    conn.executemany(
        "INSERT INTO ml_predictions VALUES (?,?,?,?,?,?,?)", results)
    conn.commit()
    print(f"ML predictions stored: {n} stocks")
    conn.close()

if len(sys.argv) > 1 and sys.argv[1] == "run":
    predict_all()
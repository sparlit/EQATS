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
import os

import db
import joblib
import numpy as np
from ml_features import FEATURE_COLUMNS, latest_features

MODEL_PATH = "data/ml_models.pkl"
MODEL_VERSION = "v0.2-pit-safe"


def _compatible(bundle):
    meta = bundle.get("metadata", {}) if isinstance(bundle, dict) else {}
    return (
        isinstance(bundle, dict)
        and bundle.get("version") == MODEL_VERSION
        and bundle.get("feat_cols") == FEATURE_COLUMNS
        and meta.get("features") == FEATURE_COLUMNS
        and meta.get("imputation_medians")
    )


def predict_all():
    if not os.path.exists(MODEL_PATH):
        print(f"[ml] {MODEL_PATH} not found — run: python ml_train.py")
        return 0

    conn = db.get_conn()
    bundle = joblib.load(MODEL_PATH)
    if not _compatible(bundle):
        print("[ml] refusing incompatible/unversioned model; retrain required")
        conn.close()
        return 0
    m6 = bundle["m6"]
    m12 = bundle["m12"]

    today = dt.date.today().isoformat()
    symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1")]
    rows_out = []
    for sym in symbols:
        rows = conn.execute(
            "SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 300", (sym,)
        ).fetchall()
        rows = [r for r in rows if r[0] is not None]
        if len(rows) < 252:
            continue
        c = np.array([r[0] for r in reversed(rows)])
        feat = latest_features(c)
        if feat is None:
            continue
        medians = bundle["metadata"]["imputation_medians"]
        feat = [
            medians.get(k, 0.0) if not np.isfinite(v) else v
            for k, v in zip(FEATURE_COLUMNS, feat, strict=False)
        ]
        p6 = float(m6.predict(np.array([feat]))[0])
        p12 = float(m12.predict(np.array([feat]))[0])
        final = round(50 * p6 + 50 * p12, 1)
        rows_out.append([sym, p6 * 100, p12 * 100, final])

    rows_out.sort(key=lambda r: -r[3])
    n = len(rows_out)
    results = []
    for i, r in enumerate(rows_out):
        rank = round(100 * (n - i) / n, 1)
        results.append((r[0], today, r[1], r[2], r[3], rank, bundle["version"]))

    conn.execute("DELETE FROM ml_predictions WHERE prediction_date=?", (today,))
    conn.executemany("INSERT INTO ml_predictions VALUES (?,?,?,?,?,?,?)", results)
    conn.commit()
    print(f"ML predictions stored: {n} stocks")
    conn.close()
    return n


if __name__ == "__main__":
    predict_all()

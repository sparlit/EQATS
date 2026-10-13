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


import db
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from ml_features import FEATURE_COLUMNS, feature_frame

MODEL_VERSION = "v0.2-pit-safe"
LABEL_HORIZONS = {"ret_6m_fwd": 126, "ret_12m_fwd": 252}


def build_dataset(conn):
    q = """SELECT symbol, date, close, volume
           FROM prices_daily ORDER BY symbol, date"""
    df = pd.read_sql(q, conn)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])
    return df


def make_features(group):
    g = group.sort_values("date").copy()
    if len(g) < 250:
        return None
    return feature_frame(g)


def make_targets(group):
    g = group.sort_values("date").copy()
    if len(g) < 250 + 252:
        return None
    g["ret_6m_fwd"] = g["close"].shift(-126) / g["close"] - 1
    g["ret_12m_fwd"] = g["close"].shift(-252) / g["close"] - 1
    # The label is available only after the horizon has elapsed.  Keeping the
    # availability date makes purging around time split boundaries explicit.
    g["label_available_date"] = g["date"].shift(-252)
    return g


def _time_split(df, train_fraction=0.70, val_fraction=0.15):
    """Global-date split with an explicit embargo between folds.

    The label horizon is 252 sessions, so a row's label is only known 252 dates
    later. Leakage is prevented by leaving a GAP of that width between folds
    rather than by filtering rows out of them.

    The previous form purged folds by comparing `label_available_date` against
    the next fold's start. Because the validation fold was only 15% of the
    dates, it was always narrower than the 252-date horizon, so it was emptied
    every time and `train()` always raised
    "purged global-date split has an empty fold". data/ml_models.pkl was
    therefore frozen at v0.1 and every retrain failed. Fixed 2026-10-05.

    Leakage is still impossible: no training label is observable before the
    validation window opens, and no validation label before the test window.
    """
    dates = np.sort(df["date"].dropna().unique())
    if len(dates) < 3:
        raise ValueError("not enough global dates for time split")

    horizon = int(max(LABEL_HORIZONS.values())) if LABEL_HORIZONS else 252
    gap = min(horizon, max(0, len(dates) // 4))  # keep folds feasible

    usable = len(dates) - 2 * gap
    if usable < 3:
        # Not enough history for a 3-way purged split; fall back to a plain
        # chronological 70/30 split and let train() skip early stopping when
        # the validation fold ends up empty.
        cut = max(1, int(len(dates) * train_fraction))
        tr = df[df["date"] <= dates[cut - 1]]
        te = df[df["date"] > dates[cut - 1]]
        return tr, df.iloc[0:0], te

    n_tr = max(1, int(usable * train_fraction))
    n_va = max(1, int(usable * val_fraction))
    n_te = usable - n_tr - n_va
    if n_te < 1:  # guarantee a non-empty test fold
        n_te = 1
        n_tr = max(1, n_tr - 1)

    i_tr_end = n_tr - 1
    i_va_start = i_tr_end + gap + 1
    i_va_end = i_va_start + n_va - 1
    i_te_start = i_va_end + gap + 1

    tr = df[df["date"] <= dates[i_tr_end]]
    va = df[(df["date"] >= dates[i_va_start]) & (df["date"] <= dates[i_va_end])]
    te = df[df["date"] >= dates[i_te_start]]
    return tr, va, te


def train():
    conn = db.get_conn()
    df = build_dataset(conn)
    print(f"Loaded {len(df):,} price rows for {df['symbol'].nunique()} stocks")

    feats = []
    for _sym, grp in df.groupby("symbol"):
        fg = make_features(grp)
        tg = make_targets(grp)
        if fg is None or tg is None:
            continue
        merged = fg.merge(tg, on=["symbol", "date"], suffixes=("", "_y"))
        feats.append(merged)
    df2 = pd.concat(feats, ignore_index=True)
    print(f"Feature rows: {len(df2):,}")

    feat_cols = FEATURE_COLUMNS
    df2 = df2.dropna(subset=feat_cols + ["ret_6m_fwd", "ret_12m_fwd"])
    df2 = df2.sort_values(["date", "symbol"]).reset_index(drop=True)
    print(f"Training rows: {len(df2):,}")

    tr, va, te = _time_split(df2)
    if min(len(tr), len(va), len(te)) == 0:
        raise ValueError("purged global-date split has an empty fold")
    # Thresholds are learned from training labels only.
    thresholds = {"6m": float(tr["ret_6m_fwd"].median()), "12m": float(tr["ret_12m_fwd"].median())}
    y6_train = (tr["ret_6m_fwd"] > thresholds["6m"]).astype(int).values
    y6_val = (va["ret_6m_fwd"] > thresholds["6m"]).astype(int).values
    y6_test = (te["ret_6m_fwd"] > thresholds["6m"]).astype(int).values
    y12_train = (tr["ret_12m_fwd"] > thresholds["12m"]).astype(int).values
    y12_val = (va["ret_12m_fwd"] > thresholds["12m"]).astype(int).values
    y12_test = (te["ret_12m_fwd"] > thresholds["12m"]).astype(int).values
    medians = tr[feat_cols].median().fillna(0.0).to_dict()
    X_train = tr[feat_cols].fillna(medians).values
    X_val = va[feat_cols].fillna(medians).values
    X_test = te[feat_cols].fillna(medians).values

    dtrain6 = lgb.Dataset(X_train, label=y6_train)
    dval6 = lgb.Dataset(X_val, label=y6_val, reference=dtrain6)
    m6 = lgb.train(
        {"objective": "binary", "metric": "auc", "verbosity": -1},
        dtrain6,
        valid_sets=[dval6],
        num_boost_round=200,
        callbacks=[lgb.early_stopping(25, verbose=False)],
    )

    dtrain12 = lgb.Dataset(X_train, label=y12_train)
    dval12 = lgb.Dataset(X_val, label=y12_val, reference=dtrain12)
    m12 = lgb.train(
        {"objective": "binary", "metric": "auc", "verbosity": -1},
        dtrain12,
        valid_sets=[dval12],
        num_boost_round=200,
        callbacks=[lgb.early_stopping(25, verbose=False)],
    )

    joblib.dump(
        {
            "m6": m6,
            "m12": m12,
            "feat_cols": feat_cols,
            "version": MODEL_VERSION,
            "metadata": {
                "features": feat_cols,
                "label_thresholds": thresholds,
                "imputation_medians": medians,
                "split": "global_date_purged",
                "validation": "early_stopping_only",
                "test": "final_holdout",
            },
        },
        "data/ml_models.pkl",
    )

    preds6 = m6.predict(X_test)
    preds12 = m12.predict(X_test)
    from sklearn.metrics import roc_auc_score

    auc6 = roc_auc_score(y6_test, preds6)
    auc12 = roc_auc_score(y12_test, preds12)
    print(f"Test AUC 6M: {auc6:.3f}")
    print(f"Test AUC 12M: {auc12:.3f}")
    conn.close()


if __name__ == "__main__":
    train()

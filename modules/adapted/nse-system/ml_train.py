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


def build_dataset(conn):
    q = """SELECT symbol, date, close, volume
           FROM prices_daily ORDER BY symbol, date"""
    df = pd.read_sql(q, conn)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["symbol", "date"])


def make_features(group):
    g = group.sort_values("date").copy()
    if len(g) < 250:
        return None
    c = g["close"]
    g["ret_1m"] = c.pct_change(21)
    g["ret_3m"] = c.pct_change(63)
    g["ret_6m"] = c.pct_change(126)
    g["ret_12m"] = c.pct_change(252)
    g["vol_3m"] = c.pct_change().rolling(63).std()
    g["dist_high"] = c / c.rolling(252).max()
    g["dist_low"] = c / c.rolling(252).min()
    g["ma50"] = c.rolling(50).mean()
    g["ma200"] = c.rolling(200).mean()
    g["above_ma50"] = (c > g["ma50"]).astype(int)
    g["above_ma200"] = (c > g["ma200"]).astype(int)
    return g


def make_targets(group):
    g = group.sort_values("date").copy()
    if len(g) < 250 + 252:
        return None
    g["ret_6m_fwd"] = g["close"].shift(-126) / g["close"] - 1
    g["ret_12m_fwd"] = g["close"].shift(-252) / g["close"] - 1
    return g


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

    feat_cols = [
        "ret_1m",
        "ret_3m",
        "ret_6m",
        "ret_12m",
        "vol_3m",
        "dist_high",
        "dist_low",
        "above_ma50",
        "above_ma200",
    ]
    df2 = df2.dropna(subset=[*feat_cols, "ret_6m_fwd", "ret_12m_fwd"])
    print(f"Training rows: {len(df2):,}")

    X = df2[feat_cols].values
    y6 = (df2["ret_6m_fwd"] > df2["ret_6m_fwd"].median()).astype(int)
    y12 = (df2["ret_12m_fwd"] > df2["ret_12m_fwd"].median()).astype(int)

    n = len(X)
    train_end = int(n * 0.7)
    val_end = int(n * 0.85)

    X_train, X_val, X_test = (X[:train_end], X[train_end:val_end], X[val_end:])
    y6_train, y6_val, y6_test = (y6[:train_end], y6[train_end:val_end], y6[val_end:])
    y12_train, y12_val, y12_test = (y12[:train_end], y12[train_end:val_end], y12[val_end:])

    dtrain6 = lgb.Dataset(X_train, label=y6_train)
    dval6 = lgb.Dataset(X_val, label=y6_val, reference=dtrain6)
    m6 = lgb.train(
        {"objective": "binary", "metric": "auc", "verbosity": -1}, dtrain6, valid_sets=[dval6], num_boost_round=200
    )

    dtrain12 = lgb.Dataset(X_train, label=y12_train)
    dval12 = lgb.Dataset(X_val, label=y12_val, reference=dtrain12)
    m12 = lgb.train(
        {"objective": "binary", "metric": "auc", "verbosity": -1}, dtrain12, valid_sets=[dval12], num_boost_round=200
    )

    joblib.dump({"m6": m6, "m12": m12, "feat_cols": feat_cols, "version": "v0.1"}, "data/ml_models.pkl")

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

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


"""
Setup Meta-Model — expanded feature set (C3).
Features: momentum + structure + volume + fundamentals + sentiment + sector strength.
Weekly auto-retrain.
"""
import sys

import db
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

MODEL_PATH = "data/meta_model.pkl"

_MODEL = None


def get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = joblib.load(MODEL_PATH)
    return _MODEL


FEATURES = [
    "mom1",
    "mom3",
    "mom6",
    "d52",
    "above200",
    "slope200",
    "pb",
    "d10",
    "d20",
    "atr",
    "rv",
    "vc",
    "roce",
    "pe",
    "debt_eq",
    "promoter",
    "sector_rs",
    "sentiment",
]

CONTEXT_FEATS = {"roce", "pe", "debt_eq", "promoter", "sector_rs", "sentiment"}
PRICE_FEATS = [f for f in FEATURES if f not in CONTEXT_FEATS]


def _symbols(conn, limit=400):
    rows = conn.execute(
        "SELECT symbol FROM universe_broad WHERE mcap_cr BETWEEN 1000 "
        "AND 8000 AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
        "ORDER BY mcap_cr DESC LIMIT ?",
        (limit,),
    ).fetchall()
    core = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1")]
    return sorted({r[0] for r in rows} | set(core))


def _fund_map(conn):
    m = {}
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fundamentals)")]
    except Exception:
        return m

    pick = {}
    for want, aliases in [
        ("roce", ["roce"]),
        ("pe", ["pe", "pe_ttm"]),
        ("debt_eq", ["debt_to_equity", "debt_equity", "de_ratio", "de"]),
        ("promoter", ["promoter_holding", "promoter_pct", "promoter"]),
    ]:
        for a in aliases:
            if a in cols:
                pick[want] = a
                break

    if not pick:
        return m

    sel = ", ".join(pick.values())
    try:
        rows = conn.execute(f"SELECT symbol, {sel} FROM fundamentals").fetchall()
        for row in rows:
            sym = row[0]
            vals = [row[i + 1] for i in range(len(pick))]
            m[sym] = dict(zip(pick.keys(), vals, strict=False))
    except Exception:
        pass
    return m


def _sentiment_map(conn):
    m = {}
    try:
        rows = conn.execute("""
            SELECT symbol, AVG(
                CASE LOWER(label)
                    WHEN 'positive' THEN 1.0
                    WHEN 'bullish' THEN 1.0
                    WHEN 'negative' THEN -1.0
                    WHEN 'bearish' THEN -1.0
                    ELSE 0.0
                END) as sent
            FROM sentiment_headlines
            WHERE age_days <= 30
            GROUP BY symbol
        """).fetchall()
        for sym, sent in rows:
            if sent is not None:
                m[sym] = float(sent)
    except Exception:
        pass
    return m


def _sector_rs_map(conn):
    try:
        import sector_gate

        g = sector_gate.sector_perf(conn)
        if g.empty:
            return {}
        n = len(g)
        ranks = {}
        for i, (_, row) in enumerate(g.iterrows()):
            ranks[row["sector"]] = 1.0 - (i / max(1, n - 1))
        sym_sector = {}
        for sym, sec in conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL"):
            sym_sector[sym] = sec
        return {sym: ranks.get(sec, 0.5) for sym, sec in sym_sector.items()}
    except Exception:
        return {}


def _features_df(df, ctx):
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    e10 = c.ewm(span=10, adjust=False).mean()
    e20 = c.ewm(span=20, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    fut_max = h.iloc[::-1].rolling(20, min_periods=1).max().iloc[::-1].shift(-1)

    out = pd.DataFrame(index=df.index)
    out["mom1"] = c / c.shift(21) - 1
    out["mom3"] = c / c.shift(63) - 1
    out["mom6"] = c / c.shift(126) - 1
    out["d52"] = c / h.rolling(252).max()
    out["above200"] = (c > e200).astype(float)
    out["slope200"] = e200 / e200.shift(20) - 1
    out["rv"] = v / v.rolling(50).mean()
    out["vc"] = v / v.rolling(20).mean()
    out["pb"] = h.rolling(25).max() / c - 1
    out["d10"] = c / e10 - 1
    out["d20"] = c / e20 - 1
    out["atr"] = tr.rolling(14).mean() / c
    out["roce"] = ctx.get("roce")
    out["pe"] = ctx.get("pe")
    out["debt_eq"] = ctx.get("debt_eq")
    out["promoter"] = ctx.get("promoter")
    out["sector_rs"] = ctx.get("sector_rs")
    out["sentiment"] = ctx.get("sentiment")
    out["win"] = ((fut_max / c - 1) >= 0.10).astype(float)
    return out


def _coerce_numeric(df):
    """Force every feature column to float dtype."""
    for col in FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def train():
    conn = db.get_conn()
    fund = _fund_map(conn)
    sent = _sentiment_map(conn)
    srs = _sector_rs_map(conn)

    frames = []
    for sym in _symbols(conn):
        rows = conn.execute(
            "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
        ).fetchall()
        if len(rows) < 300:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "close", "high", "low", "volume"])
        df["date"] = pd.to_datetime(df["date"])

        f = fund.get(sym, {})
        ctx = {
            "roce": f.get("roce"),
            "pe": f.get("pe"),
            "debt_eq": f.get("debt_eq"),
            "promoter": f.get("promoter"),
            "sector_rs": srs.get(sym),
            "sentiment": sent.get(sym),
        }

        feat = _features_df(df, ctx)
        feat["date"] = df["date"]
        feat = feat.iloc[::5]
        feat = feat.dropna(subset=[*PRICE_FEATS, "win"])
        frames.append(feat)
    conn.close()

    data = pd.concat(frames, ignore_index=True)
    if data.empty:
        print("no training rows - check prices_daily")
        return

    for f in CONTEXT_FEATS:
        if f in data.columns:
            data[f] = pd.to_numeric(data[f], errors="coerce")
            med = data[f].median()
            data[f] = data[f].fillna(med if pd.notna(med) else 0.0)

    data = _coerce_numeric(data)
    data = data.sort_values("date")
    cutoff = data["date"].quantile(0.8)
    tr = data[data["date"] <= cutoff]
    te = data[data["date"] > cutoff]

    Xtr, ytr = tr[FEATURES], tr["win"]
    Xte, yte = te[FEATURES], te["win"]

    model = lgb.LGBMClassifier(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        min_child_samples=50,
        subsample=0.9,
        colsample_bytree=0.9,
        verbose=-1,
    )
    model.fit(Xtr, ytr, eval_set=[(Xte, yte)], eval_metric="auc", callbacks=[lgb.early_stopping(50, verbose=False)])

    proba = model.predict_proba(Xte)[:, 1]
    base = yte.mean()
    from sklearn.metrics import roc_auc_score

    auc = roc_auc_score(yte, proba)
    order = np.argsort(-proba)
    top = int(max(1, len(proba) * 0.10))
    top_rate = yte.iloc[order[:top]].mean()

    joblib.dump(model, MODEL_PATH)
    print(f"rows {len(data)} | winners {data['win'].mean():.1%}")
    print(f"test AUC {auc:.3f} | base win {base:.1%} | top-10% win {top_rate:.1%}")
    print(f"features: {len(FEATURES)} (incl. fundamentals + sentiment + sector)")
    print(f"model saved to {MODEL_PATH}")


def score_symbol(sym, use_yahoo=True):
    model = get_model()
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
    ).fetchall()
    conn.close()

    if len(rows) >= 300:
        df = pd.DataFrame(list(rows), columns=["date", "close", "high", "low", "volume"])
    elif use_yahoo:
        try:
            import yfinance as yf

            d = yf.Ticker(sym + ".NS").history(period="5y", auto_adjust=True)
        except Exception:
            return None
        if d is None or len(d) < 300:
            return None
        df = pd.DataFrame(
            {
                "close": d["Close"].values,
                "high": d["High"].values,
                "low": d["Low"].values,
                "volume": d["Volume"].values,
            }
        )
    else:
        return None

    conn2 = db.get_conn()
    fund = _fund_map(conn2)
    sent = _sentiment_map(conn2)
    srs = _sector_rs_map(conn2)
    conn2.close()
    f = fund.get(sym, {})
    ctx = {
        "roce": f.get("roce"),
        "pe": f.get("pe"),
        "debt_eq": f.get("debt_eq"),
        "promoter": f.get("promoter"),
        "sector_rs": srs.get(sym),
        "sentiment": sent.get(sym),
    }

    feat = _features_df(df, ctx)
    feat = feat.dropna(subset=PRICE_FEATS)
    if feat.empty:
        return None
    feat = feat.tail(1).copy()
    feat = _coerce_numeric(feat)
    for col in CONTEXT_FEATS:
        if col in feat.columns and pd.isna(feat[col].iloc[0]):
            feat[col] = 0.0

    p = model.predict_proba(feat[FEATURES])[:, 1][0]
    contrib = model.booster_.predict(feat[FEATURES], pred_contrib=True)[0]
    parts = sorted(zip(FEATURES, contrib, strict=False), key=lambda x: -abs(x[1]))[:5]
    why = [{"feature": k, "impact": round(float(v), 3)} for k, v in parts]
    return {"symbol": sym, "p_win": round(float(p), 3), "why": why}


def rank_symbols(syms, use_yahoo=False):
    out = []
    for s in syms:
        r = score_symbol(s, use_yahoo=use_yahoo)
        if r and r.get("p_win") is not None:
            out.append({"symbol": s, "p_win": r["p_win"]})
    out.sort(key=lambda x: -x["p_win"])
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "train":
        train()
    else:
        print(score_symbol(cmd))

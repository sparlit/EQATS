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
Setup Meta-Model v7 — C3 + Secret Sauce + Pattern flags + DTW + Delivery
+ trend-persistence features.
Features: price/derived history only. Current fundamentals, sentiment and
sector context are intentionally excluded until point-in-time history exists.
+ vcr/ret_std20/below52 + 7 pattern flags + dtw_sim
+ delivery_sim + days_above_200_30 + days_above_50_30 + ema200_dist_z.
Weekly auto-retrain. Metrics auto-recorded to model_runs.
"""
import datetime as dt
import json
import sys

import db
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import universe_helper as U

MODEL_PATH = "data/meta_model.pkl"
_MODEL = None
_MODEL_METADATA = {}
_WARNED_OLD = False
MODEL_VERSION = "v8-pit-safe"
LABEL_HORIZON = 20
LABEL_DESCRIPTION = (
    "+10% high within next 20 sessions; uncalibrated event score, not trade win probability"
)


def get_model():
    global _MODEL, _MODEL_METADATA, _WARNED_OLD
    if _MODEL is not None:
        return _MODEL
    try:
        loaded = joblib.load(MODEL_PATH)
    except FileNotFoundError:
        print(f"[META] model not found at {MODEL_PATH} — run train first")
        return None
    except Exception as e:
        print(f"[META] failed to load model: {e}")
        return None

    if isinstance(loaded, dict) and "model" in loaded:
        model = loaded["model"]
        feats = loaded.get("features", [])
        metadata = loaded.get("metadata", {})
        if (
            loaded.get("version") != MODEL_VERSION
            or feats != FEATURES
            or metadata.get("label") != LABEL_DESCRIPTION
            or metadata.get("context_features_excluded") != sorted(CONTEXT_FEATS)
        ):
            print(
                f"[META] model feature mismatch: "
                f"model version/metadata is incompatible with {MODEL_VERSION}. "
                f"Retrain required."
            )
            return None
        _MODEL = model
        _MODEL_METADATA = metadata
        return _MODEL

    if not _WARNED_OLD:
        print("[META] refusing legacy/unversioned model. Retrain required.")
        _WARNED_OLD = True
    return None


def reload_model():
    global _MODEL, _MODEL_METADATA
    _MODEL = None
    _MODEL_METADATA = {}
    return get_model()


def model_bundle_metadata(model=None):
    """Metadata for the currently accepted bundle (empty when unavailable)."""
    return dict(_MODEL_METADATA)


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
    "vcr",
    "ret_std20",
    "below52",
    "pat_htf",
    "pat_tri",
    "pat_db",
    "pat_flag",
    "pat_ihs",
    "pat_bear",
    "pat_any",
    "dtw_sim",
    "delivery_sim",
    "days_above_200_30",
    "days_above_50_30",
    "ema200_dist_z",
]
CONTEXT_FEATS = {"roce", "pe", "debt_eq", "promoter", "sector_rs", "sentiment"}
PAT_MAP = {
    "HIGH_TIGHT_FLAG": "pat_htf",
    "ASCENDING_TRIANGLE": "pat_tri",
    "DOUBLE_BOTTOM": "pat_db",
    "BULL_FLAG": "pat_flag",
    "INVERSE_HEAD_SHOULDERS": "pat_ihs",
    "HEAD_SHOULDERS_TOP_WARNING": "pat_bear",
}
PAT_FEATS = ["pat_htf", "pat_tri", "pat_db", "pat_flag", "pat_ihs", "pat_bear", "pat_any"]
PRICE_FEATS = [f for f in FEATURES if f not in CONTEXT_FEATS]
DTW_WINDOW_DAYS = 12
DEL_WINDOW_DAYS = 10


def _pattern_flags(tags, dates):
    parsed = []
    for dstr, pat, dirn in tags:
        try:
            d = dt.date.fromisoformat(str(dstr)[:10])
        except Exception:
            continue
        parsed.append((d, pat, dirn))
    out = {k: [] for k in PAT_FEATS}
    for x in dates:
        xd = x.date() if hasattr(x, "date") else x
        flags = dict.fromkeys(PAT_FEATS, 0.0)
        anyb = 0.0
        for d, pat, dirn in parsed:
            delta = (xd - d).days
            if 0 <= delta <= 6:
                col = PAT_MAP.get(pat)
                if col:
                    flags[col] = 1.0
                    if dirn == "BULLISH":
                        anyb = 1.0
        flags["pat_any"] = anyb
        for k in PAT_FEATS:
            out[k].append(flags[k])
    return out


def _dtw_map(conn, sym):
    try:
        rows = conn.execute(
            "SELECT date, similarity FROM template_scores WHERE symbol=?", (sym,)
        ).fetchall()
    except Exception:
        return {}
    m = {}
    for d, s in rows:
        key = str(d)[:10]
        if key not in m or s > m[key]:
            m[key] = s
    return m


def _dtw_series(tmap, dates):
    out = []
    for x in dates:
        xd = x.date() if hasattr(x, "date") else x
        val = 0.0
        for off in range(DTW_WINDOW_DAYS + 1):
            key = (xd - dt.timedelta(days=off)).isoformat()
            if key in tmap:
                val = tmap[key] / 100.0
                break
        out.append(val)
    return out


def _delivery_map(conn, sym):
    try:
        rows = conn.execute(
            "SELECT date, delivery_pct FROM delivery_daily WHERE symbol=? AND delivery_pct > 0",
            (sym,),
        ).fetchall()
    except Exception:
        return {}
    return {str(d)[:10]: p for d, p in rows}


def _delivery_series(pmap, dates):
    out = []
    for x in dates:
        xd = x.date() if hasattr(x, "date") else x
        val = 0.5
        for off in range(DEL_WINDOW_DAYS + 1):
            key = (xd - dt.timedelta(days=off)).isoformat()
            if key in pmap:
                val = max(0.0, min(1.0, (pmap[key] - 30.0) / 50.0))
                break
        out.append(val)
    return out


def _symbols(conn, limit=400):
    rows = U.band_universe(conn, limit)
    core = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1")]
    return sorted(set(rows) | set(core))


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


def sector_rs_map(conn):
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
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    # A label is known only when all 20 future bars exist.  Never turn an
    # immature tail row into a negative example.
    future_high = h.shift(-1)
    fut_max = (
        future_high.iloc[::-1].rolling(LABEL_HORIZON, min_periods=LABEL_HORIZON).max().iloc[::-1]
    )
    label_end = (
        df["date"].shift(-LABEL_HORIZON)
        if "date" in df
        else pd.Series(index=df.index, dtype="datetime64[ns]")
    )

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
    out["vcr"] = v.rolling(5).mean() / v.rolling(50).mean().replace(0, np.nan)
    out["ret_std20"] = c.pct_change().rolling(20).std()
    out["below52"] = 1.0 - (c / h.rolling(252).max())

    # v7: trend persistence features
    above200 = (c > e200).astype(float)
    above50 = (c > e50).astype(float)
    out["days_above_200_30"] = above200.rolling(30).mean()
    out["days_above_50_30"] = above50.rolling(30).mean()
    rel_e200 = (c / e200) - 1.0
    mean60 = rel_e200.rolling(60).mean()
    std60 = rel_e200.rolling(60).std().replace(0, np.nan)
    out["ema200_dist_z"] = (rel_e200 - mean60) / std60

    out["win"] = np.where(fut_max.notna(), ((fut_max / c - 1) >= 0.10).astype(float), np.nan)
    out["label_available_date"] = label_end
    return out


def _coerce_numeric(df):
    for col in FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_train_data(conn):
    fund = _fund_map(conn)
    sent = _sentiment_map(conn)
    srs = sector_rs_map(conn)
    frames = []
    for sym in _symbols(conn):
        rows = conn.execute(
            "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date",
            (sym,),
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
        try:
            tags = conn.execute(
                "SELECT date, pattern, direction FROM pattern_tags WHERE symbol=?", (sym,)
            ).fetchall()
        except Exception:
            tags = []
        fl = _pattern_flags(tags, feat["date"].tolist())
        for k in PAT_FEATS:
            feat[k] = fl[k]
        tmap = _dtw_map(conn, sym)
        feat["dtw_sim"] = _dtw_series(tmap, feat["date"].tolist())
        dmap = _delivery_map(conn, sym)
        feat["delivery_sim"] = _delivery_series(dmap, feat["date"].tolist())
        feat = feat.dropna(subset=PRICE_FEATS + ["win", "label_available_date"])
        frames.append(feat)
    if not frames:
        return None
    data = pd.concat(frames, ignore_index=True)
    for f in CONTEXT_FEATS:
        if f in data.columns:
            data[f] = pd.to_numeric(data[f], errors="coerce")
            med = data[f].median()
            data[f] = data[f].fillna(med if pd.notna(med) else 0.0)
    data = _coerce_numeric(data)
    return data.sort_values(["date", "label_available_date"]).reset_index(drop=True)


def _fit(tr, val, feats, medians=None):
    medians = medians or tr[feats].median().fillna(0.0).to_dict()
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
    model.fit(
        tr[feats].fillna(medians),
        tr["win"],
        eval_set=[(val[feats].fillna(medians), val["win"])],
        eval_metric="auc",
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    return model


def _eval(model, te, feats, medians=None):
    from sklearn.metrics import roc_auc_score

    proba = model.predict_proba(te[feats].fillna(medians or {}))[:, 1]
    auc = float(roc_auc_score(te["win"], proba))
    order = np.argsort(-proba)
    top = int(max(1, len(proba) * 0.10))
    top_rate = float(te["win"].iloc[order[:top]].mean())
    return auc, top_rate


def train():
    conn = db.get_conn()
    data = build_train_data(conn)
    conn.close()
    if data is None or data.empty:
        print("no training rows - check prices_daily")
        return None
    dates = np.sort(data["date"].unique())
    train_end = dates[max(0, int(len(dates) * 0.60) - 1)]
    val_end = dates[min(len(dates) - 1, int(len(dates) * 0.80))]
    tr = data[data["date"] <= train_end]
    val = data[(data["date"] > train_end) & (data["date"] < val_end)]
    te = data[data["date"] >= val_end]
    # Purge observations whose forward label is not available before the next
    # fold starts. Validation is for early stopping; test remains untouched.
    tr = tr[tr["label_available_date"] < val["date"].min()]
    val = val[val["label_available_date"] < te["date"].min()]
    if min(len(tr), len(val), len(te)) == 0:
        print("no non-overlapping train/validation/test rows")
        return None
    medians = tr[FEATURES].median().fillna(0.0).to_dict()
    model = _fit(tr, val, FEATURES, medians)
    auc, top_rate = _eval(model, te, FEATURES, medians)
    base = float(te["win"].mean())
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "version": MODEL_VERSION,
            "metadata": {
                "label": LABEL_DESCRIPTION,
                "horizon_sessions": LABEL_HORIZON,
                "context_features_excluded": sorted(CONTEXT_FEATS),
                "imputation_medians": medians,
                "split": "global_date_purged",
                "validation": "early_stopping_only",
                "test": "final_holdout",
            },
        },
        MODEL_PATH,
    )
    metrics = {
        "rows": int(len(data)),
        "winners": round(base, 4),
        "auc": round(auc, 4),
        "base_win": round(base, 4),
        "top10_win": round(top_rate, 4),
        "n_features": len(FEATURES),
        "note": "retrain v8 PIT-safe; label is an uncalibrated +10%/20-session event",
    }
    print(f"rows {len(data)} | winners {base:.1%}")
    print(f"test AUC {auc:.3f} | base win {base:.1%} | top-10% win {top_rate:.1%}")
    print(f"features: {len(FEATURES)} (incl. trend persistence)")
    print(f"model saved to {MODEL_PATH}")
    try:
        import model_report

        model_report.record(metrics)
    except Exception as e:
        print(f"[META] model_run record skipped: {e}")
    reload_model()
    return metrics


def lift_test():
    conn = db.get_conn()
    data = build_train_data(conn)
    conn.close()
    if data is None or data.empty:
        return {"error": "no training data"}
    dates = np.sort(data["date"].unique())
    train_end = dates[max(0, int(len(dates) * 0.60) - 1)]
    val_end = dates[min(len(dates) - 1, int(len(dates) * 0.80))]
    tr = data[data["date"] <= train_end]
    val = data[(data["date"] > train_end) & (data["date"] < val_end)]
    te = data[data["date"] >= val_end]
    tr = tr[tr["label_available_date"] < val["date"].min()]
    val = val[val["label_available_date"] < te["date"].min()]
    if min(len(tr), len(val), len(te)) == 0:
        return {"error": "no non-overlapping split"}
    medians = tr[FEATURES].median().fillna(0.0).to_dict()
    results = {}
    for name, feats in [("full", FEATURES), ("price_only", PRICE_FEATS)]:
        model = _fit(tr, val, feats, {k: medians.get(k, 0.0) for k in feats})
        auc, top_rate = _eval(model, te, feats, {k: medians.get(k, 0.0) for k in feats})
        results[name] = {"auc": round(auc, 4), "top10_win": round(top_rate, 4)}
        print(f"   {name}: AUC {auc:.4f} | top10 {top_rate:.1%}")
    delta_auc = round(results["full"]["auc"] - results["price_only"]["auc"], 4)
    delta_top = round(results["full"]["top10_win"] - results["price_only"]["top10_win"], 4)
    metrics = {
        "rows": int(len(data)),
        "auc": results["full"]["auc"],
        "base_win": round(float(te["win"].mean()), 4),
        "top10_win": results["full"]["top10_win"],
        "n_features": len(FEATURES),
        "price_only_auc": results["price_only"]["auc"],
        "delta_auc": delta_auc,
        "delta_top10": delta_top,
        "note": (
            f"C3 lift: full AUC {results['full']['auc']} "
            f"vs price-only {results['price_only']['auc']} "
            f"(d {delta_auc:+.4f}); "
            f"top10 d {delta_top:+.4f}"
        ),
    }
    print(json.dumps(metrics, indent=1))
    try:
        import model_report

        model_report.record(metrics, note="c3_lift")
    except Exception as e:
        print(f"[META] lift record skipped: {e}")
    return metrics


def _attach_extra_feats(feat, tags, tmap, dmap):
    dates = feat.index.tolist()
    fl = _pattern_flags(tags, dates)
    for k in PAT_FEATS:
        feat[k] = fl[k]
    feat["dtw_sim"] = _dtw_series(tmap, dates)
    feat["delivery_sim"] = _delivery_series(dmap, dates)
    return feat


def score_symbol(sym, use_yahoo=True):
    model = get_model()
    if model is None:
        return None
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date",
        (sym,),
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

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    conn2 = db.get_conn()
    fund = _fund_map(conn2)
    sent = _sentiment_map(conn2)
    srs = sector_rs_map(conn2)
    try:
        tags = conn2.execute(
            "SELECT date, pattern, direction FROM pattern_tags WHERE symbol=?", (sym,)
        ).fetchall()
    except Exception:
        tags = []
    tmap = _dtw_map(conn2, sym)
    dmap = _delivery_map(conn2, sym)
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
    if feat.empty:
        return None

    feat = _attach_extra_feats(feat, tags, tmap, dmap)
    feat = _coerce_numeric(feat)
    medians = (
        model_bundle_metadata(model).get("imputation_medians", {}) if model is not None else {}
    )
    for col in FEATURES:
        if col in feat.columns:
            feat[col] = feat[col].fillna(medians.get(col, 0.0))
    feat = feat.dropna(subset=PRICE_FEATS)
    if feat.empty:
        return None
    feat = feat.tail(1)
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
    elif cmd == "lift":
        lift_test()
    else:
        print(score_symbol(cmd))

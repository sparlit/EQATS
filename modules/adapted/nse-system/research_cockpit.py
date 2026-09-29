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
Research Cockpit — historical behaviour of setups similar to today's.

Entry points:
  analyze_symbol(sym)          — full per-symbol analysis (cached 7d)
  analyze_universe(limit)      — today's setups + their cached stats
  warm_cache()                 — compute + cache stats for today's symbols
  sector_aggregate()           — pool setups across symbols, by sector
  signature_match(features, k) — k nearest historical setups globally

v4 (2026-09-12): adds signature matching via setup_pool.
"""
import contextlib
import datetime as dt
import json
import sys
import time

import db
import numpy as np
import pandas as pd
from setup import SetupDetector

CACHE_VERSION = 4
HISTORY_DAYS = 5 * 365
STEP = 5
MIN_BARS = 280
HOLD_BARS = 30
CACHE_TTL_DAYS = 7

# Feature vector for similarity matching. Order matters — don't reorder
# without updating both _to_vector and the pool table.
SIM_FEATURES = [
    "impulse_pct_60d",
    "days_since_impulse_peak",
    "consolidation_range_pct",
    "vol_ratio_20",
    "atr_pct",
    "mom_20d",
    "distance_from_52w_high",
    "rsi",
]


# ============================================================
# Cache
# ============================================================
def _ensure_cache(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS research_cache(
        symbol TEXT PRIMARY KEY,
        computed_at TEXT,
        payload TEXT
    )
    """)


def _get_cached(conn, sym, max_age_days=CACHE_TTL_DAYS):
    try:
        row = conn.execute("SELECT computed_at, payload FROM research_cache WHERE symbol=?", (sym,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        d = dt.date.fromisoformat(str(row[0])[:10])
        if (dt.date.today() - d).days > max_age_days:
            return None
        payload = json.loads(row[1])
        if payload.get("cache_version") != CACHE_VERSION:
            return None
        return payload
    except Exception:
        return None


def _put_cache(conn, sym, payload):
    _ensure_cache(conn)
    payload["cache_version"] = CACHE_VERSION
    conn.execute(
        "INSERT OR REPLACE INTO research_cache VALUES (?,?,?)",
        (sym, dt.date.today().isoformat(), json.dumps(payload, default=str)),
    )


def _clear_cache(conn, sym=None):
    _ensure_cache(conn)
    if sym:
        conn.execute("DELETE FROM research_cache WHERE symbol=?", (sym,))
    else:
        conn.execute("DELETE FROM research_cache")
    conn.commit()


# ============================================================
# Mother-bar classification (ID47)
# ============================================================
def _classify_mother_bar(df, idx):
    try:
        o = df["Open"].values.astype(float)
        h = df["High"].values.astype(float)
        l = df["Low"].values.astype(float)
        c = df["Close"].values.astype(float)
    except Exception:
        return None
    if idx < 1 or idx >= len(c):
        return None
    body = abs(c[idx] - o[idx])
    rng = h[idx] - l[idx]
    if rng <= 0:
        return None
    upper_wick = h[idx] - max(o[idx], c[idx])
    lower_wick = min(o[idx], c[idx]) - l[idx]
    body_ratio = body / rng
    upper_ratio = upper_wick / rng
    lower_ratio = lower_wick / rng
    close_pos = (c[idx] - l[idx]) / rng
    is_bull = c[idx] >= o[idx]

    if h[idx] < h[idx - 1] and l[idx] > l[idx - 1]:
        mtype = "inside"
    elif body_ratio < 0.35 and lower_ratio > 0.55 and upper_ratio < 0.20:
        mtype = "hammer"
    elif body_ratio < 0.35 and upper_ratio > 0.55 and lower_ratio < 0.20:
        mtype = "inv_hammer"
    elif body_ratio < 0.20:
        mtype = "doji"
    elif body_ratio > 0.70:
        mtype = "wide"
    else:
        mtype = "normal"

    atr = None
    if idx >= 14:
        trs = []
        for i in range(idx - 13, idx + 1):
            trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        atr = float(np.mean(trs))
    range_atr = (rng / atr) if (atr and atr > 0) else None

    return {
        "mtype": mtype,
        "body_ratio": round(body_ratio, 3),
        "upper_wick_pct": round(upper_ratio, 3),
        "lower_wick_pct": round(lower_ratio, 3),
        "close_position": round(close_pos, 3),
        "range_atr": round(range_atr, 2) if range_atr else None,
        "is_bull": bool(is_bull),
    }


def _candle_stats(setups):
    by_type = {}
    for s in setups:
        mt = s.get("mother_type")
        if not mt:
            continue
        by_type.setdefault(mt, []).append(s)
    out = {}
    for mtype, arr in by_type.items():
        triggered = [x for x in arr if x.get("triggered")]
        nt = len(triggered)

        def _hr(level):
            if not nt:
                return None
            k = f"hit_{level}r"
            return round(sum(1 for x in triggered if x.get(k)) / nt, 3)

        mfes = [x["mfe_r"] for x in triggered if x.get("mfe_r") is not None]
        maes = [x["mae_r"] for x in triggered if x.get("mae_r") is not None]
        out[mtype] = {
            "n_setups": len(arr),
            "n_triggered": nt,
            "p_1r": _hr(1),
            "p_2r": _hr(2),
            "p_3r": _hr(3),
            "median_mfe_r": (round(float(np.median(mfes)), 2) if mfes else None),
            "median_mae_r": (round(float(np.median(maes)), 2) if maes else None),
        }
    return out


# ============================================================
# Signature matching (ID46)
# ============================================================
def _to_vector(row):
    """Extract feature vector from a dict-like row (pool row or
    live feature dict). Returns (vec, valid_mask)."""
    v = []
    m = []
    for f in SIM_FEATURES:
        val = row.get(f)
        if val is None:
            v.append(0.0)
            m.append(False)
        else:
            try:
                v.append(float(val))
                m.append(True)
            except (TypeError, ValueError):
                v.append(0.0)
                m.append(False)
    return np.array(v, dtype=float), np.array(m, dtype=bool)


def signature_match(live_features, k=30, sector_filter=None):
    """
    Find the k historical setups nearest to `live_features` in the
    setup_pool. Distance = L1 on z-scored features.
    Returns dict with n_matches + pooled stats.
    """
    conn = db.get_conn()
    try:
        conn.execute("SELECT 1 FROM setup_pool LIMIT 1")
    except Exception:
        conn.close()
        return {"error": "setup_pool not built. Run build_setup_pool.py"}

    q = "SELECT * FROM setup_pool"
    params = []
    if sector_filter:
        q += " WHERE sector=?"
        params.append(sector_filter)
    rows = conn.execute(q, params).fetchall()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(setup_pool)")]
    conn.close()

    if not rows:
        return {"error": "setup_pool is empty"}

    # Build matrix
    pool_vecs = []
    pool_rows = []
    for r in rows:
        d = dict(zip(cols, r, strict=False))
        vec, _mask = _to_vector(d)
        pool_vecs.append(vec)
        pool_rows.append(d)
    X = np.vstack(pool_vecs)  # (n_pool, n_features)

    # Z-score per feature (mean, std over pool, ignoring NaN)
    mean = np.nanmean(X, axis=0)
    std = np.nanstd(X, axis=0)
    std[std == 0] = 1.0
    Xz = (X - mean) / std

    # Live vector
    lv, lmask = _to_vector(live_features)
    lvz = (lv - mean) / std

    # Distance: L1; only penalize features present in the live setup.
    # (Ignoring missing live features keeps distance meaningful.)
    diffs = np.abs(Xz - lvz)
    # Zero out diffs for missing live features
    diffs[:, ~lmask] = 0.0
    dists = diffs.sum(axis=1)

    order = np.argsort(dists)[:k]
    matches = [pool_rows[i] for i in order]

    # Pooled stats on matches
    n = len(matches)
    sum(1 for m in matches if m.get("hit_1r") is not None or m.get("outcome") == "LOSS")

    # Compute per-level hit rates (use hit_Nr columns)
    def _hr(col):
        arr = [m.get(col) for m in matches if m.get(col) is not None]
        if not arr:
            return None
        return round(sum(int(x) for x in arr) / len(arr), 3)

    mfes = [m.get("mfe_r") for m in matches if m.get("mfe_r") is not None]
    maes = [m.get("mae_r") for m in matches if m.get("mae_r") is not None]
    outcomes = {}
    for m in matches:
        o = m.get("outcome") or "?"
        outcomes[o] = outcomes.get(o, 0) + 1

    return {
        "n_pool": len(rows),
        "k": k,
        "sector_filter": sector_filter,
        "n_matches": n,
        "match_sectors": _sector_breakdown(matches),
        "p_1r": _hr("hit_1r"),
        "p_2r": _hr("hit_2r"),
        "p_3r": _hr("hit_3r"),
        "median_mfe_r": (round(float(np.median(mfes)), 2) if mfes else None),
        "median_mae_r": (round(float(np.median(maes)), 2) if maes else None),
        "p95_mfe_r": (round(float(np.percentile(mfes, 95)), 2) if mfes else None),
        "p5_mae_r": (round(float(np.percentile(maes, 5)), 2) if maes else None),
        "outcome_mix": outcomes,
        "sample_matches": [
            {
                "symbol": m["symbol"],
                "signal_date": m["signal_date"],
                "outcome": m.get("outcome"),
                "mfe_r": m.get("mfe_r"),
                "mae_r": m.get("mae_r"),
            }
            for m in matches[:15]
        ],
    }


def _sector_breakdown(matches):
    out = {}
    for m in matches:
        sec = m.get("sector") or "Unknown"
        out[sec] = out.get(sec, 0) + 1
    return out


# ============================================================
# Core simulation
# ============================================================
def _simulate_forward(df, signal_i, trigger, stop):
    n = len(df)
    h = df["High"].values
    l = df["Low"].values
    risk = trigger - stop
    if risk <= 0:
        return None
    trig_bar = None
    for j in range(signal_i + 1, min(signal_i + 4, n)):
        if h[j] >= trigger:
            trig_bar = j
            break
    if trig_bar is None:
        return {
            "triggered": False,
            "outcome": "EXPIRED",
            "mfe_r": 0.0,
            "mae_r": 0.0,
            "hit_1r": False,
            "hit_2r": False,
            "hit_3r": False,
            "hit_4r": False,
            "bars_to_1r": None,
            "bars_to_2r": None,
            "bars_to_3r": None,
            "bars_to_4r": None,
        }
    end_bar = min(trig_bar + HOLD_BARS, n)
    mfe = 0.0
    mae = 0.0
    hit_1r = hit_2r = hit_3r = hit_4r = False
    b_1r = b_2r = b_3r = b_4r = None
    outcome = "TIMEOUT"
    for k in range(trig_bar, end_bar):
        up_r = (h[k] - trigger) / risk
        dn_r = (l[k] - trigger) / risk
        mfe = max(mfe, up_r)
        mae = min(mae, dn_r)
        bars_since = k - trig_bar
        if not hit_1r and up_r >= 1.0:
            hit_1r = True
            b_1r = bars_since
        if not hit_2r and up_r >= 2.0:
            hit_2r = True
            b_2r = bars_since
        if not hit_3r and up_r >= 3.0:
            hit_3r = True
            b_3r = bars_since
        if not hit_4r and up_r >= 4.0:
            hit_4r = True
            b_4r = bars_since
        if l[k] <= stop:
            outcome = "LOSS"
            break
    if outcome != "LOSS" and not hit_1r:
        outcome = "TIMEOUT"
    return {
        "triggered": True,
        "outcome": outcome,
        "mfe_r": round(float(mfe), 2),
        "mae_r": round(float(mae), 2),
        "hit_1r": hit_1r,
        "hit_2r": hit_2r,
        "hit_3r": hit_3r,
        "hit_4r": hit_4r,
        "bars_to_1r": b_1r,
        "bars_to_2r": b_2r,
        "bars_to_3r": b_3r,
        "bars_to_4r": b_4r,
    }


def _load_df(conn, sym, years=5):
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
    ).fetchall()
    if not rows or len(rows) < MIN_BARS:
        return None
    df = pd.DataFrame(list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"]).set_index("date")
    df.index = pd.to_datetime(df.index)
    cutoff = df.index[-1] - pd.Timedelta(days=365 * years)
    return df[df.index >= cutoff]


def _features_at(df, i):
    """Reuse the pool feature extractor so live and pool vectors
    are computed identically."""
    if i < 60:
        return None
    c = df["Close"].values.astype(float)[: i + 1]
    h = df["High"].values.astype(float)[: i + 1]
    l = df["Low"].values.astype(float)[: i + 1]
    v = df["Volume"].values.astype(float)[: i + 1]
    close = float(c[-1])
    high52 = float(np.max(h[-252:])) if len(h) >= 252 else float(np.max(h))
    lookback = 60
    window = min(lookback, len(c))
    h_seg = h[-window:]
    peak_local = int(np.argmax(h_seg))
    peak_idx = len(c) - window + peak_local
    peak_high = float(h[peak_idx])
    low_start = max(0, peak_idx - 40)
    low_before = float(np.min(l[low_start : peak_idx + 1]))
    impulse_pct = (peak_high - low_before) / low_before if low_before > 0 else None
    days_since = len(c) - 1 - peak_idx
    cons_range = None
    if days_since >= 1:
        cons_high = float(np.max(h[peak_idx + 1 :]))
        cons_low = float(np.min(l[peak_idx + 1 :]))
        if peak_high > 0:
            cons_range = (cons_high - cons_low) / peak_high
    avg_vol_20 = float(np.mean(v[-20:])) if len(v) >= 20 else None
    vol_ratio = (float(v[-1]) / avg_vol_20) if avg_vol_20 else None
    atr_pct = None
    if len(c) >= 15:
        trs = []
        for k in range(1, len(c)):
            trs.append(max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])))
        atr = float(np.mean(trs[-14:]))
        atr_pct = atr / close if close > 0 else None
    mom_20d = (c[-1] / c[-21] - 1) if len(c) >= 21 else None
    mom_60d = (c[-1] / c[-61] - 1) if len(c) >= 61 else None
    dist_high = (high52 - close) / high52 if high52 > 0 else None
    # RSI
    rsi = None
    if len(c) >= 15:
        gains = 0.0
        losses = 0.0
        for k in range(len(c) - 14, len(c)):
            ch = c[k] - c[k - 1]
            if ch > 0:
                gains += ch
            else:
                losses -= ch
        rsi = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    return {
        "close": close,
        "impulse_pct_60d": impulse_pct,
        "days_since_impulse_peak": days_since,
        "consolidation_range_pct": cons_range,
        "vol_ratio_20": vol_ratio,
        "atr_pct": atr_pct,
        "mom_20d": mom_20d,
        "mom_60d": mom_60d,
        "distance_from_52w_high": dist_high,
        "rsi": rsi,
    }


def _historical_setups(df):
    setups = []
    for i in range(MIN_BARS, len(df) - 1, STEP):
        slice_df = df.iloc[: i + 1]
        st = SetupDetector.detect(slice_df, "X")
        if not st.triggered:
            continue
        sim = _simulate_forward(df, i, st.entry_price, st.stop_loss)
        if sim is None:
            continue
        candle = _classify_mother_bar(df, i)
        feats = _features_at(df, i) or {}
        setups.append(
            {
                "signal_date": str(slice_df.index[-1].date()),
                "entry": st.entry_price,
                "stop": st.stop_loss,
                "risk_pct": round((st.entry_price - st.stop_loss) / st.entry_price * 100, 2),
                "pullback_pct": round(st.pullback_depth * 100, 1),
                "pullback_days": int(st.pullback_days),
                "impulse_pct": round(st.impulse_pct * 100, 1),
                "ema_zone": st.ema_proximity,
                "shape_score": int(st.shape_score),
                "mother_type": candle["mtype"] if candle else None,
                "mother_body_ratio": candle["body_ratio"] if candle else None,
                "mother_range_atr": candle["range_atr"] if candle else None,
                "mother_close_pos": candle["close_position"] if candle else None,
                "mother_is_bull": candle["is_bull"] if candle else None,
                # Feature vector at signal (used for signature match fallback)
                "feat_impulse_pct_60d": feats.get("impulse_pct_60d"),
                "feat_days_since_impulse_peak": feats.get("days_since_impulse_peak"),
                "feat_consolidation_range_pct": feats.get("consolidation_range_pct"),
                "feat_vol_ratio_20": feats.get("vol_ratio_20"),
                "feat_atr_pct": feats.get("atr_pct"),
                "feat_mom_20d": feats.get("mom_20d"),
                "feat_distance_from_52w_high": feats.get("distance_from_52w_high"),
                "feat_rsi": feats.get("rsi"),
                **sim,
            }
        )
    return setups


def _aggregate(setups):
    if not setups:
        return {
            "n_setups": 0,
            "n_triggered": 0,
            "p_trigger": None,
            "p_1r_given_trigger": None,
            "p_2r_given_trigger": None,
            "p_3r_given_trigger": None,
            "p_4r_given_trigger": None,
            "median_bars_to_1r": None,
            "median_bars_to_2r": None,
            "median_bars_to_3r": None,
            "median_bars_to_4r": None,
            "median_mfe_r": None,
            "median_mae_r": None,
            "p5_mfe_r": None,
            "p95_mfe_r": None,
            "p5_mae_r": None,
            "p95_mae_r": None,
            "outcome_mix": {},
        }
    n = len(setups)
    triggered = [s for s in setups if s["triggered"]]
    nt = len(triggered)

    def _hitrate(level):
        if not nt:
            return None
        key = f"hit_{level}r"
        return round(sum(1 for s in triggered if s[key]) / nt, 3)

    def _median_bars(level):
        key = f"bars_to_{level}r"
        arr = [s[key] for s in triggered if s[key] is not None]
        return round(float(np.median(arr)), 1) if arr else None

    mfes = [s["mfe_r"] for s in triggered]
    maes = [s["mae_r"] for s in triggered]
    outcome_mix = {}
    for s in setups:
        outcome_mix[s["outcome"]] = outcome_mix.get(s["outcome"], 0) + 1

    def _pct(arr, q):
        return round(float(np.percentile(arr, q)), 2) if arr else None

    return {
        "n_setups": n,
        "n_triggered": nt,
        "p_trigger": round(nt / n, 3) if n else None,
        "p_1r_given_trigger": _hitrate(1),
        "p_2r_given_trigger": _hitrate(2),
        "p_3r_given_trigger": _hitrate(3),
        "p_4r_given_trigger": _hitrate(4),
        "median_bars_to_1r": _median_bars(1),
        "median_bars_to_2r": _median_bars(2),
        "median_bars_to_3r": _median_bars(3),
        "median_bars_to_4r": _median_bars(4),
        "median_mfe_r": _pct(mfes, 50),
        "median_mae_r": _pct(maes, 50),
        "p5_mfe_r": _pct(mfes, 5),
        "p95_mfe_r": _pct(mfes, 95),
        "p5_mae_r": _pct(maes, 5),
        "p95_mae_r": _pct(maes, 95),
        "outcome_mix": outcome_mix,
    }


def analyze_symbol(sym, use_cache=True, include_signature=True):
    sym = sym.upper()
    conn = db.get_conn()

    if use_cache:
        cached = _get_cached(conn, sym)
        if cached is not None:
            conn.close()
            return cached

    df = _load_df(conn, sym, years=5)
    if df is None:
        conn.close()
        return {"symbol": sym, "error": "insufficient history"}

    current_setup = None
    live_features = None
    st = SetupDetector.detect(df, sym)
    if st.triggered:
        candle = _classify_mother_bar(df, len(df) - 1)
        feats = _features_at(df, len(df) - 1) or {}
        live_features = feats
        current_setup = {
            "signal_date": st.signal_date,
            "entry": st.entry_price,
            "stop": st.stop_loss,
            "target_3r": round(st.entry_price + 3.0 * (st.entry_price - st.stop_loss), 2),
            "risk_pct": round((st.entry_price - st.stop_loss) / st.entry_price * 100, 2),
            "pullback_pct": round(st.pullback_depth * 100, 1),
            "pullback_days": int(st.pullback_days),
            "impulse_pct": round(st.impulse_pct * 100, 1),
            "ema_zone": st.ema_proximity,
            "shape_score": int(st.shape_score),
            "mother_type": candle["mtype"] if candle else None,
            "mother_body_ratio": candle["body_ratio"] if candle else None,
            "mother_range_atr": candle["range_atr"] if candle else None,
        }

    latest_close = float(df["Close"].iloc[-1])
    high_52w = float(df["High"].tail(252).max())
    low_52w = float(df["Low"].tail(252).min())

    setups = _historical_setups(df)
    agg = _aggregate(setups)
    candle_stats = _candle_stats(setups)
    recent = sorted(setups, key=lambda s: s["signal_date"], reverse=True)[:5]

    # Signature matching (only if live setup + pool exists)
    sig_match = None
    if include_signature and live_features:
        try:
            sig_match = signature_match(live_features, k=30)
        except Exception as e:
            sig_match = {"error": str(e)}

    sector = None
    row = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()
    if row:
        sector = row[0]

    result = {
        "symbol": sym,
        "sector": sector,
        "as_of": str(df.index[-1].date()),
        "latest_close": latest_close,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "pct_from_52w_high": round((high_52w - latest_close) / high_52w * 100, 1),
        "pct_from_52w_low": round((latest_close - low_52w) / low_52w * 100, 1),
        "current_setup": current_setup,
        "historical": agg,
        "candle_stats": candle_stats,
        "signature_match": sig_match,
        "recent_setups": recent,
        "raw_setups": setups,
        "history_bars_tested": len(df),
        "history_years": 5,
        "step": STEP,
    }

    if use_cache:
        _put_cache(conn, sym, result)
        conn.commit()

    conn.close()
    return result


# ============================================================
# Universe / sector (unchanged from v3)
# ============================================================
def _today_symbols(conn, trend_limit=50):
    today = dt.date.today().isoformat()
    rows = conn.execute("SELECT DISTINCT symbol, mode FROM swing_signals WHERE signal_date=?", (today,)).fetchall()
    symbols = {r[0]: r[1] for r in rows}
    try:
        trows = conn.execute(
            "SELECT symbol FROM trend_candidates WHERE date=? ORDER BY score DESC LIMIT ?", (today, trend_limit)
        ).fetchall()
        for r in trows:
            symbols.setdefault(r[0], "TREND")
    except Exception:
        pass
    return symbols


def analyze_universe(today_only=True, max_symbols=200, compute_missing=False):
    conn = db.get_conn()
    today = dt.date.today().isoformat()
    symbols = _today_symbols(conn)
    out = []
    for sym, src in list(symbols.items())[:max_symbols]:
        cached = _get_cached(conn, sym)
        if cached is None:
            cached = analyze_symbol(sym, use_cache=True) if compute_missing else {"symbol": sym, "error": "not cached"}
        h = cached.get("historical", {})
        out.append(
            {
                "symbol": sym,
                "source": src,
                "sector": cached.get("sector"),
                "latest_close": cached.get("latest_close"),
                "pct_from_52w_high": cached.get("pct_from_52w_high"),
                "pct_from_52w_low": cached.get("pct_from_52w_low"),
                "n_setups": h.get("n_setups"),
                "n_triggered": h.get("n_triggered"),
                "p_trigger": h.get("p_trigger"),
                "p_1r": h.get("p_1r_given_trigger"),
                "p_2r": h.get("p_2r_given_trigger"),
                "p_3r": h.get("p_3r_given_trigger"),
                "p_4r": h.get("p_4r_given_trigger"),
                "median_mfe_r": h.get("median_mfe_r"),
                "median_mae_r": h.get("median_mae_r"),
                "p95_mfe_r": h.get("p95_mfe_r"),
                "p5_mae_r": h.get("p5_mae_r"),
                "current_setup": cached.get("current_setup"),
            }
        )
    conn.close()
    return {"date": today, "n_setups": len(out), "rows": out}


def sector_aggregate(max_symbols=200):
    conn = db.get_conn()
    today = dt.date.today().isoformat()
    symbols = _today_symbols(conn)
    buckets = {}
    missing = []
    for sym in list(symbols.keys())[:max_symbols]:
        cached = _get_cached(conn, sym)
        if cached is None or "error" in cached:
            missing.append(sym)
            continue
        sector = cached.get("sector") or "Unknown"
        buckets.setdefault(sector, []).append(cached)
    conn.close()
    out = []
    for sector, cached_list in buckets.items():
        pooled_setups = []
        for c in cached_list:
            pooled_setups.extend(c.get("raw_setups", []))
        agg = _aggregate(pooled_setups)
        candle_stats = _candle_stats(pooled_setups)
        out.append(
            {
                "sector": sector,
                "n_symbols": len(cached_list),
                "symbols": [c.get("symbol") for c in cached_list],
                "candle_stats": candle_stats,
                **agg,
            }
        )
    out.sort(key=lambda r: -(r["n_setups"] or 0))
    return {
        "date": today,
        "n_sectors": len(out),
        "n_symbols_cached": sum(len(v) for v in buckets.values()),
        "n_symbols_missing": len(missing),
        "missing": missing[:30],
        "sectors": out,
    }


def warm_cache(max_symbols=200, force=False):
    conn = db.get_conn()
    _ensure_cache(conn)
    symbols = _today_symbols(conn, trend_limit=50)
    todo = []
    for sym in list(symbols.keys())[:max_symbols]:
        if not force and _get_cached(conn, sym) is not None:
            continue
        todo.append(sym)
    conn.close()
    if not todo:
        print(f"[WARM] all {len(symbols)} symbols already cached")
        return 0
    print(f"[WARM] computing {len(todo)} of {len(symbols)} symbols (force={force})")
    t0 = time.time()
    done = 0
    failed = 0
    for i, sym in enumerate(todo, 1):
        try:
            r = analyze_symbol(sym, use_cache=not force)
            if "error" in r:
                failed += 1
                print(f"  [{i}/{len(todo)}] {sym}: {r['error']}")
            else:
                done += 1
                if i % 5 == 0 or i == len(todo):
                    elapsed = time.time() - t0
                    rate = i / elapsed if elapsed else 0
                    eta = (len(todo) - i) / rate if rate else 0
                    print(f"  [{i}/{len(todo)}] {sym} ok ({elapsed:.0f}s, ETA {eta:.0f}s)")
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(todo)}] {sym}: exception {e}")
    print(f"[WARM] done: {done} computed, {failed} failed, {time.time() - t0:.0f}s total")
    return done


def clear_cache(sym=None):
    conn = db.get_conn()
    _clear_cache(conn, sym)
    conn.close()


# ============================================================
# CLI
# ============================================================
def _print_symbol(result):
    print("=" * 70)
    print(f"RESEARCH COCKPIT — {result['symbol']}")
    print("=" * 70)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return
    print(f"  Sector: {result['sector']}")
    print(f"  As of: {result['as_of']}  close: {result['latest_close']}")
    print(f"  {result['pct_from_52w_high']}% from 52w high  |  {result['pct_from_52w_low']}% from 52w low")
    print()
    if result["current_setup"]:
        cs = result["current_setup"]
        print("  CURRENT SETUP:")
        print(f"    signal {cs['signal_date']}  entry {cs['entry']}  stop {cs['stop']}  target3R {cs['target_3r']}")
        if cs.get("mother_type"):
            print(f"    mother bar: {cs['mother_type']}")
    else:
        print("  CURRENT SETUP: none triggered today")
    print()
    h = result["historical"]
    print(f"  HISTORICAL ({h['n_setups']} setups over 5y):")
    print(f"    triggered: {h['n_triggered']} (P={h['p_trigger']})")
    print(
        f"    P(+1R): {h['p_1r_given_trigger']}  P(+2R): {h['p_2r_given_trigger']}  P(+3R): {h['p_3r_given_trigger']}"
    )
    print(f"    MFE R: p5={h['p5_mfe_r']}  p50={h['median_mfe_r']}  p95={h['p95_mfe_r']}")
    print(f"    MAE R: p5={h['p5_mae_r']}  p50={h['median_mae_r']}  p95={h['p95_mae_r']}")
    print()
    cs = result.get("candle_stats") or {}
    if cs:
        print("  CANDLE BEHAVIOUR:")
        for mtype, s in sorted(cs.items(), key=lambda x: -x[1]["n_setups"]):
            print(
                f"    {mtype:<14} n={s['n_setups']:<3} "
                f"trig={s['n_triggered']:<3} "
                f"P1R={s['p_1r']}  P2R={s['p_2r']}  "
                f"P3R={s['p_3r']}"
            )
    print()
    sm = result.get("signature_match")
    if sm and not sm.get("error"):
        print(f"  SIGNATURE MATCH (nearest {sm['k']} of {sm['n_pool']} pool setups):")
        print(f"    P(+1R): {sm['p_1r']}  P(+2R): {sm['p_2r']}  P(+3R): {sm['p_3r']}")
        print(f"    MFE R: median {sm['median_mfe_r']}  p95 {sm['p95_mfe_r']}")
        print(f"    MAE R: median {sm['median_mae_r']}  p5 {sm['p5_mae_r']}")
        print(f"    outcome mix: {sm['outcome_mix']}")
        print(f"    top sectors: {sm['match_sectors']}")
    elif sm and sm.get("error"):
        print(f"  SIGNATURE MATCH: {sm['error']}")


if __name__ == "__main__":
    argv = sys.argv[1:]

    if "--clear-cache" in argv:
        clear_cache()
        print("cache cleared")
        sys.exit(0)

    if "--warm" in argv:
        force = "--force" in argv
        limit = 200
        for a in argv:
            if a.startswith("--limit="):
                with contextlib.suppress(Exception):
                    limit = int(a.split("=", 1)[1])
        warm_cache(max_symbols=limit, force=force)
        sys.exit(0)

    if "--sector" in argv or "-s" in argv:
        want_json = "--json" in argv
        out = sector_aggregate()
        if want_json:
            print(json.dumps(out, indent=2, default=str))
        else:
            pass  # minimal CLI; sector printed via _print_sector in earlier version
        sys.exit(0)

    want_json = "--json" in argv
    want_refresh = "--refresh" in argv
    positional = [a for a in argv if not a.startswith("--") and not a.startswith("-")]
    sym = positional[0] if positional else "RELIANCE"
    result = analyze_symbol(sym, use_cache=not want_refresh)
    if want_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_symbol(result)

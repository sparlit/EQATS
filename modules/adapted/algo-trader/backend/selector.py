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
Strategy selector — the core algorithm.

First-principles frame: "which strategy should run today?" is NOT a bandit
problem. A bandit needs exploration because it only observes the pulled arm's
reward. Here we can REPLAY every arm on every historical day and observe all
counterfactual outcomes. That reduces strategy selection to supervised
conditional expectancy:

    1. For every past (symbol, day), simulate each arm → net R-multiple.
       Store (day-state features, arm, R) in SQLite.  [replay + record]
    2. On a new day at 9:45, find the K most similar past day-states
       (z-scored Euclidean distance, pooled across symbols) and compute each
       arm's distance-weighted mean R over them.       [choose]
    3. Pick the best arm only if its conditional expectancy clears a margin
       above zero. Otherwise NO_TRADE — capital preservation is an arm too,
       and it's free.

Walk-forward by construction: choose(date=D) only reads rows with date < D.
"""

import json
import math
import os
import sqlite3
from zoneinfo import ZoneInfo

import pandas as pd
from daystate import FEATURES
from strategies import STRATEGY_REGISTRY

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache.db")

ARMS = list(STRATEGY_REGISTRY.keys())  # ["ORB", "VWAP_FADE", "GAP_FADE"]
NO_TRADE = "NO_TRADE"
FEATURE_VERSION = 3  # v3: cross-sectional in-play rank features

# Round-trip cost as % of notional (₹40×2 brokerage on a ~₹1.25L MIS position
# + STT + txn + GST + stamp + 8bps slippage). Matches backtest._trade_costs
# at the default sizing scale.
_COST_PCT = 0.18

# Minimum stop width as % of entry. Below this the fixed costs exceed ~0.5R
# and no win rate can save the trade — economically untradeable, skip.
_MIN_RISK_PCT = 0.30

_K_NEIGHBORS = 150  # neighbors used for conditional expectancy (pooled cross-symbol table)
_MIN_HISTORY = 90  # min (symbol,day) states before we trust the table
_EDGE_THRESHOLD = 0.02  # best arm must clear positive net expectancy, else NO_TRADE
_DECAY_HALF_LIFE_DAYS = 120  # time-decay half-life for neighbor weights (non-stationarity)
_SHRINK_N0 = 8  # shrinkage prior strength: estimates from few trades shrink to 0
_LOSS_PROB_LIMIT = 0.70  # no-trade guardrail for extreme modeled loss risk
_SCORE_FLOOR = -999.0  # score ranks/sizes; expectancy is the hard profit gate
_DOWNSIDE_PENALTY = 0.35  # expected downside penalty weight; profit remains primary
_TAIL_PENALTY = 0.20  # tail-loss penalty for capital preservation
_LOSS_PROB_PENALTY = 0.12  # soft penalty on frequent losers

# ── ML layer: gradient boosting blended with KNN ─────────────────────────────
# KNN answers "what happened on the K most similar days"; boosting learns global
# feature interactions (e.g. momentum pays only when range expansion AND market
# direction agree). Blending the two is more robust than either alone on a few
# thousand noisy rows. Models train strictly on rows dated before the decision
# day, with time-decay sample weights (López de Prado, AFML ch. 4).
_GBM_BLEND = 0.5  # weight of the boosted model in the blend
_GBM_MIN_ROWS = 300  # below this, boosting overfits — KNN only
_GBM_RETRAIN_EVERY = 300  # retrain after this many new day-states (~3 scan days)
_gbm_cache: dict = {"n_rows": 0, "before": "", "models": {}}


def _score_arm(metrics: dict) -> float:
    """
    Profit-first objective with explicit downside penalties.

    Primary term is raw expectancy. Penalties are deliberately smaller so the
    model still prefers higher-profit arms unless their downside is materially
    worse. This is not a variance optimizer; it is an anti-blowup bias.
    """
    expectancy = float(metrics.get("expectancy", 0.0))
    downside = float(metrics.get("downside", 0.0))
    tail_loss = float(metrics.get("tail_loss", 0.0))
    loss_prob = float(metrics.get("loss_prob", 0.5))
    score = (
        expectancy
        - _DOWNSIDE_PENALTY * downside
        - _TAIL_PENALTY * tail_loss
        - _LOSS_PROB_PENALTY * max(loss_prob - 0.50, 0.0)
    )
    return round(score, 4)


def _blend_metric(knn_val: float | None, ml_val: float | None) -> float | None:
    if knn_val is None:
        return ml_val
    if ml_val is None:
        return knn_val
    return round((1 - _GBM_BLEND) * knn_val + _GBM_BLEND * ml_val, 4)


def _gbm_predict(hist: pd.DataFrame, x: pd.Series, date: str, arms: list) -> dict:
    """
    Per-arm ML risk/return estimates for today's day-state, or {}.

    Meta-labeling design (López de Prado): the noisy part of trading data is
    magnitude, the learnable part is direction. So instead of regressing raw R:
        1. classifier on the arm's TRADED days: p = P(win | day-state)
        2. magnitudes from history: W = decayed avg winning R, L = decayed avg losing R
        3. fire-rate f = decayed P(arm trades at all | trained on all days)
        Expected value = f × (p·W − (1−p)·L)
        Expected downside = f × ((1−p)·L)
    """
    if len(hist) < _GBM_MIN_ROWS:
        return {}
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError:
        return {}

    global _gbm_cache
    stale = (
        len(hist) - _gbm_cache["n_rows"] >= _GBM_RETRAIN_EVERY
        or _gbm_cache["before"] > date  # cache must never know the future
        or not _gbm_cache["models"]
    )
    if stale:
        models = {}
        age = (pd.Timestamp(date) - pd.to_datetime(hist["date"])).dt.days.clip(lower=0)
        sw_all = 0.5 ** (age / _DECAY_HALF_LIFE_DAYS)
        for arm in ARMS:
            r = hist[f"r_{arm}"].astype(float)
            t = hist[f"t_{arm}"].fillna(0).astype(int)
            traded = (t == 1) & r.notna()
            if traded.sum() < 60 or r[traded].gt(0).nunique() < 2:
                continue  # not enough trades to learn win/loss structure

            # P(win | state), trained only on days the arm actually traded
            clf = HistGradientBoostingClassifier(
                max_iter=120,
                max_depth=3,
                learning_rate=0.08,
                min_samples_leaf=25,
                l2_regularization=1.0,
                random_state=7,
            )
            clf.fit(
                hist.loc[traded, FEATURES],
                (r[traded] > 0).astype(int),
                sample_weight=sw_all[traded],
            )

            # Decayed win/loss magnitudes and fire rate
            w_tr = sw_all[traded]
            wins = r[traded] > 0
            W = (
                float((r[traded][wins] * w_tr[wins]).sum() / max(w_tr[wins].sum(), 1e-9))
                if wins.any()
                else 0.0
            )
            L = (
                float((-r[traded][~wins] * w_tr[~wins]).sum() / max(w_tr[~wins].sum(), 1e-9))
                if (~wins).any()
                else 0.0
            )
            ok = r.notna()
            fire = float((t[ok] * sw_all[ok]).sum() / max(sw_all[ok].sum(), 1e-9))

            models[arm] = {"clf": clf, "W": W, "L": L, "fire": fire}
        _gbm_cache = {"n_rows": len(hist), "before": date, "models": models}

    xv = pd.DataFrame([x[FEATURES]])
    out = {}
    for arm, m in _gbm_cache["models"].items():
        if arm not in arms:
            continue
        p = float(m["clf"].predict_proba(xv)[0][1])
        expectancy = m["fire"] * (p * m["W"] - (1 - p) * m["L"])
        downside = m["fire"] * ((1 - p) * m["L"])
        out[arm] = {
            "expectancy": round(expectancy, 4),
            "win_prob": round(m["fire"] * p, 4),
            "loss_prob": round(m["fire"] * (1 - p), 4),
            "trade_rate": round(m["fire"], 4),
            "downside": round(downside, 4),
            "tail_loss": round(m["L"], 4),
        }
    return out


_MARKET_CLOSE = (15, 15)


# ── Replay: simulate one arm on one prepared day ─────────────────────────────


def replay_arm(df_signals: pd.DataFrame) -> dict:
    """
    Simulate a single (symbol, day, arm): first signal after the observation
    window → entry at bar close; exit at SL / TP / 15:15 square-off.

    Returns {"r": net R-multiple, "traded": 0|1}.
    Days where the arm produced no entry return r=0 — the expected P&L of
    running an arm includes the days it sits out, so 0 is the honest value.
    """
    sig_rows = df_signals[df_signals["signal"] != 0]
    if sig_rows.empty:
        return {"r": 0.0, "traded": 0}

    entry_ts = sig_rows.index[0]
    entry_row = sig_rows.iloc[0]
    side = int(entry_row["signal"])
    entry = float(entry_row["close"])

    sl = float(entry_row.get("sl_hint", float("nan")))
    tp = float(entry_row.get("tp_hint", float("nan")))
    if math.isnan(sl) or math.isnan(tp):
        atr = float(entry_row.get("atr", 0.0)) or entry * 0.005
        sl = entry - side * 1.0 * atr
        tp = entry + side * 2.5 * atr

    risk_pct = abs(entry - sl) / entry * 100
    if risk_pct < _MIN_RISK_PCT:
        return {"r": 0.0, "traded": 0}

    close_ist = (
        df_signals.index[0]
        .astimezone(IST)
        .replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1], second=0, microsecond=0)
    )

    has_trail = "trail_long" in df_signals.columns
    exit_price = float(df_signals.iloc[-1]["close"])
    for ts, row in df_signals.loc[entry_ts:].iloc[1:].iterrows():
        price = float(row["close"])
        # Ratchet the stop along the strategy's trail levels (never loosen)
        if has_trail:
            if side == 1 and not math.isnan(float(row["trail_long"])):
                sl = max(sl, float(row["trail_long"]))
            elif side == -1 and not math.isnan(float(row["trail_short"])):
                sl = min(sl, float(row["trail_short"]))
        if side == 1:
            # trail stops are evaluated on bar close → fill at close (conservative);
            # hard stops are resting orders → fill at the stop level
            if price <= sl:
                exit_price = price if has_trail else sl
                break
            if price >= tp:
                exit_price = tp
                break
        else:
            if price >= sl:
                exit_price = price if has_trail else sl
                break
            if price <= tp:
                exit_price = tp
                break
        if ts >= close_ist:
            exit_price = price
            break

    move_pct = side * (exit_price - entry) / entry * 100
    r = (move_pct - _COST_PCT) / risk_pct
    return {"r": round(r, 3), "traded": 1}


# ── History store ─────────────────────────────────────────────────────────────


def init_history() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS arm_history (
                date     TEXT NOT NULL,
                symbol   TEXT NOT NULL,
                arm      TEXT NOT NULL,
                r        REAL NOT NULL,
                traded   INTEGER NOT NULL,
                features TEXT NOT NULL,
                PRIMARY KEY (date, symbol, arm)
            )
        """)


def record_day(date: str, symbol: str, features: dict, arm_results: dict) -> None:
    """arm_results: {arm_id: {"r": float, "traded": int}}"""
    versioned_features = {**features, "__feature_version": FEATURE_VERSION}
    feat_json = json.dumps(versioned_features)
    with sqlite3.connect(DB_PATH) as con:
        con.executemany(
            "INSERT OR REPLACE INTO arm_history (date, symbol, arm, r, traded, features) "
            "VALUES (?,?,?,?,?,?)",
            [
                (date, symbol, arm, res["r"], res["traded"], feat_json)
                for arm, res in arm_results.items()
            ],
        )
    _history_cache.update(before=None, df=None)  # table changed → invalidate


def record_no_data(date: str, symbol: str) -> None:
    """Marker so bootstrap doesn't re-attempt (symbol, day) pairs with no data."""
    feat_json = json.dumps({"__feature_version": FEATURE_VERSION})
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT OR REPLACE INTO arm_history (date, symbol, arm, r, traded, features) "
            "VALUES (?,?,'NODATA',0,0,?)",
            (date, symbol, feat_json),
        )


def has_day(date: str, symbol: str) -> bool:
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT arm, features FROM arm_history WHERE date=? AND symbol=?",
            (date, symbol),
        ).fetchall()
    if any(arm == "NODATA" for arm, _ in rows):
        try:
            return all(
                json.loads(fj).get("__feature_version", 0) == FEATURE_VERSION for _, fj in rows
            )
        except Exception:
            return False
    if len(rows) < len(ARMS):
        return False
    try:
        versions = {json.loads(feat_json).get("__feature_version", 0) for _, feat_json in rows}
    except Exception:
        return False
    return versions == {FEATURE_VERSION}


_history_cache: dict = {"before": None, "df": None}


def _load_history(before_date: str) -> pd.DataFrame:
    """All rows strictly before `before_date`, pivoted to one row per (date,symbol).

    Cached per before_date: in scan mode this is called ~15× per day on a
    table that only changes between days."""
    if _history_cache["before"] == before_date and _history_cache["df"] is not None:
        return _history_cache["df"]
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT date, symbol, arm, r, traded, features FROM arm_history WHERE date < ?",
            (before_date,),
        ).fetchall()
    if not rows:
        _history_cache.update(before=before_date, df=pd.DataFrame())
        return _history_cache["df"]

    by_key: dict = {}
    for date, symbol, arm, r, traded, feat_json in rows:
        features = json.loads(feat_json)
        if features.get("__feature_version", 0) != FEATURE_VERSION:
            continue
        key = (date, symbol)
        if key not in by_key:
            by_key[key] = {"features": features, "arms": {}, "traded": {}}
        by_key[key]["arms"][arm] = r
        by_key[key]["traded"][arm] = traded

    records = []
    for (date, symbol), v in by_key.items():
        if not any(arm in v["arms"] for arm in ARMS):
            continue  # NODATA marker rows carry no information
        rec = {"date": date, "symbol": symbol, **{f: v["features"].get(f, 0.0) for f in FEATURES}}
        for arm in ARMS:
            rec[f"r_{arm}"] = v["arms"].get(arm)
            rec[f"t_{arm}"] = v["traded"].get(arm, 0)
        records.append(rec)
    _history_cache.update(before=before_date, df=pd.DataFrame(records))
    return _history_cache["df"]


# ── Choose: conditional expectancy via KNN over past day-states ──────────────


def choose(features: dict, date: str, allowed_arms: list = None) -> dict:
    """
    Pick the arm with the best conditional expectancy for this day-state.

    Returns {
        "arm": "ORB" | "VWAP_FADE" | "GAP_FADE" | "NO_TRADE",
        "expectancy": {arm: mean R over neighbors},
        "score": {arm: profit-first, downside-adjusted score},
        "risk": {arm: loss/downside diagnostics},
        "n_history": int, "n_neighbors": int, "reason": str,
    }
    """
    arms = [a for a in (allowed_arms or ARMS) if a in ARMS]
    hist = _load_history(date)

    if hist.empty or len(hist) < _MIN_HISTORY:
        return {
            "arm": NO_TRADE,
            "expectancy": {},
            "n_history": len(hist),
            "n_neighbors": 0,
            "reason": f"insufficient history ({len(hist)}/{_MIN_HISTORY} day-states)",
        }

    # z-score features on history stats, then Euclidean distance
    x = pd.Series({f: float(features.get(f, 0.0)) for f in FEATURES})
    mu = hist[FEATURES].mean()
    sd = hist[FEATURES].std().replace(0, 1.0).fillna(1.0)
    hz = (hist[FEATURES] - mu) / sd
    xz = (x - mu) / sd
    dist = ((hz - xz) ** 2).sum(axis=1) ** 0.5

    k = min(_K_NEIGHBORS, len(hist))
    nearest = dist.nsmallest(k)
    weights = 1.0 / (1.0 + nearest)

    # Time decay (markets are non-stationary — recent regimes matter more):
    # half-life of _DECAY_HALF_LIFE_DAYS on the day-state's age.
    cur = pd.Timestamp(date)
    age_days = (cur - pd.to_datetime(hist.loc[nearest.index, "date"])).dt.days.clip(lower=0)
    weights = weights * 0.5 ** (age_days / _DECAY_HALF_LIFE_DAYS)

    arm_metrics: dict[str, dict] = {}
    for arm in arms:
        r_col = hist.loc[nearest.index, f"r_{arm}"].astype(float)
        valid = r_col.notna()
        if valid.sum() == 0:
            continue
        w = weights[valid]
        mean_r = float((r_col[valid] * w).sum() / w.sum())
        n_traded = int(hist.loc[nearest.index, f"t_{arm}"][valid].sum())
        shrink = n_traded / (n_traded + _SHRINK_N0)
        traded_mask = hist.loc[nearest.index, f"t_{arm}"].fillna(0).astype(int) == 1
        traded_r = r_col[traded_mask[valid]]
        traded_w = w[traded_mask[valid]]
        wins = traded_r > 0
        losses = traded_r < 0
        trade_rate = float(traded_w.sum() / w.sum()) if traded_w.sum() > 0 else 0.0
        cond_win_prob = float(traded_w[wins].sum() / traded_w.sum()) if traded_w.sum() > 0 else 0.0
        cond_loss_prob = (
            float(traded_w[losses].sum() / traded_w.sum()) if traded_w.sum() > 0 else 0.0
        )
        day_win_prob = trade_rate * cond_win_prob
        day_loss_prob = trade_rate * cond_loss_prob
        avg_loss = (
            float(((-traded_r[losses]) * traded_w[losses]).sum() / traded_w[losses].sum())
            if losses.any()
            else 0.0
        )
        tail_loss = 0.0
        if losses.any():
            worst = traded_r[losses].nsmallest(max(1, math.ceil(losses.sum() * 0.25)))
            tail_loss = float(-worst.mean())
        arm_metrics[arm] = {
            "expectancy": round(mean_r * shrink, 4),
            "win_prob": round(day_win_prob * shrink, 4),
            "loss_prob": round(day_loss_prob * shrink + (1 - shrink) * 0.25, 4),
            "trade_rate": round(trade_rate, 4),
            "downside": round(day_loss_prob * avg_loss * shrink, 4),
            "tail_loss": round(tail_loss * shrink, 4),
            "n_traded": n_traded,
        }

    # Blend in the boosted-tree predictions (global pattern learner)
    gbm = _gbm_predict(hist, x, date, arms)
    blended_metrics: dict[str, dict] = {}
    for arm in arms:
        knn = arm_metrics.get(arm, {})
        ml = gbm.get(arm, {})
        if not knn and not ml:
            continue
        metrics = {
            "expectancy": _blend_metric(knn.get("expectancy"), ml.get("expectancy")),
            "win_prob": _blend_metric(knn.get("win_prob"), ml.get("win_prob")),
            "loss_prob": _blend_metric(knn.get("loss_prob"), ml.get("loss_prob")),
            "trade_rate": _blend_metric(knn.get("trade_rate"), ml.get("trade_rate")),
            "downside": _blend_metric(knn.get("downside"), ml.get("downside")),
            "tail_loss": _blend_metric(knn.get("tail_loss"), ml.get("tail_loss")),
            "n_traded": int(knn.get("n_traded", 0)),
        }
        metrics["score"] = _score_arm(metrics)
        blended_metrics[arm] = metrics

    if not blended_metrics:
        return {
            "arm": NO_TRADE,
            "expectancy": {},
            "n_history": len(hist),
            "n_neighbors": k,
            "score": {},
            "risk": {},
            "reason": "no arm has history",
        }

    expectancy = {arm: round(m["expectancy"], 4) for arm, m in blended_metrics.items()}
    scores = {arm: round(m["score"], 4) for arm, m in blended_metrics.items()}
    risk = {
        arm: {
            "loss_prob": round(float(m.get("loss_prob", 0.0)), 4),
            "win_prob": round(float(m.get("win_prob", 0.0)), 4),
            "trade_rate": round(float(m.get("trade_rate", 0.0)), 4),
            "downside": round(float(m.get("downside", 0.0)), 4),
            "tail_loss": round(float(m.get("tail_loss", 0.0)), 4),
            "n_traded": int(m.get("n_traded", 0)),
        }
        for arm, m in blended_metrics.items()
    }

    # ── Decision: single-margin policy rule ──────────────────────────────────
    # Trade the argmax-EV arm iff its EV beats NO_TRADE's 0 by _EDGE_THRESHOLD.
    # No stacked risk vetoes: losses are already inside the replayed R-multiples,
    # so extra score floors / tail penalties double-count risk and encode
    # "never trade" (tail_loss ≈ 1R for ANY strategy — a stop-out is −1R by
    # definition). Risk's proper lever is position sizing, which already scales
    # with this EV. The score/risk maps stay as diagnostics for the UI.
    best_arm, best_metrics = max(
        blended_metrics.items(),
        key=lambda kv: kv[1]["expectancy"],
    )
    best_r = float(best_metrics["expectancy"])
    if best_r < _EDGE_THRESHOLD:
        return {
            "arm": NO_TRADE,
            "expectancy": expectancy,
            "score": scores,
            "risk": risk,
            "n_history": len(hist),
            "n_neighbors": k,
            "reason": f"best arm {best_arm} at {best_r:+.3f}R < +{_EDGE_THRESHOLD}R margin",
        }

    return {
        "arm": best_arm,
        "expectancy": expectancy,
        "score": scores,
        "risk": risk,
        "n_history": len(hist),
        "n_neighbors": k,
        "reason": f"{best_arm} expects {best_r:+.3f}R on {k} similar past days",
    }


# ── Cross-sectional day pick: stocks in play first, then the arm ─────────────

_IN_PLAY_MIN_RANK = 0.80  # only the top 20% of the universe by rel. volume
_IN_PLAY_MIN_VOLR = 1.30  # ...and volume must be genuinely elevated (1.3× normal)
_SCAN_EDGE_MARGIN = 0.05  # higher bar than single-symbol mode: argmax over many
# noisy estimates suffers winner's curse


def choose_day(
    features_by_symbol: dict, date: str, allowed_arms: list = None, top_n: int = 3
) -> dict:
    """
    The day's trade list, cross-sectionally.

    1. Gate to stocks in play: top-quintile relative volume AND ≥1.3× normal
       first-30 volume (Zarattini/Barbon/Aziz — the edge concentrates there).
    2. For each in-play symbol, conditional best arm via choose().
    3. Rank by expectancy, return up to top_n picks clearing _SCAN_EDGE_MARGIN.

    Returns {"picks": [{"symbol", "arm", "expectancy", "decision"}...],
             "in_play": [symbols], "n_scanned": int}
    """
    in_play = [
        sym
        for sym, f in features_by_symbol.items()
        if f
        and f.get("vol_ratio_rank", 0.0) >= _IN_PLAY_MIN_RANK
        and f.get("vol_ratio", 0.0) >= _IN_PLAY_MIN_VOLR
    ]
    picks = []
    for sym in in_play:
        decision = choose(features_by_symbol[sym], date, allowed_arms=allowed_arms)
        arm = decision["arm"]
        if arm == NO_TRADE:
            continue
        ev = float(decision["expectancy"].get(arm, 0.0))
        if ev < _SCAN_EDGE_MARGIN:
            continue
        picks.append({"symbol": sym, "arm": arm, "expectancy": ev, "decision": decision})
    picks.sort(key=lambda p: p["expectancy"], reverse=True)
    return {"picks": picks[:top_n], "in_play": in_play, "n_scanned": len(features_by_symbol)}

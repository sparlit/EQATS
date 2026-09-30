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
Rule Engine — generic strategy evaluation.

Strategies are JSON definitions stored in data/strategies.json.

v2 (2026-09-12): score uses percentile ranks within the current universe.
Raw-value scoring was outlier-dominated (holding companies with weird
accounting inflating the whole score). Percentile scoring produces
comparable numbers across symbols.
"""
import datetime as dt
import json
import math
import os

import db
import numpy as np
import pandas as pd
from log_utils import get_logger

log = get_logger("rule_engine")

STRATEGIES_PATH = os.path.join("data", "strategies.json")

OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


# ============================================================
# Strategy file I/O
# ============================================================
def _ensure_file():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(STRATEGIES_PATH):
        with open(STRATEGIES_PATH, "w") as f:
            json.dump({}, f, indent=2)


def load_strategies():
    _ensure_file()
    try:
        with open(STRATEGIES_PATH) as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"strategies file unreadable: {e}")
        return {}


def save_strategies(strategies):
    _ensure_file()
    with open(STRATEGIES_PATH, "w") as f:
        json.dump(strategies, f, indent=2)


def get_strategy(name):
    return load_strategies().get(name)


def save_strategy(name, definition):
    s = load_strategies()
    s[name] = definition
    save_strategies(s)


def delete_strategy(name):
    s = load_strategies()
    s.pop(name, None)
    save_strategies(s)


# ============================================================
# Feature computation helpers
# ============================================================
def _seq_len(v):
    if v is None:
        return 0
    try:
        return len(v)
    except Exception:
        return 0


def _ema(vals, span):
    if _seq_len(vals) == 0:
        return None
    k = 2.0 / (span + 1.0)
    e = float(vals[0])
    for v in vals[1:]:
        e = float(v) * k + e * (1 - k)
    return e


def _sma(vals, span):
    if _seq_len(vals) < span:
        return None
    return float(np.mean(vals[-span:]))


def _rsi(closes, period=14):
    if _seq_len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        ch = float(closes[i]) - float(closes[i - 1])
        if ch > 0:
            gains += ch
        else:
            losses -= ch
    if losses == 0:
        return 100.0
    return 100 - (100 / (1 + gains / losses))


def _find_gapup(o, c, lookback=15, min_gap=0.04):
    n = len(c)
    out = {
        "had_gapup_15d": 0,
        "days_since_gapup": None,
        "gapup_size": None,
        "pre_gap_above50": None,
        "pre_gap_above200": None,
        "pre_gap_drawdown": None,
    }
    if n < 22:
        return out
    for lb in range(1, lookback + 1):
        idx = n - lb
        if idx < 1:
            break
        prev_close = float(c[idx - 1])
        if prev_close <= 0:
            continue
        gap = float(o[idx]) / prev_close - 1
        if gap >= min_gap:
            out["had_gapup_15d"] = 1
            out["days_since_gapup"] = n - 1 - idx
            out["gapup_size"] = float(gap)
            if idx >= 50:
                s50 = _sma(c[:idx], 50)
                if s50:
                    out["pre_gap_above50"] = 1 if prev_close > s50 else 0
            if idx >= 200:
                s200 = _sma(c[:idx], 200)
                if s200:
                    out["pre_gap_above200"] = 1 if prev_close > s200 else 0
            if idx >= 60:
                h60 = float(np.max(c[idx - 60 : idx]))
                if h60 > 0:
                    out["pre_gap_drawdown"] = (h60 - prev_close) / h60
            return out
    return out


def _impulse_pullback(c, h, l, lookback=60):
    out = {
        "impulse_pct_60d": None,
        "days_since_impulse_peak": None,
        "pullback_from_peak_pct": None,
        "consolidation_range_pct": None,
        "consolidation_vol_ratio": None,
    }
    n = len(c)
    if n < 30:
        return out
    window = min(lookback, n)
    h_seg = h[n - window :]
    local_peak = int(np.argmax(h_seg))
    peak_idx = n - window + local_peak
    peak_high = float(h[peak_idx])
    low_start = max(0, peak_idx - 40)
    low_before = float(np.min(l[low_start : peak_idx + 1]))
    if low_before <= 0:
        return out
    out["impulse_pct_60d"] = (peak_high - low_before) / low_before
    days_since = n - 1 - peak_idx
    out["days_since_impulse_peak"] = days_since
    out["pullback_from_peak_pct"] = (peak_high - float(c[-1])) / peak_high if peak_high > 0 else None
    if days_since >= 1:
        cons_high = float(np.max(h[peak_idx + 1 :]))
        cons_low = float(np.min(l[peak_idx + 1 :]))
        if peak_high > 0:
            out["consolidation_range_pct"] = (cons_high - cons_low) / peak_high
    return out


def _compute_features(sym, df, fund_row, sector, sector_rs):
    if df is None or len(df) < 60:
        return None
    c = df["Close"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    v = df["Volume"].values.astype(float)
    o = df["Open"].values.astype(float)

    close = float(c[-1])
    open_ = float(o[-1])

    dma20 = _sma(c, 20)
    dma50 = _sma(c, 50)
    dma200 = _sma(c, 200)
    high52 = float(np.max(h[-252:])) if len(h) >= 252 else float(np.max(h))
    low52 = float(np.min(l[-252:])) if len(l) >= 252 else float(np.min(l))

    atr = None
    if len(c) >= 15:
        trs = []
        for i in range(1, len(c)):
            trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        atr = float(np.mean(trs[-14:]))

    mom_5d = (c[-1] / c[-6] - 1) if len(c) >= 6 else None
    mom_20d = (c[-1] / c[-21] - 1) if len(c) >= 21 else None
    mom_60d = (c[-1] / c[-61] - 1) if len(c) >= 61 else None

    avg_vol_20 = _sma(v, 20)
    vol_ratio_20 = (float(v[-1]) / avg_vol_20) if avg_vol_20 else None

    gap = _find_gapup(o, c, lookback=15, min_gap=0.04)
    imp = _impulse_pullback(c, h, l, lookback=60)

    features = {
        "symbol": sym,
        "close": close,
        "open": open_,
        "high": float(h[-1]),
        "low": float(l[-1]),
        "volume": float(v[-1]),
        "high52": high52,
        "low52": low52,
        "distance_from_52w_high": ((high52 - close) / high52) if high52 > 0 else None,
        "distance_from_52w_low": ((close - low52) / low52) if low52 > 0 else None,
        "dma20": dma20,
        "dma50": dma50,
        "dma200": dma200,
        "above20": 1 if (dma20 and close > dma20) else 0,
        "above50": 1 if (dma50 and close > dma50) else 0,
        "above200": 1 if (dma200 and close > dma200) else 0,
        "mom_5d": mom_5d,
        "mom_20d": mom_20d,
        "mom_60d": mom_60d,
        "rsi": _rsi(c),
        "avg_vol_20": avg_vol_20,
        "vol_ratio_20": vol_ratio_20,
        "close_gt_open": 1 if close > open_ else 0,
        "atr_14": atr,
        "atr_pct": (atr / close) if (atr and close) else None,
        "sector_rs": sector_rs,
    }
    features.update(gap)
    features.update(imp)

    if fund_row:
        for k in [
            "roce",
            "pe",
            "pb",
            "roe",
            "debt_to_equity",
            "profit_growth_3y",
            "sales_growth_3y",
            "promoter_holding",
            "dividend_yield",
            "cfo_positive",
            "market_cap_cr",
            "operating_margin",
            "net_profit_margin",
            "beta_1y",
            "eps_fy",
            "book_value",
            "ev_ebitda",
            "fcf_fy",
            "net_debt_fy",
        ]:
            features[k] = fund_row.get(k)

    features["sector"] = sector
    return features


def _load_symbol_df(conn, sym, max_bars=300):
    rows = conn.execute(
        "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (sym, max_bars),
    ).fetchall()
    if not rows or len(rows) < 60:
        return None
    rows = list(reversed(rows))
    return pd.DataFrame(rows, columns=["date", "Open", "High", "Low", "Close", "Volume"]).set_index("date")


def _load_fundamentals(conn):
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fundamentals)")]
    except Exception:
        return {}
    out = {}
    if not cols:
        return out
    sel = ", ".join(cols)
    for row in conn.execute(f"SELECT {sel} FROM fundamentals").fetchall():
        m = dict(zip(cols, row, strict=False))
        sym = m.get("symbol")
        if sym:
            out[sym] = m
    return out


def _load_sectors(conn):
    out = {}
    try:
        for sym, sec in conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL"):
            out[sym] = sec
    except Exception:
        pass
    return out


def _load_sector_rs(conn):
    try:
        import sector_gate

        g = sector_gate.sector_perf(conn)
        if g is None or g.empty:
            return {}
        n = len(g)
        rank = {r["sector"]: 1.0 - (i / max(1, n - 1)) for i, (_, r) in enumerate(g.iterrows())}
        out = {}
        for sym, sec in conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL"):
            out[sym] = rank.get(sec, 0.5)
        return out
    except Exception:
        return {}


def _universe_symbols(conn, universe):
    if universe == "active":
        rows = conn.execute("SELECT symbol FROM stocks WHERE active=1").fetchall()
    elif universe == "band":
        rows = conn.execute(
            "SELECT symbol FROM universe_broad "
            "WHERE mcap_cr BETWEEN 1000 AND 8000 "
            "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
            "ORDER BY mcap_cr DESC LIMIT 800"
        ).fetchall()
    elif universe == "combined":
        from universe_helper import combined_universe

        return combined_universe(conn, band_limit=800)
    else:
        rows = conn.execute("SELECT symbol FROM stocks WHERE active=1").fetchall()
    return sorted({r[0] for r in rows})


# ============================================================
# Percentile ranks
# ============================================================
def _percentile_ranks(sym_values):
    """sym_values = list of (symbol, value). Returns dict symbol -> pct (0-100).
    Symbols with None or NaN values are omitted."""
    valid = []
    for s, v in sym_values:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(fv) or math.isinf(fv):
            continue
        valid.append((s, fv))
    if not valid:
        return {}
    valid.sort(key=lambda x: x[1])
    n = len(valid)
    out = {}
    for i, (s, v) in enumerate(valid):
        out[s] = (100.0 * i / (n - 1)) if n > 1 else 50.0
    return out


# ============================================================
# Evaluation
# ============================================================
def _condition_label(cond, features):
    field = cond["field"]
    op = cond["op"]
    want = cond["value"]
    got = features.get(field)
    try:
        ok = OPS[op](got, want) if got is not None else False
    except Exception:
        ok = False
    if got is None:
        got_str = "—"
    elif isinstance(got, float):
        got_str = f"{got:.3f}"
    else:
        got_str = str(got)
    return {"field": field, "op": op, "want": want, "got": got_str, "ok": bool(ok)}


def evaluate(strategy, features, pct_maps=None):
    conditions = strategy.get("conditions", [])
    checks = [_condition_label(c, features) for c in conditions]
    passed = all(c["ok"] for c in checks)
    if not passed:
        return {"passed": False, "score": None, "checks": checks}

    weights = strategy.get("score_weights", {})
    sym = features.get("symbol")
    score = 0.0
    have = False
    for field, w in weights.items():
        if pct_maps and field in pct_maps and sym in pct_maps[field]:
            pct = pct_maps[field][sym]
            # Negative weight = lower is better → invert percentile
            if w < 0:
                pct = 100.0 - pct
            score += pct * abs(w)
            have = True
        else:
            # Fallback: raw value × weight (used when pct map missing)
            v = features.get(field)
            if v is None:
                continue
            try:
                score += float(v) * float(w)
                have = True
            except Exception:
                continue
    return {"passed": True, "score": round(score, 3) if have else 0.0, "checks": checks}


def _diagnose(strategy, all_checks):
    conditions = strategy.get("conditions", [])
    n = len(all_checks)
    if n == 0:
        return {"n_evaluated": 0, "per_condition": []}

    fails = [0] * len(conditions)
    missing = [0] * len(conditions)
    for checks in all_checks:
        for i, c in enumerate(checks):
            if not c["ok"]:
                fails[i] += 1
                if c["got"] == "—":
                    missing[i] += 1

    survivors = [n]
    for i in range(len(conditions)):
        alive = 0
        for checks in all_checks:
            if all(checks[j]["ok"] for j in range(i + 1)):
                alive += 1
        survivors.append(alive)

    per_condition = []
    for i, c in enumerate(conditions):
        per_condition.append(
            {
                "field": c["field"],
                "op": c["op"],
                "want": c["value"],
                "failed": fails[i],
                "failed_because_missing": missing[i],
                "survived_after": survivors[i + 1],
            }
        )
    return {"n_evaluated": n, "per_condition": per_condition}


def run_strategy(name, limit=50):
    strategies = load_strategies()
    s = strategies.get(name)
    if not s:
        return {"error": f"strategy '{name}' not found"}

    conn = db.get_conn()
    syms = _universe_symbols(conn, s.get("universe", "active"))
    funds = _load_fundamentals(conn)
    sectors = _load_sectors(conn)
    srs = _load_sector_rs(conn)
    conn.close()

    # ---- Pass 1: compute features for every symbol ----
    feats_list = []
    for sym in syms:
        df = _load_symbol_df(db.get_conn(), sym)  # hmm, reopens per call
        # Use single connection for speed
    # Restructure: keep one connection open for the loop

    conn = db.get_conn()
    feats_list = []
    for sym in syms:
        df = _load_symbol_df(conn, sym)
        if df is None:
            continue
        f = _compute_features(sym, df, funds.get(sym), sectors.get(sym), srs.get(sym))
        if f:
            feats_list.append((sym, f))
    conn.close()

    # ---- Percentile maps for score fields ----
    score_fields = list((s.get("score_weights") or {}).keys())
    pct_maps = {}
    for field in score_fields:
        pct_maps[field] = _percentile_ranks([(sym, f.get(field)) for sym, f in feats_list])

    # ---- Pass 2: evaluate conditions + compute score ----
    results = []
    all_checks = []
    for sym, feats in feats_list:
        r = evaluate(s, feats, pct_maps=pct_maps)
        all_checks.append(r["checks"])
        if not r["passed"]:
            continue
        results.append(
            {
                "symbol": sym,
                "score": r["score"],
                "sector": feats.get("sector"),
                "close": feats.get("close"),
                "distance_from_52w_high": feats.get("distance_from_52w_high"),
                "checks": r["checks"],
                "top_features": {k: feats.get(k) for k in score_fields},
            }
        )

    results.sort(key=lambda r: -(r["score"] if r["score"] is not None else 0))
    diag = _diagnose(s, all_checks)

    return {
        "strategy": name,
        "type": s.get("type", "unknown"),
        "universe": s.get("universe", "active"),
        "n_symbols_checked": len(feats_list),
        "n_passed": len(results),
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "picks": results[:limit],
        "diagnostic": diag,
    }


def run_all():
    out = {}
    for name in load_strategies():
        try:
            out[name] = run_strategy(name, limit=30)
        except Exception as e:
            out[name] = {"error": str(e)}
    return out


# ============================================================
# Seed strategies (unchanged from last version)
# ============================================================
SEEDS = {
    "Multibagger": {
        "name": "Multibagger",
        "description": (
            "Quality compounder — high ROCE/ROE, low debt, positive FCF. "
            "(Note: growth data unavailable on TV India; quality-only.)"
        ),
        "type": "fundamental",
        "universe": "active",
        "conditions": [
            {"field": "roce", "op": ">=", "value": 15},
            {"field": "roe", "op": ">=", "value": 12},
            {"field": "debt_to_equity", "op": "<=", "value": 1.0},
            {"field": "cfo_positive", "op": "==", "value": 1},
            {"field": "operating_margin", "op": ">=", "value": 8},
        ],
        "score_weights": {
            "roce": 0.35,
            "roe": 0.25,
            "operating_margin": 0.20,
            "pe": -0.20,
        },
    },
    "RCP": {
        "name": "RCP — Range Contraction Pattern",
        "description": ("Stock ran 15-30% up, then meandered 4-12 days retracing 5-20% on lower volume."),
        "type": "swing",
        "universe": "band",
        "conditions": [
            {"field": "above200", "op": "==", "value": 1},
            {"field": "impulse_pct_60d", "op": ">=", "value": 0.15},
            {"field": "impulse_pct_60d", "op": "<=", "value": 0.30},
            {"field": "days_since_impulse_peak", "op": ">=", "value": 4},
            {"field": "days_since_impulse_peak", "op": "<=", "value": 12},
            {"field": "consolidation_range_pct", "op": ">=", "value": 0.05},
            {"field": "consolidation_range_pct", "op": "<=", "value": 0.20},
            {"field": "vol_ratio_20", "op": "<=", "value": 1.0},
        ],
        "score_weights": {
            "impulse_pct_60d": 0.4,
            "sector_rs": 0.3,
            "vol_ratio_20": -0.2,
        },
    },
    "EpisodicPivot": {
        "name": "Episodic Pivot",
        "description": (
            "Downtrend stock suddenly gaps up on high volume within last 15 days. Reaction to news / results / event."
        ),
        "type": "swing",
        "universe": "band",
        "conditions": [
            {"field": "had_gapup_15d", "op": "==", "value": 1},
            {"field": "days_since_gapup", "op": "<=", "value": 15},
            {"field": "gapup_size", "op": ">=", "value": 0.04},
            {"field": "vol_ratio_20", "op": ">=", "value": 1.5},
            {"field": "distance_from_52w_high", "op": "<=", "value": 0.30},
        ],
        "score_weights": {
            "gapup_size": 0.4,
            "vol_ratio_20": 0.3,
            "mom_20d": 0.3,
        },
    },
}


def seed_if_empty(force=False):
    s = load_strategies()
    added = 0
    for name, definition in SEEDS.items():
        if force or name not in s:
            s[name] = definition
            added += 1
    if added:
        save_strategies(s)
        log.info(f"seeded {added} strategies")
    return added


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]

    if "--seed" in argv:
        n = seed_if_empty(force="--force" in argv)
        print(f"seeded {n} strategies")
        sys.exit(0)

    if "--list" in argv:
        s = load_strategies()
        print(json.dumps(list(s.keys()), indent=2))
        sys.exit(0)

    if "--run" in argv:
        idx = argv.index("--run")
        name = argv[idx + 1] if idx + 1 < len(argv) else None
        if not name:
            print("usage: rule_engine.py --run STRATEGY_NAME")
            sys.exit(1)
        out = run_strategy(name, limit=20)
        if "error" in out:
            print(f"ERROR: {out['error']}")
            sys.exit(1)
        print(f"[{out['strategy']}] {out['n_passed']} passed of {out['n_symbols_checked']} checked")
        for p in out["picks"]:
            print(f"  {p['symbol']:<14} score {p['score']:>8.3f}  {p['sector'] or '?'}")
        diag = out.get("diagnostic") or {}
        pc = diag.get("per_condition") or []
        if pc:
            print()
            print(f"  failure breakdown (n={diag.get('n_evaluated')}):")
            for c in pc:
                fb = c["failed_because_missing"]
                print(
                    f"    {c['field']:<26} {c['op']:<3} "
                    f"{c['want']!s:<8}  failed {c['failed']:<5} "
                    f"(missing {fb:<5})  survived {c['survived_after']}"
                )
        sys.exit(0)

    print("commands: --seed [--force] | --list | --run NAME")

from __future__ import annotations

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
Condition-builder scan engine (ported from the QuantEdge project into AXIOM).

Computes a full named-column indicator frame per symbol, then evaluates
Chartink-style conditions: {ind, op, vt, val|vi, lg} joined with AND/OR.
Operators include cross-above / cross-below. RHS is a constant or another
indicator column. Powers /api/scan/builder.
"""

import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from loguru import logger


def _wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1.0 / n, min_periods=n, adjust=False).mean()


def compute_indicators(df: pd.DataFrame, nifty_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return a frame of named indicator columns for condition evaluation."""
    c, h, l, v, o = df["close"], df["high"], df["low"], df["volume"], df["open"]
    idx = df.index
    cols: dict[str, pd.Series] = {"open": o, "high": h, "low": l, "close": c, "volume": v}

    for p in (5, 9, 13, 20, 26, 50, 100, 200):
        cols[f"ema{p}"] = c.ewm(span=p, adjust=False).mean()
    for p in (5, 10, 20, 50, 100, 200):
        cols[f"sma{p}"] = c.rolling(p).mean()

    def _rsi(s: pd.Series, n: int) -> pd.Series:
        d = s.diff()
        return 100 - 100 / (1 + _wilder(d.clip(lower=0), n) / _wilder((-d).clip(lower=0), n).replace(0, np.nan))

    for n in (7, 9, 14, 21):
        cols[f"rsi{n}"] = _rsi(c, n)

    e12, e26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = e12 - e26
    cols["macd"], cols["macd_sig"] = macd, macd.ewm(span=9, adjust=False).mean()
    cols["macd_hist"] = cols["macd"] - cols["macd_sig"]

    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    cols["bb_mid"], cols["bb_up"], cols["bb_lo"] = mid, mid + 2 * sd, mid - 2 * sd
    cols["bb_bw"] = (cols["bb_up"] - cols["bb_lo"]) / mid
    cols["bb_pctb"] = (c - cols["bb_lo"]) / (cols["bb_up"] - cols["bb_lo"])

    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    for n in (7, 14, 21):
        cols[f"atr{n}"] = _wilder(tr, n)
    cols["atr_pct"] = cols["atr14"] / c * 100

    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=idx)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=idx)
    atr14 = _wilder(tr, 14)
    dip = 100 * _wilder(pdm, 14) / atr14.replace(0, np.nan)
    dim = 100 * _wilder(ndm, 14) / atr14.replace(0, np.nan)
    dx = 100 * (dip - dim).abs() / (dip + dim).replace(0, np.nan)
    cols["adx14"], cols["di_plus"], cols["di_minus"] = _wilder(dx.fillna(0), 14), dip, dim

    low14, high14 = l.rolling(14).min(), h.rolling(14).max()
    k = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    cols["stoch_k"] = k.rolling(3).mean()
    cols["stoch_d"] = cols["stoch_k"].rolling(3).mean()

    tp = (h + l + c) / 3
    mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cols["cci20"] = (tp - tp.rolling(20).mean()) / (0.015 * mad.replace(0, np.nan))
    cols["willr14"] = -100 * (h.rolling(14).max() - c) / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)

    # Supertrend (10, 3)
    atr10 = _wilder(tr, 10)
    hl2 = (h + l) / 2
    ub, lb = hl2 + 3 * atr10, hl2 - 3 * atr10
    pd.Series(np.nan, index=idx)
    pd.Series(1, index=idx)
    cl_vals = c.to_numpy()
    ub_v, lb_v = ub.to_numpy(), lb.to_numpy()
    st_v = np.full(len(idx), np.nan)
    dir_v = np.ones(len(idx), dtype=int)
    for i in range(1, len(idx)):
        prev_st = st_v[i - 1] if not np.isnan(st_v[i - 1]) else lb_v[i]
        if dir_v[i - 1] == 1:
            cur = max(lb_v[i], prev_st) if cl_vals[i] > prev_st else ub_v[i]
            dir_v[i] = 1 if cl_vals[i] > cur else -1
        else:
            cur = min(ub_v[i], prev_st) if cl_vals[i] < prev_st else lb_v[i]
            dir_v[i] = -1 if cl_vals[i] < cur else 1
        st_v[i] = cur
    cols["supertrend"] = pd.Series(st_v, index=idx)
    cols["supertrend_dir"] = pd.Series(dir_v, index=idx)

    cols["vwap20"] = (tp * v).rolling(20).sum() / v.rolling(20).sum().replace(0, np.nan)
    avg_vol = v.rolling(20).mean()
    cols["avg_vol20"], cols["vol_ratio"] = avg_vol, v / avg_vol.replace(0, np.nan)
    cols["vol_ratio5"] = v / v.rolling(5).mean().replace(0, np.nan)
    cols["obv"] = (np.sign(c.diff()) * v).fillna(0).cumsum()
    cols["pct_chg"] = c.pct_change() * 100
    cols["pct_chg5"] = c.pct_change(5) * 100
    cols["pct_chg20"] = c.pct_change(20) * 100

    for n in (5, 10, 20, 50):
        cols[f"high{n}d"], cols[f"low{n}d"] = h.rolling(n).max(), l.rolling(n).min()
    cols["high52w"], cols["low52w"] = h.rolling(252).max(), l.rolling(252).min()
    cols["pct52h"] = (c - cols["high52w"]) / cols["high52w"] * 100
    cols["pct52l"] = (c - cols["low52w"]) / cols["low52w"] * 100

    rng = h - l
    cols["inside_bar"] = (h <= h.shift(1)) & (l >= l.shift(1))
    cols["outside_bar"] = (h >= h.shift(1)) & (l <= l.shift(1))
    cols["nr4"] = rng <= rng.rolling(4).min().shift(1)
    cols["nr7"] = rng <= rng.rolling(7).min().shift(1)
    body, full = (c - o).abs(), (h - l).replace(0, np.nan)
    cols["hammer"] = (body / full < 0.3) & ((c - l) / full > 0.6)
    cols["shooting_star"] = (body / full < 0.3) & ((h - c) / full > 0.6)
    cols["bullish_engulf"] = (c > o) & (c.shift(1) < o.shift(1)) & (c > o.shift(1)) & (o < c.shift(1))
    cols["bearish_engulf"] = (c < o) & (c.shift(1) > o.shift(1)) & (c < o.shift(1)) & (o > c.shift(1))
    cols["doji"] = body / full < 0.1

    if nifty_df is not None and not nifty_df.empty:
        nc = nifty_df["close"].reindex(idx, method="ffill")
        if c.iloc[0] > 0 and nc.iloc[0] > 0:
            rs = (c / c.iloc[0]) / (nc / nc.iloc[0])
            cols["rs_nifty"] = rs
            cols["rs_nifty5d"] = rs.pct_change(5) * 100
            cols["rs_nifty20d"] = rs.pct_change(20) * 100

    return pd.DataFrame(cols, index=idx)


# ── condition evaluation ────────────────────────────────────────────────────
OPS = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "x_above": lambda a, b: (a > b) & (a.shift() <= _shift(b)),
    "x_below": lambda a, b: (a < b) & (a.shift() >= _shift(b)),
}


def _shift(b):
    return b.shift() if isinstance(b, pd.Series) else b


def _rhs(df: pd.DataFrame, cond: dict):
    if cond.get("vt") == "ind" and cond.get("vi") in df.columns:
        return df[cond["vi"]]
    val = cond.get("val", "0")
    if val == "true":
        return True
    if val == "false":
        return False
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _eval(df: pd.DataFrame, cond: dict) -> pd.Series:
    ind = cond.get("ind", "close")
    if ind not in df.columns:
        return pd.Series(False, index=df.index)
    if cond.get("vt") == "bool":
        return df[ind].fillna(False).astype(bool)
    fn = OPS.get(cond.get("op", "gt"))
    if not fn:
        return pd.Series(False, index=df.index)
    try:
        r = fn(df[ind], _rhs(df, cond))
        return r.fillna(False) if isinstance(r, pd.Series) else pd.Series(bool(r), index=df.index)
    except Exception:
        return pd.Series(False, index=df.index)


def apply_conditions(df: pd.DataFrame, conditions: list[dict]) -> pd.Series:
    if not conditions:
        return pd.Series(True, index=df.index)
    mask = _eval(df, conditions[0])
    for cond in conditions[1:]:
        cm = _eval(df, cond)
        mask = mask | cm if str(cond.get("lg", "AND")).upper() == "OR" else mask & cm
    return mask


def _setup(last: pd.Series) -> str:
    try:
        rsi = float(last.get("rsi14", 0) or 0)
        adx = float(last.get("adx14", 0) or 0)
        vr = float(last.get("vol_ratio", 0) or 0)
        rs = float(last.get("rs_nifty", 1) or 1)
        bw = float(last.get("bb_bw", 0) or 0)
        chg = float(last.get("pct_chg", 0) or 0)
        cl = float(last["close"])
        e20 = float(last.get("ema20", cl) or cl)
        e50 = float(last.get("ema50", cl) or cl)
        std = int(last.get("supertrend_dir", 1) or 1)
        if bw < 0.06 and cl > e20:
            return "BB Squeeze"
        if bool(last.get("nr7")) or bool(last.get("nr4")):
            return "NR Breakout"
        if std == 1 and vr > 2.5 and chg > 1.5:
            return "Breakout"
        if rs > 1.05 and rsi > 55 and cl > e20:
            return "RS Leader"
        if rsi > 60 and adx > 25 and cl > e20 > e50:
            return "Momentum"
        if std == 1 and cl > e20 and adx > 20:
            return "Supertrend ↑"
        return "Signal"
    except Exception:
        return "Signal"


def _safe(last: pd.Series, col: str, dec: int = 2):
    try:
        f = float(last.get(col, np.nan))
        return None if f != f else round(f, dec)
    except (TypeError, ValueError):
        return None


def _scan_one(sym: str, conditions: list[dict], nifty_df, fetch_fn) -> dict | None:
    try:
        df = fetch_fn(sym, "1y", "1d")
        if df is None or df.empty or len(df) < 30:
            return None
        ind = compute_indicators(df, nifty_df)
        if not bool(apply_conditions(ind, conditions).iloc[-1]):
            return None
        last = ind.iloc[-1]
        return {
            "symbol": sym.replace(".NS", ""),
            "price": _safe(last, "close"),
            "change": _safe(last, "pct_chg"),
            "rsi14": _safe(last, "rsi14", 1),
            "adx14": _safe(last, "adx14", 1),
            "vol_ratio": _safe(last, "vol_ratio"),
            "rs_nifty": _safe(last, "rs_nifty", 3),
            "atr_pct": _safe(last, "atr_pct"),
            "supertrend_dir": int(last.get("supertrend_dir", 0) or 0),
            "ema20": _safe(last, "ema20"),
            "ema50": _safe(last, "ema50"),
            "ema200": _safe(last, "ema200"),
            "pct52h": _safe(last, "pct52h"),
            "macd_hist": _safe(last, "macd_hist", 3),
            "setup": _setup(last),
        }
    except Exception as exc:
        logger.debug("builder scan {} failed: {}", sym, exc)
        return None


def run_builder(symbols: list[str], conditions: list[dict], fetch_fn, nifty_df=None, workers: int = 8) -> list[dict]:
    """Scan symbols against conditions. fetch_fn(sym, period, interval) -> OHLCV df."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(lambda s: _scan_one(s, conditions, nifty_df, fetch_fn), symbols))
    return [r for r in out if r]


# ── event-driven backtester (replays the same conditions) ───────────────────
def _bt_one(sym, conditions, ind_df, from_date, to_date, stop_pct, exit_days, exit_rule, target_rr):
    """Backtest one symbol's pre-computed indicator frame. Returns list of trades."""
    try:
        df_bt = ind_df.loc[from_date:to_date]
    except Exception:
        return []
    if len(df_bt) < 10:
        return []
    mask = apply_conditions(df_bt, conditions)
    trades = []
    busy_until = -1  # one position per symbol — skip signals while already in a trade
    for sig_dt in df_bt.index[mask]:
        i = df_bt.index.get_loc(sig_dt)
        if i <= busy_until or i + 1 >= len(df_bt):
            continue
        entry_dt = df_bt.index[i + 1]
        entry = float(df_bt["open"].iloc[i + 1])
        if entry <= 0:
            continue
        sl = entry * (1 - stop_pct / 100)
        target = entry * (1 + (stop_pct * target_rr) / 100)
        exit_px = exit_dt = None
        reason = "timeout"
        future = df_bt.iloc[i + 2 : i + 2 + exit_days]
        for fdt, row in future.iterrows():
            lo, hi, cl = float(row["low"]), float(row["high"]), float(row["close"])
            if lo <= sl:
                exit_px, exit_dt, reason = sl, fdt, "stop"
                break
            if hi >= target:
                exit_px, exit_dt, reason = target, fdt, "target"
                break
            if exit_rule == "RSI Overbought (>70)" and float(row.get("rsi14", 50) or 50) > 70:
                exit_px, exit_dt, reason = cl, fdt, "rsi"
                break
            if exit_rule == "EMA Cross Down" and cl < float(row.get("ema20", cl) or cl):
                exit_px, exit_dt, reason = cl, fdt, "ema"
                break
        if exit_px is None and len(future):
            exit_px, exit_dt = float(future["close"].iloc[-1]), future.index[-1]
        if exit_px is None:
            continue
        pnl_pct = (exit_px - entry) / entry * 100
        trades.append(
            {
                "symbol": sym.replace(".NS", ""),
                "entry_date": str(entry_dt.date()),
                "exit_date": str(exit_dt.date()) if exit_dt is not None else "",
                "entry": round(entry, 2),
                "exit": round(exit_px, 2),
                "sl": round(sl, 2),
                "target": round(target, 2),
                "pnl_pct": round(pnl_pct, 2),
                "rr": round(pnl_pct / stop_pct, 2),
                "days": (exit_dt - entry_dt).days if exit_dt is not None else exit_days,
                "result": "WIN" if pnl_pct > 0 else "LOSS",
                "exit_reason": reason,
            }
        )
        busy_until = df_bt.index.get_loc(exit_dt) if exit_dt is not None else i + 1 + exit_days
    return trades


def run_backtest(
    symbols,
    conditions,
    fetch_fn,
    nifty_df=None,
    from_date="2024-01-01",
    to_date=None,
    stop_pct=3.0,
    exit_days=8,
    exit_rule="After N Days",
    target_rr=2.0,
    cap=40,
):
    """Replay conditions over history. Risk 2%/trade, next-open entry. Returns trades, equity, stats."""
    import datetime as _dt

    to_date = to_date or _dt.date.today().isoformat()
    capital = 100000.0
    equity = [{"date": from_date, "value": capital}]
    all_trades = []

    def _prep(sym):
        df = fetch_fn(sym, "2y", "1d")
        if df is None or df.empty or len(df) < 60:
            return None
        return (sym, compute_indicators(df, nifty_df))

    with ThreadPoolExecutor(max_workers=8) as ex:
        prepped = [p for p in ex.map(_prep, symbols[:cap]) if p]

    rows = []
    for sym, ind in prepped:
        for t in _bt_one(sym, conditions, ind, from_date, to_date, stop_pct, exit_days, exit_rule, target_rr):
            rows.append((t["exit_date"] or t["entry_date"], t))
    rows.sort(key=lambda x: x[0])
    for exit_date, t in rows:
        capital += capital * 0.02 / stop_pct * t["pnl_pct"]  # 2% risk → pnl in R × risk
        t["pnl_rs"] = round(capital * 0.02 / stop_pct * t["pnl_pct"] / 100 * 100, 0)  # display only
        all_trades.append(t)
        equity.append({"date": exit_date, "value": round(capital, 2)})

    wins = [t for t in all_trades if t["result"] == "WIN"]
    losses = [t for t in all_trades if t["result"] == "LOSS"]
    n = len(all_trades)
    wr = len(wins) / n * 100 if n else 0
    aw = float(np.mean([t["pnl_pct"] for t in wins])) if wins else 0
    al = abs(float(np.mean([t["pnl_pct"] for t in losses]))) if losses else 0
    rets = pd.Series([t["pnl_pct"] for t in all_trades])
    sh = round(float(rets.mean() / rets.std() * (252**0.5)), 2) if n > 1 and rets.std() > 0 else 0
    eq = pd.Series([e["value"] for e in equity])
    dd = round(float(((eq - eq.cummax()) / eq.cummax() * 100).min()), 2) if len(eq) > 1 else 0
    gw = sum(t["pnl_pct"] for t in wins)
    gl = abs(sum(t["pnl_pct"] for t in losses))
    stats = {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(wr, 1),
        "avg_win_pct": round(aw, 2),
        "avg_loss_pct": round(al, 2),
        "expectancy": round(wr / 100 * aw - (1 - wr / 100) * al, 2),
        "avg_rr": round(float(np.mean([t["rr"] for t in all_trades])), 2) if n else 0,
        "profit_factor": round(gw / gl, 2) if gl else (999.0 if gw else 0),
        "max_drawdown": dd,
        "sharpe": sh,
        "total_return": round((capital - 100000) / 100000 * 100, 2),
    }
    return all_trades, equity, stats


# ── multi-timeframe confluence ──────────────────────────────────────────────
def tf_trend(df: pd.DataFrame) -> bool | None:
    """Uptrend test for one timeframe: close > EMA20 > EMA50."""
    if df is None or df.empty or len(df) < 55 or "close" not in df:
        return None
    c = df["close"]
    e20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
    e50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
    return bool(float(c.iloc[-1]) > e20 > e50)


def mtf_confluence(daily_df: pd.DataFrame, m15_df: pd.DataFrame | None = None) -> dict:
    """Trend agreement across daily / weekly (resampled) / optional 15-min.
    Score counts uptrending TFs out of those measurable."""
    daily = tf_trend(daily_df)
    weekly = None
    try:
        wk = (
            daily_df[["open", "high", "low", "close"]]
            .resample("W")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna()
        )
        weekly = tf_trend(wk)
    except Exception:
        pass
    m15 = tf_trend(m15_df) if m15_df is not None else None
    tfs = {"daily": daily, "weekly": weekly, "m15": m15}
    measured = [v for v in tfs.values() if v is not None]
    score = sum(1 for v in measured if v)
    return {**tfs, "score": score, "of": len(measured)}

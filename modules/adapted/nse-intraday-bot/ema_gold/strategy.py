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
EMA trend-following strategy core (Gold) — indicators + entry/exit rules.
Shared by backtest.py and trader.py so both always use identical logic.
"""
import json
import os

import pandas as pd

_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config(path: str = None) -> dict:
    with open(path or os.path.join(_DIR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


# ── Indicators ──────────────────────────────────────────────────────


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    """Wilder's ATR."""
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int) -> pd.Series:
    """Wilder's ADX."""
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_w = tr.ewm(alpha=1.0 / n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr_w
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / n, adjust=False).mean() / atr_w
    denom = (plus_di + minus_di).replace(0, float("nan"))
    dx = (100 * (plus_di - minus_di).abs() / denom).astype(float)
    return dx.ewm(alpha=1.0 / n, adjust=False).mean().fillna(0.0)


def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Add all strategy columns. df needs open/high/low/close (+ datetime index)."""
    out = df.copy()
    out["ema_fast"] = ema(out["close"], cfg["ema_fast"])
    out["ema_slow"] = ema(out["close"], cfg["ema_slow"])
    out["ema_trend"] = ema(out["close"], cfg["ema_trend"])
    out["adx"] = adx(out, cfg["adx_period"])
    out["atr"] = atr(out, cfg["atr_period"])
    # crossovers on CLOSED bars
    fa, sl = out["ema_fast"], out["ema_slow"]
    out["cross_up"] = (fa > sl) & (fa.shift() <= sl.shift())
    out["cross_dn"] = (fa < sl) & (fa.shift() >= sl.shift())
    return out


# ── Rules ───────────────────────────────────────────────────────────


def entry_signal(row, cfg: dict):
    """Evaluate a CLOSED bar. Returns 'LONG' / 'SHORT' / None."""
    if row["adx"] <= cfg["adx_min"]:
        return None
    if row["cross_up"] and row["close"] > row["ema_trend"]:
        return "LONG"
    if row["cross_dn"] and row["close"] < row["ema_trend"]:
        return "SHORT"
    return None


def blocked_by_time(ts: pd.Timestamp, cfg: dict) -> str:
    """Entry-time filters. Returns reason string or '' if clear. ts is UTC."""
    if ts.hour in cfg.get("skip_hours_utc", []):
        return "low-liquidity hours"
    win = pd.Timedelta(minutes=cfg.get("news_window_min", 30))
    for ev in cfg.get("news_blackout_utc", []):
        try:
            evt = pd.Timestamp(ev)
        except Exception:
            continue
        if abs(ts - evt) <= win:
            return f"news blackout ({ev})"
    return ""


def initial_stops(direction: str, entry: float, atr_val: float, cfg: dict):
    """(stop_loss, take_profit) from ATR multiples."""
    sl_d = cfg["sl_atr_mult"] * atr_val
    tp_d = cfg["tp_atr_mult"] * atr_val
    if direction == "LONG":
        return entry - sl_d, entry + tp_d
    return entry + sl_d, entry - tp_d


def position_size(equity: float, risk_pct: float, sl_distance: float) -> float:
    """Units of the asset such that hitting SL loses risk_pct% of equity."""
    if sl_distance <= 0:
        return 0.0
    return (equity * risk_pct / 100.0) / sl_distance

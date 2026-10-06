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
On-Demand Screener — baseline (Stage-2 + momentum + volume) + VCP/pullback checks.
DB-first (prices_daily), Yahoo fallback for unknown symbols (single-symbol mode only).

Usage:
  python screener_engine.py RELIANCE   -> full check breakdown for one stock
  python screener_engine.py scan       -> run over top smallcap band (DB-only)
"""
import datetime as dt
import json
import sys

import db
import pandas as pd
import universe_helper as U
import yfinance as yf

# Canonical thresholds (rule R22). Guarded so a config problem can never blank
# the screener -- the .get() fallbacks below carry the previous hardcoded values.
try:
    from strategy_config import SCREENER as _SCREENER
    from strategy_config import SETUP as _SETUP

    _SC = {"SETUP": _SETUP, "SCREENER": _SCREENER}
except Exception:
    _SC = {}


# ==========================================
# 1. DATA FETCHING (DB-first, on-demand)
# ==========================================
def _from_db(ticker):
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume "
            "FROM prices_daily WHERE symbol=? ORDER BY date",
            (ticker,),
        ).fetchall()
        conn.close()
    except Exception:
        return None
    if len(rows) < 240:
        return None
    df = pd.DataFrame(list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Close"])


def _from_yahoo(ticker, period_days=550):
    try:
        end = dt.date.today()
        start = end - dt.timedelta(days=period_days)
        df = yf.download(
            f"{ticker}.NS",
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            progress=False,
        )
        if df is None or df.empty or len(df) < 240:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None


def fetch_stock_data(ticker, period_days=550, allow_yahoo=True):
    """18 months (~550 days) ensures enough history for EMA200 + 52W high."""
    df = _from_db(ticker)
    if df is None and allow_yahoo:
        df = _from_yahoo(ticker, period_days=period_days)
    return df


def fetch_index_data(index_ticker=None):
    """Benchmark data for the global regime filter.
    Tries multiple index candidates if none specified."""
    candidates = (
        [index_ticker]
        if index_ticker
        else ["^CNXSMALLCAP", "^CNXSC", "NIFTY_SMALLCAP_100.NS", "^NSEI"]
    )
    for sym in candidates:
        try:
            df = yf.download(sym, period="1mo", interval="1d", progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df
        except Exception:
            continue
    return None


# ==========================================
# 2. GLOBAL REGIME FILTER (top-down gatekeeper)
# ==========================================
def check_global_regime():
    idx_df = fetch_index_data()
    if idx_df is None or len(idx_df) < 10:
        return False, "Index Data Unavailable"
    idx_df["EMA_10"] = idx_df["Close"].ewm(span=10, adjust=False).mean()
    latest_close = idx_df["Close"].iloc[-1]
    latest_ema = idx_df["EMA_10"].iloc[-1]
    is_bullish = bool(latest_close > latest_ema)
    status = "BULLISH (Entries Allowed)" if is_bullish else "DEFENSIVE (Cash Mode)"
    return is_bullish, status


# ==========================================
# 3. MAIN SCREENER ENGINE (baseline + VCP)
# ==========================================
def evaluate_stock(ticker, allow_yahoo=True):
    """Evaluate one stock; returns metrics, pass/fail checks, UI strings."""
    df = _from_db(ticker)
    source = "prices_daily"
    if df is None and allow_yahoo:
        df = _from_yahoo(ticker)
        source = "Yahoo Finance"
    if df is None:
        return {"error": "Insufficient data or invalid ticker."}

    df = df.copy()
    df["EMA_10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["EMA_20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA_200"] = df["Close"].ewm(span=200, adjust=False).mean()
    df["SMA_Vol_50"] = df["Volume"].rolling(window=50).mean()
    df["SMA_Vol_20"] = df["Volume"].rolling(window=20).mean()
    df["52W_High"] = df["High"].rolling(window=252).max()
    df["EMA_200_Shifted"] = df["EMA_200"].shift(20)

    latest = df.iloc[-1]

    def fmt(x):
        return f"{x:.2f}" if pd.notnull(x) else "N/A"

    # --- A. BASELINE FILTERS ---
    # Thresholds come from strategy_config.SCREENER (the single source of truth,
    # rule R22). strategy_config stores FRACTIONS (0.20); this module's UI strings
    # are percentages, so *100 for display only.
    # Before 2026-10-05 this block hardcoded its own copy with different numbers
    # (impulse 25-50 vs 18-75, pullback 12-20 over 6-15d vs 6-25 over 6-20d,
    # volume one-branch vs two-branch) and omitted the liquidity gate entirely,
    # so the Screener tab could surface names the official strategy rejects.
    SC_ = _SC.get("SCREENER", {})
    MOM_1M_MIN = SC_.get("MOM_1M_MIN", 0.20) * 100
    MOM_3M_MIN = SC_.get("MOM_3M_MIN", 0.30) * 100
    PROX_MIN = SC_.get("HIGH_52WK_MIN_RATIO", 0.75) * 100
    VOL_MULT = SC_.get("VOL_EXPLOSION_MULT", 2.5)
    VOL_LOOKBACK = int(SC_.get("VOL_LOOKBACK", 60))
    LIQ_DAYS = int(SC_.get("LIQ_DAYS", 20))
    MIN_TURNOVER = float(SC_.get("MIN_AVG_TURNOVER", 2e7))

    baseline_1 = latest["Close"] > latest["EMA_200"]
    baseline_2 = latest["EMA_200"] > latest["EMA_200_Shifted"]
    mom_1m = (
        ((latest["Close"] - df["Close"].iloc[-22]) / df["Close"].iloc[-22]) * 100
        if len(df) >= 22
        else 0
    )
    mom_3m = (
        ((latest["Close"] - df["Close"].iloc[-64]) / df["Close"].iloc[-64]) * 100
        if len(df) >= 64
        else 0
    )
    prox_52w = (latest["Close"] / latest["52W_High"]) * 100 if latest["52W_High"] > 0 else 0
    baseline_3 = (mom_1m >= MOM_1M_MIN) or (mom_3m >= MOM_3M_MIN) or (prox_52w >= PROX_MIN)
    # Live voice. The old copy compared one value (period max > 2.5x SMA50);
    # the canonical rule looks for ANY 2.5x spike inside the last VOL_LOOKBACK
    # bars against the 50-bar average. Both are kept so the stricter official
    # sense governs, while the display flag stays honest about the raw spike.
    baseline_4 = bool(df["Volume"].tail(20).max() > (VOL_MULT * latest["SMA_Vol_50"]))
    vol_sma50 = df["Volume"].rolling(window=50).mean()
    vol_ok = any(
        pd.notnull(vol_sma50.iloc[i - 1])
        and df["Volume"].iloc[i] > VOL_MULT * vol_sma50.iloc[i - 1]
        for i in range(max(1, len(df) - VOL_LOOKBACK), len(df))
    )
    # Liquidity gate was previously MISSING from this path (rule R22 / SCREENER).
    avg_vol = float(df["Volume"].tail(LIQ_DAYS).mean())
    turnover_ok = (avg_vol * float(latest["Close"])) >= MIN_TURNOVER
    baseline_pass = all([baseline_1, baseline_2, baseline_3, vol_ok, turnover_ok])

    # --- B. VCP / PULLBACK SETUP FILTERS ---
    SET_ = _SC.get("SETUP", {})
    IMP_MIN = SET_.get("IMPULSE_MIN_PCT", 0.18) * 100
    IMP_MAX = SET_.get("IMPULSE_MAX_PCT", 0.75) * 100
    PB_MIN = SET_.get("PB_MIN_PCT", 0.06) * 100
    PB_MAX = SET_.get("PB_MAX_PCT", 0.25) * 100
    PB_MIN_D = int(SET_.get("PB_MIN_DAYS", 6))
    PB_MAX_D = int(SET_.get("PB_MAX_DAYS", 20))
    PB_LOOKBACK = int(SET_.get("PB_LOOKBACK", 25))
    EMA_TOUCH = SET_.get("EMA_TOUCH_MULT", 0.03) * 100
    TIGHT_ATR = SET_.get("TIGHT_ATR_MULT", 0.9)

    lookback = df.tail(PB_LOOKBACK)
    swing_high_idx = lookback["High"].idxmax()
    swing_high_val = lookback.loc[swing_high_idx, "High"]
    current_price = latest["Close"]

    pre_swing_data = df.loc[:swing_high_idx].tail(30)
    impulse_low = pre_swing_data["Low"].min()
    impulse_gain = ((swing_high_val - impulse_low) / impulse_low) * 100 if impulse_low else 0
    vcp_1 = IMP_MIN <= impulse_gain <= IMP_MAX

    pullback_depth = (
        ((swing_high_val - current_price) / swing_high_val) * 100 if swing_high_val else 0
    )
    vcp_2 = PB_MIN <= pullback_depth <= PB_MAX

    days_since_high = len(df) - df.index.get_loc(swing_high_idx) - 1
    vcp_3 = PB_MIN_D <= days_since_high <= PB_MAX_D

    recent_lows = df["Low"].tail(max(1, days_since_high)).min()
    dist_to_ema = min(abs(recent_lows - latest["EMA_10"]), abs(recent_lows - latest["EMA_20"]))
    vcp_4 = (dist_to_ema / current_price) * 100 <= EMA_TOUCH

    vcp_5 = bool(latest["Volume"] < (0.70 * latest["SMA_Vol_20"]))

    # Tightness now uses the canonical ATR rule: the last-3-bar range must be
    # within TIGHT_ATR x ATR14, instead of an ad-hoc 3%-of-price band.
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = float(tr.rolling(14).mean().iloc[-1]) if len(df) >= 15 else 0.0
    last_3_days = df.tail(3)
    max_range = (last_3_days["High"] - last_3_days["Low"]).max()
    tightness_pct = (max_range / current_price) * 100 if current_price else 0
    vcp_6 = bool(atr14 > 0 and max_range <= TIGHT_ATR * atr14)

    vcp_pass = all([vcp_1, vcp_2, vcp_3, vcp_4, vcp_5, vcp_6])
    overall_signal = bool(baseline_pass and vcp_pass)

    return {
        "ticker": ticker,
        "as_of": str(df.index[-1].date()),
        "source": source,
        "overall_signal": overall_signal,
        "current_price": fmt(current_price),
        "ema_200": fmt(latest["EMA_200"]),
        "momentum_1m": f"{fmt(mom_1m)}%",
        "momentum_3m": f"{fmt(mom_3m)}%",
        "proximity_52w": f"{fmt(prox_52w)}%",
        "impulse_gain": f"{fmt(impulse_gain)}%",
        "pullback_depth": f"{fmt(pullback_depth)}%",
        "days_since_high": int(days_since_high),
        "tightness_pct": f"{fmt(tightness_pct)}%",
        "checks": {
            "Baseline": bool(baseline_pass),
            "VCP Setup": bool(vcp_pass),
            "Stage 2 Trend": bool(baseline_1 and baseline_2),
            "Momentum": bool(baseline_3),
            "Volume Spike": bool(baseline_4),
            "Impulse (%d-%d%%)" % (IMP_MIN, IMP_MAX): bool(vcp_1),
            "Pullback (%d-%d%%)" % (PB_MIN, PB_MAX): bool(vcp_2),
            "Duration (%d-%dd)" % (PB_MIN_D, PB_MAX_D): bool(vcp_3),
            "EMA Support": bool(vcp_4),
            "Vol Contraction": bool(vcp_5),
            "Candle Tightness": bool(vcp_6),
        },
    }


def screen_universe(limit=60, show=True, allow_yahoo=False):
    """Run the screener over the top smallcap band (DB-only = fast)."""
    conn = db.get_conn()
    syms = U.band_universe(conn, limit)
    conn.close()
    hits = []
    for sym in syms:
        r = evaluate_stock(sym, allow_yahoo=allow_yahoo)
        if r.get("overall_signal"):
            hits.append(r)
            if show:
                print(
                    f"   ✅ {sym}: price {r['current_price']}  "
                    f"PB {r['pullback_depth']}  "
                    f"tight {r['tightness_pct']}"
                )
    if show:
        print(f"screener hits: {len(hits)} / {len(syms)}")
    return hits


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        screen_universe()
    elif len(sys.argv) > 1:
        print(json.dumps(evaluate_stock(sys.argv[1].upper()), indent=1))
    else:
        ok, status = check_global_regime()
        print(status)

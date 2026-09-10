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
import json
import sys

import db
import numpy as np
import pandas as pd
import yfinance as yf


# ==========================================
# 1. DATA FETCHING (DB-first, on-demand)
# ==========================================
def _from_db(ticker):
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date", (ticker,)
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


def _from_yahoo(ticker, period="18mo"):
    try:
        df = yf.download(f"{ticker}.NS", period=period, interval="1d", progress=False)
        if df is None or df.empty or len(df) < 240:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None


def fetch_stock_data(ticker, period="18mo", allow_yahoo=True):
    """18 months ensures enough history for EMA200 + 52W high."""
    df = _from_db(ticker)
    if df is None and allow_yahoo:
        df = _from_yahoo(ticker, period)
    return df


def fetch_index_data(index_ticker="^NSESMALLCAP"):
    """Benchmark data for the global regime filter."""
    try:
        df = yf.download(index_ticker, period="1mo", interval="1d", progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
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
    df = fetch_stock_data(ticker, allow_yahoo=allow_yahoo)
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
    baseline_1 = latest["Close"] > latest["EMA_200"]
    baseline_2 = latest["EMA_200"] > latest["EMA_200_Shifted"]
    mom_1m = ((latest["Close"] - df["Close"].iloc[-22]) / df["Close"].iloc[-22]) * 100 if len(df) >= 22 else 0
    mom_3m = ((latest["Close"] - df["Close"].iloc[-64]) / df["Close"].iloc[-64]) * 100 if len(df) >= 64 else 0
    prox_52w = (latest["Close"] / latest["52W_High"]) * 100 if latest["52W_High"] > 0 else 0
    baseline_3 = (mom_1m >= 20) or (mom_3m >= 30) or (prox_52w >= 75)
    recent_vol_max = df["Volume"].tail(20).max()
    baseline_4 = bool(recent_vol_max > (2.5 * latest["SMA_Vol_50"]))
    baseline_pass = all([baseline_1, baseline_2, baseline_3, baseline_4])

    # --- B. VCP / PULLBACK SETUP FILTERS ---
    lookback = df.tail(60)
    swing_high_idx = lookback["High"].idxmax()
    swing_high_val = lookback.loc[swing_high_idx, "High"]
    current_price = latest["Close"]

    pre_swing_data = df.loc[:swing_high_idx].tail(30)
    impulse_low = pre_swing_data["Low"].min()
    impulse_gain = ((swing_high_val - impulse_low) / impulse_low) * 100 if impulse_low else 0
    vcp_1 = 25 <= impulse_gain <= 50

    pullback_depth = ((swing_high_val - current_price) / swing_high_val) * 100 if swing_high_val else 0
    vcp_2 = 12 <= pullback_depth <= 20

    days_since_high = len(df) - df.index.get_loc(swing_high_idx) - 1
    vcp_3 = 6 <= days_since_high <= 15

    recent_lows = df["Low"].tail(max(1, days_since_high)).min()
    dist_to_ema = min(abs(recent_lows - latest["EMA_10"]), abs(recent_lows - latest["EMA_20"]))
    vcp_4 = (dist_to_ema / current_price) * 100 <= 2.0

    vcp_5 = latest["Volume"] < (0.70 * latest["SMA_Vol_20"])

    last_3_days = df.tail(3)
    max_range = (last_3_days["High"] - last_3_days["Low"]).max()
    tightness_pct = (max_range / current_price) * 100
    vcp_6 = tightness_pct <= 3.0

    vcp_pass = all([vcp_1, vcp_2, vcp_3, vcp_4, vcp_5, vcp_6])
    overall_signal = bool(baseline_pass and vcp_pass)

    return {
        "ticker": ticker,
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
            "Impulse (+25-50%)": bool(vcp_1),
            "Pullback (12-20%)": bool(vcp_2),
            "Duration (6-15d)": bool(vcp_3),
            "EMA Support": bool(vcp_4),
            "Vol Contraction": bool(vcp_5),
            "Candle Tightness": bool(vcp_6),
        },
    }


def screen_universe(limit=60, show=True, allow_yahoo=False):
    """Run the screener over the top smallcap band (DB-only = fast)."""
    conn = db.get_conn()
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM universe_broad "
            "WHERE mcap_cr BETWEEN 1000 AND 8000 "
            "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
            "ORDER BY mcap_cr DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]
    conn.close()
    hits = []
    for sym in syms:
        r = evaluate_stock(sym, allow_yahoo=allow_yahoo)
        if r.get("overall_signal"):
            hits.append(r)
            if show:
                print(f"   ✅ {sym}: price {r['current_price']}  PB {r['pullback_depth']}  tight {r['tightness_pct']}")
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

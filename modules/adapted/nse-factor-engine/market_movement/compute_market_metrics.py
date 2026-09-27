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
Market Movement -- Metrics Computation
Separate from main NSE Factor Engine pipeline (Stage 8 scope).

Reads   : data/index_prices.parquet  (single source of truth, repo root)
Output  : market_movement/data/market_movement_metrics.parquet
          market_movement/data/market_movement_metrics_{RUN_DATE}.parquet

── Date convention (locked 2026-06-30, METHODOLOGY.md) ──
RUN_DATE   = IST calendar date this script executed -> filename
as_of_date = T, latest trading day reflected in the data -> column, computed from data

── Scope (locked with user, Stage 8) ──
1. Index metrics -- all 9 market_movement tickers:
   - weekly close, 30W SMA slope, 20W support/resistance -> Weinstein 5-stage
     (Stage 1 Accumulation, Stage 2 Advancing, Stage 3 Distribution,
     Stage 4 Transition Breakdown, Stage 4 Declining -- volume-free,
     locked with user 2026-07-06). Computed for all tickers except ^INDIAVIX.
   - trailing 21D % return
   - 52-week high proximity
   - drawdown from rolling peak
   - Wilder RSI-14 (computed for all tickers including ^INDIAVIX)
2. VIX standalone (^INDIAVIX) -- 5-tier, 21D % change
3. 2x2 combo grid -- VIX (collapsed 3-tier) x Market Direction (Nifty 50 only, 3-tier)
   - Market direction threshold: +/-1 sigma on Nifty 50 21D returns = +/-3.58%
   - VIX drives combo per India VIX being Nifty-50-options-based
   - 4 of 9 combo cells have narrative labels; 5 ship as raw tags (locked with user)

Reads only the 9 market_movement tickers from the shared parquet;
the 3 liquidity_risk_index-only tickers are ignored here.
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# ── Repo-root guard ──────────────────
if not Path("signals").is_dir():
    sys.exit(
        "ERROR: 'signals/' not found in current directory.\nRun from repo root: cd /home/ec2-user/nse-factor-engine/"
    )

# ── Config ───────────────────────────
END_DATE = date.today()
RUN_DATE = END_DATE.strftime("%d%m%Y")

INPUT_PATH = Path("data/index_prices.parquet")  # single source of truth
DATA_DIR = Path("market_movement/data")
ROLLING_OUT = DATA_DIR / "market_movement_metrics.parquet"
DATED_OUT = DATA_DIR / f"market_movement_metrics_{RUN_DATE}.parquet"

RET_WINDOW_DAYS = 21
WEEK_MA_WINDOW = 30
SMA_SHORT = 150
SMA_LONG = 200
LOOKBACK_52W_DAYS = 252
RSI_PERIOD = 14

VIX_SYMBOL = "^INDIAVIX"
PRIMARY_MARKET = "^NSEI"

# market_movement consumes these 9 tickers only
MM_SYMBOLS = {
    "^NSEI",
    "^CRSLDX",
    "^NSEMDCP50",
    "NIFTYMIDCAP150.NS",
    "SML100CASE.NS",
    "^NSEBANK",
    "^CNXIT",
    "^CNXPHARMA",
    "^INDIAVIX",
}

VIX_STABLE_BAND = 7.0
VIX_CONFIRMED_BAND = 15.0
MARKET_DIRECTION_THRESHOLD_PCT = 3.58


# ── Helpers ───────────────────────────


def _weekly_close(df_sym):
    s = df_sym.set_index("date")["close"]
    return s.resample("W-FRI").last().dropna()


def _wilder_rsi(close, n=RSI_PERIOD):
    close = close.dropna().reset_index(drop=True)
    if len(close) < n + 1:
        return np.nan
    delta = close.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.iloc[:n].mean()
    avg_loss = loss.iloc[:n].mean()
    for i in range(n, len(gain)):
        avg_gain = (avg_gain * (n - 1) + gain.iloc[i]) / n
        avg_loss = (avg_loss * (n - 1) + loss.iloc[i]) / n
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 4)


def compute_index_metrics(df_sym):
    df_sym = df_sym.sort_values("date").reset_index(drop=True)
    close = df_sym["close"]
    symbol = df_sym["symbol"].iloc[0]
    latest_close = close.iloc[-1]
    latest_date = df_sym["date"].iloc[-1]
    is_vix = symbol == VIX_SYMBOL

    if is_vix:
        weinstein_state = "NOT_APPLICABLE"
        close_above_30w_ma = np.nan
        ma_30w_slope_positive = np.nan
    else:
        weekly = _weekly_close(df_sym)
        sma_30w = weekly.rolling(WEEK_MA_WINDOW, min_periods=WEEK_MA_WINDOW).mean()
        slope_30w = ((sma_30w - sma_30w.shift(3)) / sma_30w.shift(3)) * 100
        resistance_20w = weekly.shift(1).rolling(20, min_periods=20).max()
        support_20w = weekly.shift(1).rolling(20, min_periods=20).min()
        above_sma = weekly > sma_30w
        whipsaw_4w = above_sma.rolling(4, min_periods=4).apply(lambda x: bool(x.any() and not x.all()), raw=True)

        v = {
            "close": weekly.iloc[-1] if len(weekly) >= 1 else np.nan,
            "sma_30w": sma_30w.iloc[-1] if len(sma_30w.dropna()) >= 1 else np.nan,
            "slope_30w": slope_30w.iloc[-1] if len(slope_30w.dropna()) >= 1 else np.nan,
            "resistance": resistance_20w.iloc[-1] if len(resistance_20w.dropna()) >= 1 else np.nan,
            "support": support_20w.iloc[-1] if len(support_20w.dropna()) >= 1 else np.nan,
            "whipsaw": whipsaw_4w.iloc[-1] if len(whipsaw_4w.dropna()) >= 1 else np.nan,
        }

        if any(pd.isna(v[k]) for k in ("close", "sma_30w", "slope_30w", "resistance", "support")):
            weinstein_state = "INSUFFICIENT_DATA"
        elif v["support"] <= v["close"] <= v["resistance"] and -1.0 <= v["slope_30w"] <= 1.0:
            weinstein_state = "STAGE_1_ACCUMULATION"
        elif v["close"] > v["sma_30w"] and v["slope_30w"] > 1.0:
            weinstein_state = "STAGE_2_ADVANCING"
        elif pd.notna(v["whipsaw"]) and bool(v["whipsaw"]) and -1.0 <= v["slope_30w"] <= 1.0:
            weinstein_state = "STAGE_3_DISTRIBUTION"
        elif v["close"] < v["support"] and v["slope_30w"] < -1.0:
            weinstein_state = "STAGE_4_TRANSITION_BREAKDOWN"
        elif v["close"] < v["sma_30w"] and v["slope_30w"] < -1.0:
            weinstein_state = "STAGE_4_DECLINING"
        else:
            weinstein_state = "TRANSITION_ZONE"

        close_above_30w_ma = bool(v["close"] > v["sma_30w"]) if pd.notna(v["sma_30w"]) else np.nan
        ma_30w_slope_positive = bool(v["slope_30w"] > 0) if pd.notna(v["slope_30w"]) else np.nan

    sma_150 = close.rolling(SMA_SHORT, min_periods=SMA_SHORT).mean()
    sma_200 = close.rolling(SMA_LONG, min_periods=SMA_LONG).mean()
    sma_150_above_200 = np.nan
    if pd.notna(sma_150.iloc[-1]) and pd.notna(sma_200.iloc[-1]):
        sma_150_above_200 = bool(sma_150.iloc[-1] > sma_200.iloc[-1])

    ret_21d = np.nan
    if len(close) > RET_WINDOW_DAYS:
        past_close = close.iloc[-(RET_WINDOW_DAYS + 1)]
        if pd.notna(past_close) and past_close != 0:
            ret_21d = round((latest_close / past_close - 1) * 100, 4)

    window_252 = close.tail(LOOKBACK_52W_DAYS)
    high_52w = window_252.max()
    proximity_52w_high = round(latest_close / high_52w, 4) if pd.notna(high_52w) and high_52w != 0 else np.nan

    cummax = close.cummax()
    drawdown_series = (close - cummax) / cummax
    current_drawdown = round(drawdown_series.iloc[-1] * 100, 4)

    rsi_14 = _wilder_rsi(close, RSI_PERIOD)

    return {
        "symbol": symbol,
        "as_of_date": latest_date,
        "close": round(latest_close, 4),
        "close_above_30w_ma": close_above_30w_ma,
        "ma_30w_slope_positive": ma_30w_slope_positive,
        "sma_150_above_200": sma_150_above_200,
        "weinstein_state": weinstein_state,
        "ret_21d_pct": ret_21d,
        "proximity_52w_high": proximity_52w_high,
        "current_drawdown_pct": current_drawdown,
        "rsi_14": rsi_14,
    }


def classify_vix_5tier(ret_21d_pct):
    if pd.isna(ret_21d_pct):
        return "INSUFFICIENT_DATA"
    if ret_21d_pct > VIX_CONFIRMED_BAND:
        return "GOING_UP_CONFIRMED"
    if ret_21d_pct > VIX_STABLE_BAND:
        return "DEVELOPING_UPTREND"
    if ret_21d_pct < -VIX_CONFIRMED_BAND:
        return "GOING_DOWN_CONFIRMED"
    if ret_21d_pct < -VIX_STABLE_BAND:
        return "DEVELOPING_DOWNTREND"
    return "STABLE"


def collapse_vix_to_3tier(vix_5tier):
    if vix_5tier in ("DEVELOPING_UPTREND", "GOING_UP_CONFIRMED"):
        return "VIX_UP"
    if vix_5tier in ("DEVELOPING_DOWNTREND", "GOING_DOWN_CONFIRMED"):
        return "VIX_DOWN"
    if vix_5tier == "STABLE":
        return "VIX_STABLE"
    return "INSUFFICIENT_DATA"


def classify_market_direction(ret_21d_pct):
    if pd.isna(ret_21d_pct):
        return "INSUFFICIENT_DATA"
    if ret_21d_pct > MARKET_DIRECTION_THRESHOLD_PCT:
        return "MARKET_UP"
    if ret_21d_pct < -MARKET_DIRECTION_THRESHOLD_PCT:
        return "MARKET_DOWN"
    return "MARKET_STABLE"


COMBO_LABELS = {
    ("VIX_UP", "MARKET_UP"): "FOMO_PRE_EVENT_ANXIETY",
    ("VIX_UP", "MARKET_DOWN"): "PANIC_REAL_CRASH",
    ("VIX_DOWN", "MARKET_UP"): "CONFIDENCE_HEALTHY_RALLY",
    ("VIX_STABLE", "MARKET_STABLE"): "COMPLACENCY_BOREDOM",
}


def classify_combo(vix_3tier, market_3tier):
    if vix_3tier == "INSUFFICIENT_DATA" or market_3tier == "INSUFFICIENT_DATA":
        return "INSUFFICIENT_DATA"
    return COMBO_LABELS.get((vix_3tier, market_3tier), f"{vix_3tier}_{market_3tier}")


# ── Main ──────────────────────────────
print("=" * 60)
print("Market Movement -- Metrics Computation")
print(f"Run Date : {END_DATE}")
print("=" * 60)

if not INPUT_PATH.exists():
    sys.exit(f"ERROR: {INPUT_PATH} not found. Run data/fetch_index_data.py first.")

prices = pd.read_parquet(INPUT_PATH)
prices["date"] = pd.to_datetime(prices["date"])

# Filter to market_movement tickers only
prices = prices[prices["symbol"].isin(MM_SYMBOLS)]
print("\n[1/3] Loaded {} rows | {} market_movement tickers".format(prices.shape[0], prices["symbol"].nunique()))

print("\n[2/3] Computing index metrics...")
rows = []
for symbol, grp in prices.groupby("symbol"):
    m = compute_index_metrics(grp)
    rows.append(m)
    print(
        "  {:25s} state={:30s} ret_21d={:+7.2f}%  rsi_14={:.1f}".format(
            symbol,
            m["weinstein_state"],
            m["ret_21d_pct"] if pd.notna(m["ret_21d_pct"]) else float("nan"),
            m["rsi_14"] if pd.notna(m["rsi_14"]) else float("nan"),
        )
    )

metrics_df = pd.DataFrame(rows)

vix_row = metrics_df[metrics_df["symbol"] == VIX_SYMBOL]
if vix_row.empty:
    sys.exit(f"ERROR: {VIX_SYMBOL} not found -- cannot compute VIX/combo.")
vix_ret_21d = vix_row["ret_21d_pct"].iloc[0]
vix_5tier = classify_vix_5tier(vix_ret_21d)
vix_3tier = collapse_vix_to_3tier(vix_5tier)

market_row = metrics_df[metrics_df["symbol"] == PRIMARY_MARKET]
if market_row.empty:
    sys.exit(f"ERROR: {PRIMARY_MARKET} not found -- cannot compute combo.")
market_ret_21d = market_row["ret_21d_pct"].iloc[0]
market_3tier = classify_market_direction(market_ret_21d)
combo_state = classify_combo(vix_3tier, market_3tier)

print("\n[3/3] VIX & combo...")
print(
    "  VIX  21D ret={:+.2f}%  5-tier={}  3-tier={}".format(
        vix_ret_21d if pd.notna(vix_ret_21d) else float("nan"), vix_5tier, vix_3tier
    )
)
print(
    "  NSEI 21D ret={:+.2f}%  3-tier={}".format(
        market_ret_21d if pd.notna(market_ret_21d) else float("nan"), market_3tier
    )
)
print(f"  Combo : {combo_state}")

as_of_date = metrics_df["as_of_date"].max()
metrics_df["vix_ret_21d_pct"] = vix_ret_21d
metrics_df["vix_5tier"] = vix_5tier
metrics_df["vix_3tier"] = vix_3tier
metrics_df["market_ret_21d_pct"] = market_ret_21d
metrics_df["market_3tier"] = market_3tier
metrics_df["combo_state"] = combo_state
metrics_df["as_of_date"] = as_of_date
metrics_df["run_date"] = END_DATE

DATA_DIR.mkdir(parents=True, exist_ok=True)
metrics_df.to_parquet(ROLLING_OUT, index=False)
metrics_df.to_parquet(DATED_OUT, index=False)

print("\n" + "=" * 60)
print("SUMMARY")
print(f"  {ROLLING_OUT.name} : {metrics_df.shape[0]} rows")
print(f"  {DATED_OUT.name} : {metrics_df.shape[0]} rows")
print(f"  as_of_date : {as_of_date}")
print(f"  Combo      : {combo_state}")
print("=" * 60)

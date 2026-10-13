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
Market Breadth Metrics
Run from repo root: python3 market_movement/compute_breadth_metrics.py

Reads  : data/prices.parquet
         universe/universe_{DDMMYYYY}.parquet  (latest by parsed date)
Writes : market_movement/data/breadth_metrics.parquet       (rolling)
         market_movement/data/breadth_metrics_{DDMMYYYY}.parquet (dated snapshot)

Indicators (all on in_universe=True subset only):
  1. Advance-Decline Line     -- cumulative (advancing - declining)
  2. Advance-Decline Ratio    -- advancing / declining per day
  3. New Highs / New Lows     -- 52-week window (252 trading days)
  4. McClellan Oscillator     -- EMA(19, net_adv) - EMA(39, net_adv)
  5. TRIN (Arms Index)        -- (adv_count/dec_count) / (adv_vol/dec_vol)
  6. % Above 50-day SMA       -- fraction of universe above own 50-day SMA
  7. % Above 200-day SMA      -- fraction of universe above own 200-day SMA

Advancing : close(T) > close(T-1)
Declining : close(T) < close(T-1)
Unchanged : excluded from both counts (standard convention)

Date convention:
  RUN_DATE   = IST calendar date this script ran  -> filename suffix
  as_of_date = latest trading date in prices data -> column inside file
"""

import glob
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# -- Repo-root guard ----------------------------------------------------------
if not Path("signals").is_dir():
    sys.exit(
        "ERROR: 'signals/' not found. Run from repo root: cd /home/ec2-user/nse-factor-engine/"
    )

# -- Config -------------------------------------------------------------------
RUN_DATE = date.today()
RUN_DATE_STR = RUN_DATE.strftime("%d%m%Y")

PRICES_PATH = Path("data/prices.parquet")
UNIVERSE_DIR = Path("universe")
DATA_DIR = Path("market_movement/data")
ROLLING_OUT = DATA_DIR / "breadth_metrics.parquet"
DATED_OUT = DATA_DIR / f"breadth_metrics_{RUN_DATE_STR}.parquet"

SMA_SHORT = 50
SMA_LONG = 200
NH_NL_WINDOW = 252  # 52-week in trading days
EMA_SHORT = 19  # McClellan fast EMA
EMA_LONG = 39  # McClellan slow EMA

# Interpretation bands (calibrated on 346 days of NSE 495-stock universe, Aug 2026)
# McClellan: US convention (±100) does not apply — NSE 495-stock range is [-44, +63]
# Using ±40 (~2 std devs) as overbought/oversold threshold
MCCLELLAN_OB = 40
MCCLELLAN_OS = -40
# TRIN: NSE mean is 0.85, habitually below 1.0. Revised bands reflect actual distribution.
TRIN_BEARISH = 1.50
TRIN_BULLISH = 0.60
ADR_BULL_ZONE = 1.50
ADR_BEAR_ZONE = 0.67

print("=" * 60)
print("Market Breadth -- Metrics Computation")
print(f"Run date : {RUN_DATE}")
print("=" * 60)

# -- Load prices --------------------------------------------------------------
if not PRICES_PATH.exists():
    sys.exit(f"ERROR: {PRICES_PATH} not found. Run universe/run_universe.py first.")

prices = pd.read_parquet(PRICES_PATH)
prices["date"] = pd.to_datetime(prices["date"])
as_of_date = prices["date"].max()
print(
    f"\n[1/4] Prices: {len(prices):,} rows | "
    f"{prices['symbol'].nunique()} symbols | "
    f"{prices['date'].min().date()} -> {as_of_date.date()}"
)


# -- Load latest universe (parsed-date sort, not alphabetical) ----------------
def _parse_universe_date(path):
    stem = Path(path).stem
    return datetime.strptime(stem.replace("universe_", ""), "%d%m%Y")


universe_files = sorted(
    glob.glob(str(UNIVERSE_DIR / "universe_*.parquet")), key=_parse_universe_date
)
if not universe_files:
    sys.exit(f"ERROR: No universe_*.parquet found in {UNIVERSE_DIR}/")

latest_universe_path = universe_files[-1]
universe = pd.read_parquet(latest_universe_path)
in_universe_symbols = set(universe[universe["in_universe"]]["symbol"])
print(
    f"[1/4] Universe: {Path(latest_universe_path).name} | "
    f"{len(in_universe_symbols)} in_universe=True symbols"
)

# -- Filter to in-universe stocks only ----------------------------------------
prices = prices[prices["symbol"].isin(in_universe_symbols)].copy()
prices = prices.sort_values(["symbol", "date"]).reset_index(drop=True)
print(f"[1/4] After filter: {len(prices):,} rows | {prices['symbol'].nunique()} symbols")

# -- Per-stock signals --------------------------------------------------------
print("\n[2/4] Computing per-stock daily signals...")


def compute_stock_signals(grp):
    grp = grp.sort_values("date").copy()
    grp["prev_close"] = grp["close"].shift(1)

    grp["advancing"] = (grp["close"] > grp["prev_close"]).astype(int)
    grp["declining"] = (grp["close"] < grp["prev_close"]).astype(int)

    grp["adv_volume"] = grp["volume"] * grp["advancing"]
    grp["dec_volume"] = grp["volume"] * grp["declining"]

    # 52-week high/low: compare today's close to max/min of prior 252 closes
    roll_high = grp["close"].shift(1).rolling(NH_NL_WINDOW, min_periods=NH_NL_WINDOW).max()
    roll_low = grp["close"].shift(1).rolling(NH_NL_WINDOW, min_periods=NH_NL_WINDOW).min()
    grp["new_high"] = (grp["close"] >= roll_high).astype(int)
    grp["new_low"] = (grp["close"] <= roll_low).astype(int)

    # SMA participation
    sma_50 = grp["close"].rolling(SMA_SHORT, min_periods=SMA_SHORT).mean()
    sma_200 = grp["close"].rolling(SMA_LONG, min_periods=SMA_LONG).mean()
    grp["above_50sma"] = np.where(sma_50.isna(), np.nan, (grp["close"] > sma_50).astype(float))
    grp["above_200sma"] = np.where(sma_200.isna(), np.nan, (grp["close"] > sma_200).astype(float))

    return grp[
        [
            "date",
            "advancing",
            "declining",
            "adv_volume",
            "dec_volume",
            "new_high",
            "new_low",
            "above_50sma",
            "above_200sma",
        ]
    ]


stock_signals = prices.groupby("symbol", group_keys=False).apply(
    compute_stock_signals, include_groups=False
)
stock_signals = stock_signals.reset_index(level=0)  # brings symbol back from index
print(f"[2/4] Stock signals: {len(stock_signals):,} rows")

# -- Aggregate to daily breadth -----------------------------------------------
print("\n[3/4] Aggregating to daily breadth indicators...")

daily = (
    stock_signals.groupby("date")
    .agg(
        adv_count=("advancing", "sum"),
        dec_count=("declining", "sum"),
        adv_volume=("adv_volume", "sum"),
        dec_volume=("dec_volume", "sum"),
        new_highs=("new_high", "sum"),
        new_lows=("new_low", "sum"),
        pct_above_50sma=("above_50sma", "mean"),
        pct_above_200sma=("above_200sma", "mean"),
    )
    .reset_index()
    .sort_values("date")
)

# Indicator 1: A/D Line
daily["net_advances"] = daily["adv_count"] - daily["dec_count"]
daily["ad_line"] = daily["net_advances"].cumsum()

# Indicator 2: ADR
daily["adr"] = np.where(
    daily["dec_count"] > 0, (daily["adv_count"] / daily["dec_count"]).round(4), np.nan
)

# Indicator 4: McClellan Oscillator
daily["ema_19"] = daily["net_advances"].ewm(span=EMA_SHORT, adjust=False).mean().round(4)
daily["ema_39"] = daily["net_advances"].ewm(span=EMA_LONG, adjust=False).mean().round(4)
daily["mcclellan"] = (daily["ema_19"] - daily["ema_39"]).round(4)

# Indicator 5: TRIN
daily["trin"] = np.where(
    (daily["adv_count"] > 0)
    & (daily["dec_count"] > 0)
    & (daily["adv_volume"] > 0)
    & (daily["dec_volume"] > 0),
    ((daily["adv_count"] / daily["dec_count"]) / (daily["adv_volume"] / daily["dec_volume"])).round(
        4
    ),
    np.nan,
)

# Scale SMA participation to 0-100
daily["pct_above_50sma"] = (daily["pct_above_50sma"] * 100).round(2)
daily["pct_above_200sma"] = (daily["pct_above_200sma"] * 100).round(2)


# -- Signal labels ------------------------------------------------------------
def _mcclellan_signal(v):
    if pd.isna(v):
        return "INSUFFICIENT_DATA"
    if v > MCCLELLAN_OB:
        return "OVERBOUGHT"
    if v < MCCLELLAN_OS:
        return "OVERSOLD"
    if v > 0:
        return "BULLISH"
    if v < 0:
        return "BEARISH"
    return "NEUTRAL"


def _trin_signal(v):
    if pd.isna(v):
        return "INSUFFICIENT_DATA"
    if v > TRIN_BEARISH:
        return "BEARISH"
    if v < TRIN_BULLISH:
        return "BULLISH"
    return "NEUTRAL"


def _adr_signal(v):
    if pd.isna(v):
        return "INSUFFICIENT_DATA"
    if v > ADR_BULL_ZONE:
        return "STRONG_BREADTH"
    if v < ADR_BEAR_ZONE:
        return "WEAK_BREADTH"
    return "NEUTRAL"


daily["mcclellan_signal"] = daily["mcclellan"].apply(_mcclellan_signal)
daily["trin_signal"] = daily["trin"].apply(_trin_signal)
daily["adr_signal"] = daily["adr"].apply(_adr_signal)


# -- Composite breadth score --------------------------------------------------
def _composite_score(row):
    score = 0
    if pd.notna(row["ad_line"]):
        score += 1 if row["ad_line"] > 0 else -1
    if row["adr_signal"] == "STRONG_BREADTH":
        score += 1
    elif row["adr_signal"] == "WEAK_BREADTH":
        score -= 1
    if pd.notna(row["new_highs"]) and pd.notna(row["new_lows"]):
        if row["new_highs"] > row["new_lows"]:
            score += 1
        elif row["new_lows"] > row["new_highs"]:
            score -= 1
    if pd.notna(row["mcclellan"]):
        score += 1 if row["mcclellan"] > 0 else -1
    if row["trin_signal"] == "BULLISH":
        score += 1
    elif row["trin_signal"] == "BEARISH":
        score -= 1
    if pd.notna(row["pct_above_50sma"]):
        if row["pct_above_50sma"] > 60:
            score += 1
        elif row["pct_above_50sma"] < 40:
            score -= 1
    if pd.notna(row["pct_above_200sma"]):
        if row["pct_above_200sma"] > 60:
            score += 1
        elif row["pct_above_200sma"] < 40:
            score -= 1
    return score


def _breadth_label(score):
    if score >= 4:
        return "BROAD_BULL"
    if score >= 1:
        return "NARROW_BULL"
    if score == 0:
        return "MIXED"
    if score >= -3:
        return "NARROW_BEAR"
    return "BROAD_BEAR"


def _breadth_narrative(row):
    row["breadth_score"]
    label = row["breadth_label"]
    mc = row["mcclellan"]
    trin = row["trin"]
    p50 = row["pct_above_50sma"]
    ad = row["ad_line"]
    nh = row["new_highs"]
    nl = row["new_lows"]

    base = {
        "BROAD_BULL": "Wide participation — majority of stocks advancing on healthy breadth.",
        "NARROW_BULL": "Positive bias but leadership is thin — rally not broadly confirmed.",
        "MIXED": "No clear directional edge — bulls and bears evenly matched.",
        "NARROW_BEAR": "Breadth deteriorating — more stocks declining than advancing.",
        "BROAD_BEAR": "Wide distribution — majority of stocks under pressure.",
    }.get(label, "")

    flags = []
    if pd.notna(mc) and pd.notna(trin):
        if mc > 0 and trin >= 0.60:
            flags.append("breadth momentum positive but volume favouring decliners")
        elif mc <= 0 and trin < 0.60:
            flags.append(
                "breadth momentum negative but advancing stocks absorbing heavy volume — narrow concentrated buying"
            )
    if pd.notna(p50) and pd.notna(ad):
        if ad < 0 and p50 > 60:
            flags.append(
                "A/D Line negative but majority above 50d SMA — recent recovery not yet in cumulative breadth"
            )
        elif ad > 0 and p50 < 40:
            flags.append(
                "A/D Line positive but few stocks above 50d SMA — cumulative breadth masking short-term weakness"
            )
    if pd.notna(nh) and pd.notna(nl):
        if label in ("NARROW_BEAR", "BROAD_BEAR") and nh > nl:
            flags.append("new highs still outnumber new lows — damage not yet at extremes")
        elif label in ("NARROW_BULL", "BROAD_BULL") and nl > nh:
            flags.append(
                "new lows outnumber new highs despite positive bias — watch for breadth rollover"
            )

    if flags:
        return base + " " + "; ".join(flags).capitalize() + "."
    return base


daily["breadth_score"] = daily.apply(_composite_score, axis=1)
daily["breadth_label"] = daily["breadth_score"].apply(_breadth_label)
daily["breadth_narrative"] = daily.apply(_breadth_narrative, axis=1)

# -- Metadata + column order --------------------------------------------------
daily["as_of_date"] = as_of_date
daily["run_date"] = RUN_DATE
daily["universe_size"] = len(in_universe_symbols)

col_order = [
    "date",
    "as_of_date",
    "run_date",
    "universe_size",
    "adv_count",
    "dec_count",
    "net_advances",
    "ad_line",
    "adr",
    "adr_signal",
    "new_highs",
    "new_lows",
    "ema_19",
    "ema_39",
    "mcclellan",
    "mcclellan_signal",
    "adv_volume",
    "dec_volume",
    "trin",
    "trin_signal",
    "pct_above_50sma",
    "pct_above_200sma",
    "breadth_score",
    "breadth_label",
    "breadth_narrative",
]
daily = daily[col_order]

# -- Write --------------------------------------------------------------------
DATA_DIR.mkdir(parents=True, exist_ok=True)
daily.to_parquet(ROLLING_OUT, index=False)
daily.to_parquet(DATED_OUT, index=False)

# -- Summary ------------------------------------------------------------------
latest = daily.iloc[-1]
p200 = latest["pct_above_200sma"]
print(f"\n[4/4] Written: {ROLLING_OUT}  ({len(daily)} rows)")
print()
print("=" * 60)
print("BREADTH SUMMARY (latest trading day)")
print("=" * 60)
print(f"  as_of_date       : {latest['date'].date()}")
print(f"  Universe size    : {latest['universe_size']}")
print(f"  Advancing        : {int(latest['adv_count'])}")
print(f"  Declining        : {int(latest['dec_count'])}")
print(f"  Net advances     : {int(latest['net_advances'])}")
print(f"  A/D Line         : {latest['ad_line']:.0f}")
print(f"  ADR              : {latest['adr']:.3f}  [{latest['adr_signal']}]")
print(f"  New Highs        : {int(latest['new_highs'])}")
print(f"  New Lows         : {int(latest['new_lows'])}")
print(f"  McClellan        : {latest['mcclellan']:.2f}  [{latest['mcclellan_signal']}]")
print(f"  TRIN             : {latest['trin']:.3f}  [{latest['trin_signal']}]")
print(f"  % > 50-day SMA   : {latest['pct_above_50sma']:.1f}%")
print(f"  % > 200-day SMA  : {p200:.1f}%" if pd.notna(p200) else "  % > 200-day SMA  : NaN")
print(f"  Breadth Score    : {int(latest['breadth_score'])}  [{latest['breadth_label']}]")
print(f"  Narrative        : {latest['breadth_narrative']}")
print("=" * 60)

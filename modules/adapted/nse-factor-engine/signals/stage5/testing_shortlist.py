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
Stage 5 — Testing Shortlist (NOT a production pipeline component)

Experimental top-20 selection combining gates + composite score across
all 5 functional variable groups. Run standalone to eyeball today's
shortlist; tweak thresholds/weights and re-run. Final design must be
validated by backtest before being canonized.
"""
import glob
import os
import re

import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine/"

GATE_STPB_RET_21D_MIN = -0.05
GATE_STPB_MA_DIST_MIN = 0.0
GATE_LOTTERY_KEEP = {"CAUTIOUS", "ALRIGHT"}
GATE_PROXIMITY_MIN = 0.80

WEIGHT_MOMENTUM = 0.30
WEIGHT_FIP = 0.20
WEIGHT_RS = 0.20
WEIGHT_INDUSTRY = 0.15
WEIGHT_PROXIMITY = 0.15

TOP_N = 20

signals_files = glob.glob(BASE + "signals/final/momentum_signals_final_*.parquet")
signals_files = [f for f in signals_files if "_pre_stage" not in f]
date_re = re.compile(r"momentum_signals_final_(\d{8})\.parquet$")
dated = []
for f in signals_files:
    m = date_re.search(f)
    if m:
        dated.append((m.group(1), f))
dated.sort(key=lambda x: pd.Timestamp(day=int(x[0][:2]), month=int(x[0][2:4]), year=int(x[0][4:])))
run_date_str, SIGNALS_PATH = dated[-1]
print(f"Using signals file run_date: {run_date_str}")
print(f"Signals path: {SIGNALS_PATH}\n")

df = pd.read_parquet(SIGNALS_PATH)
print(f"Input shape: {df.shape}")
n_start = len(df)

print("\n=== Gate attrition ===")
df = df[df["in_universe"]]
print(f"G1 in_universe==True              : {n_start} -> {len(df)}")
df = df[df["weinstein_stage2"]]
print(f"G2 weinstein_stage2==True         : -> {len(df)}")
df = df[df["stpb_ret_21d"] > GATE_STPB_RET_21D_MIN]
print(f"G3 stpb_ret_21d > {GATE_STPB_RET_21D_MIN}            : -> {len(df)}")
df = df[df["stpb_ma_distance_21d"] > GATE_STPB_MA_DIST_MIN]
print(f"G4 stpb_ma_distance_21d > {GATE_STPB_MA_DIST_MIN}       : -> {len(df)}")
df = df[df["lottery_class"].isin(GATE_LOTTERY_KEEP)]
print(f"G5 lottery_class in {GATE_LOTTERY_KEEP}: -> {len(df)}")
df = df[df["proximity_52w_high"] > GATE_PROXIMITY_MIN]
print(f"G6 proximity_52w_high > {GATE_PROXIMITY_MIN}        : -> {len(df)}")

n_survivors = len(df)
assert n_survivors > 0, "No symbols survived gates -- relax thresholds."
print(f"\nSurvivors entering composite score: {n_survivors}")

if n_survivors < TOP_N:
    print(f"WARNING: only {n_survivors} survivors, fewer than TOP_N={TOP_N}.")

df = df.copy()

df["sub_mom_avg_rank"] = (
    df[["ret_12m1m", "sharpe_style_momentum", "sortino_style_momentum"]]
    .rank(method="min", ascending=False)
    .mean(axis=1)
)
df["sub_mom_rank"] = df["sub_mom_avg_rank"].rank(method="min", ascending=True)

df["sub_fip_rank"] = df["fip_score"].rank(method="min", ascending=True)
df["sub_rs_rank"] = df["rs_rank_500"].rank(method="min", ascending=False)
df["sub_industry_rank"] = df["industry_rank"].rank(method="min", ascending=False)
df["sub_proximity_rank"] = df["proximity_52w_high"].rank(method="min", ascending=False)

df["composite_score"] = (
    WEIGHT_MOMENTUM * df["sub_mom_rank"]
    + WEIGHT_FIP * df["sub_fip_rank"]
    + WEIGHT_RS * df["sub_rs_rank"]
    + WEIGHT_INDUSTRY * df["sub_industry_rank"]
    + WEIGHT_PROXIMITY * df["sub_proximity_rank"]
)

n_null_composite = df["composite_score"].isnull().sum()
if n_null_composite > 0:
    print(
        f"\nWARNING: {n_null_composite} survivor(s) have NaN composite_score -- "
        f"checking which input column is null for each:"
    )
    null_rows = df[df["composite_score"].isnull()]
    check_cols = [
        "symbol",
        "ret_12m1m",
        "sharpe_style_momentum",
        "sortino_style_momentum",
        "fip_score",
        "rs_rank_500",
        "industry_rank",
        "proximity_52w_high",
    ]
    print(null_rows[check_cols].to_string(index=False))

df["composite_rank"] = df["composite_score"].rank(method="min", ascending=True).astype("Int64")

df = df[df["composite_score"].notnull()].copy()
print(f"\nSurvivors with valid composite_score: {len(df)}")

shortlist = df.sort_values("composite_rank").head(TOP_N).copy()

display_cols = [
    "composite_rank",
    "symbol",
    "ret_12m1m",
    "rank_ret_12m1m",
    "fip_score",
    "rs_rank_500",
    "industry_rank",
    "proximity_52w_high",
    "stpb_ret_21d",
    "stpb_ma_distance_21d",
    "weinstein_stage2",
    "lottery_class",
    "composite_score",
]

print(f"\n=== TOP {TOP_N} BY COMPOSITE SCORE ===\n")
print(shortlist[display_cols].to_string(index=False))

if "NATIONALUM" in shortlist["symbol"].values:
    print("\nNOTE: NATIONALUM survived the gates -- inspect why.")
else:
    nationalum_row = pd.read_parquet(SIGNALS_PATH)
    nationalum_row = nationalum_row[nationalum_row["symbol"] == "NATIONALUM"]
    print("\nSanity: NATIONALUM correctly excluded. Its values were:")
    print(f"  weinstein_stage2     = {nationalum_row['weinstein_stage2'].values[0]}")
    print(f"  stpb_ret_21d         = {nationalum_row['stpb_ret_21d'].values[0]:.4f}")
    print(f"  stpb_ma_distance_21d = {nationalum_row['stpb_ma_distance_21d'].values[0]:.4f}")
    print(f"  lottery_class        = {nationalum_row['lottery_class'].values[0]}")
    print(f"  proximity_52w_high   = {nationalum_row['proximity_52w_high'].values[0]:.4f}")

out_dir = BASE + "signals/stage5/intermediate/"
os.makedirs(out_dir, exist_ok=True)
out_path = out_dir + f"testing_shortlist_{run_date_str}.csv"
shortlist[display_cols].to_csv(out_path, index=False)
print(f"\nWritten: {out_path}")

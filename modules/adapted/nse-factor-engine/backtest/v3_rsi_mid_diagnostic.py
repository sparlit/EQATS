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
Diagnostic: Mid-Month RSI Swap — Did the Replacements Outperform?
==================================================================
For every mid-month RSI exit, computes:
  - Replaced stock  : return from d16 open → next SOM open (counterfactual if held)
  - Replacement stock: return from d16 open → next SOM open (actual)

Run from repo root:
  cd /home/ec2-user/nse-factor-engine
  python3 backtest/v3_rsi_mid_diagnostic.py
"""

import gc
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/ec2-user/nse-factor-engine")

BASE = "backtest"
RESULTS_DIR = f"{BASE}/results"
PRICES_PATH = f"{BASE}/data/prices_backtest.parquet"

# ── Find latest activity CSV ──────────────────────────────────────────────────
candidates = sorted(
    [
        f
        for f in os.listdir(RESULTS_DIR)
        if f.startswith("MR_M_V3_RSI_SIM_activity") and f.endswith(".csv")
    ]
)
if not candidates:
    raise FileNotFoundError("No MR_M_V3_RSI_SIM_activity CSV found in results/")
act_path = os.path.join(RESULTS_DIR, candidates[-1])
print(f"Loading activity: {act_path}")
act = pd.read_csv(act_path, parse_dates=["friday_date", "signal_date"])

# ── Load prices ───────────────────────────────────────────────────────────────
print("Loading prices ...")
prices = pd.read_parquet(PRICES_PATH, columns=["symbol", "date", "open", "close"])
prices["date"] = pd.to_datetime(prices["date"])

open_by_date = {
    pd.Timestamp(date): grp.set_index("symbol")["open"].to_dict()
    for date, grp in prices.groupby("date")
}
all_trading_days = sorted(open_by_date.keys())

prices_by_sym = {
    sym: grp[["date", "close"]].sort_values("date").reset_index(drop=True)
    for sym, grp in prices.groupby("symbol")
}
print(f"  {len(prices_by_sym)} symbols | {len(all_trading_days)} trading days")
del prices
gc.collect()

# ── Build signal_date → next SOM exec date ───────────────────────────────────
# SOM rows: friday_date = SOM exec date, signal_date = signal Friday
som_rows = act[act["rebal_type"] == "SOM"][["friday_date", "signal_date"]].drop_duplicates(
    "signal_date"
)
sig_to_som_exec = dict(zip(som_rows["signal_date"], som_rows["friday_date"], strict=False))

# Sort SOM exec dates to find next one
som_exec_dates = sorted(som_rows["friday_date"].unique())
som_exec_to_next = {
    som_exec_dates[i]: som_exec_dates[i + 1] for i in range(len(som_exec_dates) - 1)
}

# signal_date → next SOM exec date (one period ahead)
sig_to_next_som = {
    sig: som_exec_to_next[exec] for sig, exec in sig_to_som_exec.items() if exec in som_exec_to_next
}

print(f"\n  Built signal→next SOM map: {len(sig_to_next_som)} periods")
print(f"  Sample: {list(sig_to_next_som.items())[:3]}")

# ── Mid-month rows ────────────────────────────────────────────────────────────
mid = act[act["rebal_type"] == "MID"].copy()

exits = mid[mid["mr_action"] == "MID_SELL_RSI"].copy()
replacements = mid[mid["action"] == "BUY"].copy()

print(f"\n  MID_SELL_RSI rows : {len(exits)}")
print(f"  MID BUY rows      : {len(replacements)}")

# ── Compute returns: d16 open → next SOM open ────────────────────────────────
print("\nComputing returns ...")
t0 = time.time()

exit_records = []
for _, row in exits.iterrows():
    sig_date = row["signal_date"]
    sym = row["symbol"]
    d16_price = row["price"]  # execution price = d16 open
    next_som = sig_to_next_som.get(sig_date)
    if next_som is None:
        continue
    next_open = open_by_date.get(next_som, {}).get(sym, np.nan)
    if pd.isna(d16_price) or d16_price == 0 or pd.isna(next_open) or next_open == 0:
        continue
    exit_records.append(
        {
            "signal_date": sig_date,
            "d16_date": row["friday_date"],
            "next_som": next_som,
            "symbol": sym,
            "d16_price": d16_price,
            "next_som_open": next_open,
            "counterfactual_ret": next_open / d16_price - 1,
        }
    )

repl_records = []
for _, row in replacements.iterrows():
    sig_date = row["signal_date"]
    sym = row["symbol"]
    d16_price = row["price"]
    next_som = sig_to_next_som.get(sig_date)
    if next_som is None:
        continue
    next_open = open_by_date.get(next_som, {}).get(sym, np.nan)
    if pd.isna(d16_price) or d16_price == 0 or pd.isna(next_open) or next_open == 0:
        continue
    repl_records.append(
        {
            "signal_date": sig_date,
            "d16_date": row["friday_date"],
            "next_som": next_som,
            "symbol": sym,
            "d16_price": d16_price,
            "next_som_open": next_open,
            "actual_ret": next_open / d16_price - 1,
        }
    )

exits_df = pd.DataFrame(exit_records)
repls_df = pd.DataFrame(repl_records)
print(f"  Done in {time.time() - t0:.1f}s")
print(f"  Exit records    : {len(exits_df)}")
print(f"  Replace records : {len(repls_df)}")

# ── Q1: Overall comparison ────────────────────────────────────────────────────
er = exits_df["counterfactual_ret"]
rr = repls_df["actual_ret"]

print(f"\n{'=' * 72}")
print("Q1: REPLACED vs REPLACEMENT — d16 OPEN → NEXT SOM OPEN")
print(f"{'=' * 72}")
print(f"  {'':26}  {'Replaced (if held)':>18}  {'Replacement':>14}  {'Delta':>10}")
print(f"  {'-' * 26}  {'-' * 18}  {'-' * 14}  {'-' * 10}")
print(f"  {'Count':26}  {len(er):>18}  {len(rr):>14}")
print(
    f"  {'Mean return':26}  {er.mean() * 100:>17.2f}%  {rr.mean() * 100:>13.2f}%  {(rr.mean() - er.mean()) * 100:>+9.2f}%"
)
print(
    f"  {'Median return':26}  {er.median() * 100:>17.2f}%  {rr.median() * 100:>13.2f}%  {(rr.median() - er.median()) * 100:>+9.2f}%"
)
print(f"  {'% positive':26}  {(er > 0).mean() * 100:>17.1f}%  {(rr > 0).mean() * 100:>13.1f}%")
print(f"  {'Std dev':26}  {er.std() * 100:>17.2f}%  {rr.std() * 100:>13.2f}%")
print(
    f"  {'Mean tail (worst 10%)':26}  "
    f"{er.nsmallest(max(1, int(len(er) * 0.1))).mean() * 100:>17.2f}%  "
    f"{rr.nsmallest(max(1, int(len(rr) * 0.1))).mean() * 100:>13.2f}%"
)

# ── Q2: % portfolio exited at mid-month per period ───────────────────────────
mid_all = mid[mid["mr_action"].isin(["MID_HOLD", "MID_SELL_RSI"])].copy()
period_mid_summary = (
    mid_all.groupby("signal_date")
    .agg(
        n_held=("symbol", "count"),
        n_exits=("mr_action", lambda x: (x == "MID_SELL_RSI").sum()),
    )
    .reset_index()
)
period_mid_summary["pct_exited"] = (
    period_mid_summary["n_exits"] / period_mid_summary["n_held"] * 100
)

print(f"\n{'=' * 72}")
print("Q2: RSI < 50 PREVALENCE — SOM vs MID-MONTH")
print(f"{'=' * 72}")
print(f"  {'':35}  {'SOM':>10}  {'Mid-Month':>10}")
print(f"  {'-' * 35}  {'-' * 10}  {'-' * 10}")
print(
    f"  {'Avg slots with RSI < 50/period':35}  {'12.6':>10}  {period_mid_summary['n_exits'].mean():>10.1f}"
)
print(
    f"  {'Avg % of portfolio':35}  {'50.2%':>10}  {period_mid_summary['pct_exited'].mean():>9.1f}%"
)
print(f"  {'Periods with 0 exits':35}  {'1':>10}  {(period_mid_summary['n_exits'] == 0).sum():>10}")
print(
    f"  {'Periods with > 10 exits':35}  {'77':>10}  {(period_mid_summary['n_exits'] > 10).sum():>10}"
)

# ── Q3: Per-period swap quality ───────────────────────────────────────────────
period_exit_ret = (
    exits_df.groupby("signal_date")["counterfactual_ret"].mean().rename("replaced_ret")
)
period_repl_ret = repls_df.groupby("signal_date")["actual_ret"].mean().rename("replacement_ret")
period_compare = pd.concat([period_exit_ret, period_repl_ret], axis=1).dropna()
period_compare["delta"] = period_compare["replacement_ret"] - period_compare["replaced_ret"]

print(f"\n{'=' * 72}")
print("Q3: HOW OFTEN DID REPLACEMENTS BEAT THE REPLACED? (per period)")
print(f"{'=' * 72}")
print(f"  Periods with mid-month swaps      : {len(period_compare)}")
print(
    f"  Periods replacement won           : {(period_compare['delta'] > 0).sum()} "
    f"({(period_compare['delta'] > 0).mean() * 100:.1f}%)"
)
print(
    f"  Periods replacement lost          : {(period_compare['delta'] < 0).sum()} "
    f"({(period_compare['delta'] < 0).mean() * 100:.1f}%)"
)
print(f"  Avg delta per period              : {period_compare['delta'].mean() * 100:+.2f}%")
print(f"  Median delta per period           : {period_compare['delta'].median() * 100:+.2f}%")

# ── Verdict ───────────────────────────────────────────────────────────────────
delta = (rr.mean() - er.mean()) * 100
print(f"\n{'=' * 72}")
print("VERDICT")
print(f"{'=' * 72}")
if delta > 0.5:
    print(f"  Replacements outperformed by {delta:+.2f}% on average.")
    print("  Mid-month RSI swap is adding genuine alpha in the residual holding window.")
elif delta < -0.5:
    print(f"  Replacements underperformed by {delta:+.2f}% on average.")
    print("  The swap is destroying value — exits would have been better held.")
else:
    print(f"  Negligible difference ({delta:+.2f}%).")
    print("  CAGR gain comes from cutting losers, not from replacement quality.")
print(f"{'=' * 72}")

# ── Save ──────────────────────────────────────────────────────────────────────
out_path = f"{RESULTS_DIR}/v3_rsi_mid_diagnostic.csv"
pd.concat(
    [
        exits_df.assign(type="replaced"),
        repls_df.rename(columns={"actual_ret": "counterfactual_ret"}).assign(type="replacement"),
    ]
).to_csv(out_path, index=False)
print(f"\n  Saved: {out_path}")

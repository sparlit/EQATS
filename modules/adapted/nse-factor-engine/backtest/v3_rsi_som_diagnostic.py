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
Diagnostic: SOM RSI vs Next-Month Return
=========================================
Reads the MR_M_V3_RSI_SIM activity CSV (mid-month only sim) and for every
SOM holding computes the signal-Friday RSI and the actual next-month return.

Answers two questions:
  Q1: Does RSI < 50 at SOM actually predict worse next-month performance?
      If yes → SOM RSI filter has signal, just needs a better cash-avoidance strategy
      If no  → SOM RSI filter has no alpha and should stay dropped

  Q2: What is the RSI distribution of SOM holdings?
      How many slots would be filtered, and are replacements even available?

Run from repo root:
  cd /home/ec2-user/nse-factor-engine
  python3 backtest/v3_rsi_som_diagnostic.py
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

RSI_EXIT_THRESH = 50

# ── Find latest activity CSV from the mid-month-only sim ─────────────────────
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


# ── RSI ───────────────────────────────────────────────────────────────────────
def wilder_rsi(closes):
    if len(closes) < 15:
        return np.nan
    deltas = np.diff(closes[-15:])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains.mean()
    avg_loss = losses.mean()
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def compute_rsi(sym, up_to_date):
    sym_df = prices_by_sym.get(sym)
    if sym_df is None:
        return np.nan
    closes = sym_df[sym_df["date"] <= up_to_date]["close"].values
    return wilder_rsi(closes)


# ── Filter to SOM BUY/HOLD rows ───────────────────────────────────────────────
som_act = act[(act["rebal_type"] == "SOM") & (act["action"].isin(["BUY", "HOLD"]))].copy()

exec_dates = sorted(som_act["friday_date"].unique())
period_to_next = {exec_dates[i]: exec_dates[i + 1] for i in range(len(exec_dates) - 1)}

# ── Main loop: compute SOM RSI + next-month return for every holding ──────────
print(f"\nComputing SOM RSI for {len(som_act)} holdings across {len(exec_dates)} periods ...")
t0 = time.time()
records = []

for exec_date, grp in som_act.groupby("friday_date"):
    next_exec = period_to_next.get(exec_date)
    if next_exec is None:
        continue  # last period, no exit price

    next_px = open_by_date.get(next_exec, {})

    for _, row in grp.iterrows():
        sym = row["symbol"]
        sig_date = row["signal_date"]
        entry_px = row["price"]
        exit_px = next_px.get(sym, np.nan)

        if pd.isna(entry_px) or entry_px == 0 or pd.isna(exit_px) or exit_px == 0:
            continue

        rsi = compute_rsi(sym, sig_date)
        slot_ret = exit_px / entry_px - 1

        records.append(
            {
                "exec_date": exec_date,
                "signal_date": sig_date,
                "symbol": sym,
                "action": row["action"],
                "mr_rank": row.get("mr_rank", np.nan),
                "entry_px": entry_px,
                "exit_px": exit_px,
                "slot_ret": slot_ret,
                "rsi": rsi,
                "rsi_below": pd.notna(rsi) and rsi < RSI_EXIT_THRESH,
            }
        )

print(f"  Done in {time.time() - t0:.1f}s — {len(records)} slot-periods computed")
df = pd.DataFrame(records)

# ── Q1: Return by RSI bucket ──────────────────────────────────────────────────
bins = [0, 30, 40, 50, 60, 70, 80, 100]
labels = ["<30", "30-40", "40-50", "50-60", "60-70", "70-80", ">80"]
df["rsi_bucket"] = pd.cut(df["rsi"], bins=bins, labels=labels, right=False)

bucket_stats = (
    df.groupby("rsi_bucket", observed=True)["slot_ret"]
    .agg(
        count="count",
        mean_ret="mean",
        median_ret="median",
        std_ret="std",
        pct_positive=lambda x: (x > 0).mean(),
    )
    .reset_index()
)
bucket_stats["mean_ret_pct"] = bucket_stats["mean_ret"] * 100
bucket_stats["median_ret_pct"] = bucket_stats["median_ret"] * 100
bucket_stats["pct_of_total"] = bucket_stats["count"] / len(df) * 100

print(f"\n{'=' * 72}")
print("Q1: NEXT-MONTH SLOT RETURN BY SOM RSI BUCKET")
print(f"{'=' * 72}")
print(
    f"  {'RSI':>7}  {'Count':>6}  {'% Total':>8}  {'Mean Ret':>9}  {'Median':>8}  {'% Positive':>11}"
)
print(f"  {'-' * 7}  {'-' * 6}  {'-' * 8}  {'-' * 9}  {'-' * 8}  {'-' * 11}")
for _, r in bucket_stats.iterrows():
    marker = " ◄ filter zone" if r["rsi_bucket"] in ["<30", "30-40", "40-50"] else ""
    print(
        f"  {str(r['rsi_bucket']):>7}  {r['count']:>6.0f}  {r['pct_of_total']:>7.1f}%  "
        f"{r['mean_ret_pct']:>8.2f}%  {r['median_ret_pct']:>7.2f}%  "
        f"{r['pct_positive'] * 100:>10.1f}%{marker}"
    )

# ── Binary split: < 50 vs >= 50 ──────────────────────────────────────────────
below = df[df["rsi_below"]]["slot_ret"]
above = df[not df["rsi_below"]]["slot_ret"]

print(f"\n{'=' * 72}")
print(f"Q1 SUMMARY: RSI < {RSI_EXIT_THRESH} vs RSI >= {RSI_EXIT_THRESH} at SOM")
print(f"{'=' * 72}")
print(f"  {'':22}  {'RSI < 50':>12}  {'RSI >= 50':>12}  {'Delta':>10}")
print(f"  {'-' * 22}  {'-' * 12}  {'-' * 12}  {'-' * 10}")
print(f"  {'Count':22}  {len(below):>12}  {len(above):>12}")
print(
    f"  {'% of holdings':22}  {len(below) / len(df) * 100:>11.1f}%  {len(above) / len(df) * 100:>11.1f}%"
)
print(
    f"  {'Mean next-month ret':22}  {below.mean() * 100:>11.2f}%  {above.mean() * 100:>11.2f}%  {(below.mean() - above.mean()) * 100:>+9.2f}%"
)
print(
    f"  {'Median next-month ret':22}  {below.median() * 100:>11.2f}%  {above.median() * 100:>11.2f}%  {(below.median() - above.median()) * 100:>+9.2f}%"
)
print(
    f"  {'% months positive':22}  {(below > 0).mean() * 100:>11.1f}%  {(above > 0).mean() * 100:>11.1f}%"
)
print(f"  {'Std dev':22}  {below.std() * 100:>11.2f}%  {above.std() * 100:>11.2f}%")

# ── Q2: RSI distribution per period ──────────────────────────────────────────
period_summary = (
    df.groupby("exec_date")
    .agg(
        n_holdings=("symbol", "count"),
        n_below_50=("rsi_below", "sum"),
        mean_rsi=("rsi", "mean"),
        mean_slot_ret=("slot_ret", "mean"),
    )
    .reset_index()
)
period_summary["pct_below_50"] = period_summary["n_below_50"] / period_summary["n_holdings"] * 100

print(f"\n{'=' * 72}")
print("Q2: HOW MANY HOLDINGS HAVE RSI < 50 AT SOM PER PERIOD?")
print(f"{'=' * 72}")
print(f"  Avg holdings per period    : {period_summary['n_holdings'].mean():.1f}")
print(f"  Avg RSI < 50 count/period  : {period_summary['n_below_50'].mean():.1f}")
print(f"  Avg % of portfolio < 50    : {period_summary['pct_below_50'].mean():.1f}%")
print(f"  Max RSI < 50 in a period   : {period_summary['n_below_50'].max():.0f}")
print(f"  Periods with 0 below 50    : {(period_summary['n_below_50'] == 0).sum()}")
print(f"  Periods with > 10 below 50 : {(period_summary['n_below_50'] > 10).sum()}")

print("\n  Top 10 periods by # holdings with RSI < 50:")
print(
    f"  {'Exec Date':>12}  {'# Below 50':>11}  {'% Portfolio':>12}  {'Avg RSI':>8}  {'Period Ret':>11}"
)
print(f"  {'-' * 12}  {'-' * 11}  {'-' * 12}  {'-' * 8}  {'-' * 11}")
for _, r in period_summary.nlargest(10, "n_below_50").iterrows():
    print(
        f"  {str(r['exec_date'].date()):>12}  {r['n_below_50']:>11.0f}  "
        f"{r['pct_below_50']:>11.1f}%  {r['mean_rsi']:>8.1f}  "
        f"{r['mean_slot_ret'] * 100:>10.2f}%"
    )

# ── Verdict ───────────────────────────────────────────────────────────────────
delta = (below.mean() - above.mean()) * 100
print(f"\n{'=' * 72}")
print("VERDICT")
print(f"{'=' * 72}")
if abs(delta) < 0.3:
    print(f"  RSI < 50 at SOM has NO meaningful return difference ({delta:+.2f}%).")
    print("  Filter has no alpha. Cash drag is the entire reason SOM sim underperformed.")
elif delta < 0:
    print(f"  RSI < 50 at SOM stocks underperform by {delta:+.2f}% next month.")
    print(
        f"  Filter HAS signal — but cash drag of {period_summary['n_below_50'].mean():.1f} slots/month"
    )
    print("  overwhelmed the alpha. Worth retesting with hold-instead-of-cash fallback.")
else:
    print(f"  RSI < 50 at SOM stocks OUTPERFORM by {delta:+.2f}% next month.")
    print("  Filter is counterproductive — momentum names need high RSI to keep running.")
print(f"{'=' * 72}")

# ── Save ──────────────────────────────────────────────────────────────────────
out_path = f"{RESULTS_DIR}/v3_rsi_som_diagnostic.csv"
df.to_csv(out_path, index=False)
print(f"\n  Saved: {out_path}")

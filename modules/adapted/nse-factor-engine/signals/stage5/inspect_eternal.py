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
Sample-row inspection + quality checks for ETERNAL in the final Stage 5
output. Run after stage5_assemble.py has completed.
"""
import glob
import re

import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine/"

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

print(f"Reading: {SIGNALS_PATH}")
df = pd.read_parquet(SIGNALS_PATH)
print(f"Full file shape: {df.shape}")
print(f"Total columns: {len(df.columns)}")

assert "ETERNAL" in df["symbol"].values, "ETERNAL not found in final file"
row = df[df["symbol"] == "ETERNAL"]

print("\n=== ETERNAL — all columns, all values ===")
for col in df.columns:
    print(f"{col:35s} {row[col].values[0]}")

print("\n=== Quality checks ===")

dupes = df["symbol"].duplicated().sum()
print(f"1. Duplicate symbols in file: {dupes} (expect 0)")

print(f"2. Total rows: {len(df)} (expect 500, all original symbols retained)")

in_uni_true = (df["in_universe"]).sum()
in_uni_false = (not df["in_universe"]).sum()
print(f"3. in_universe True: {in_uni_true}, False: {in_uni_false} (expect ~496/4)")

eternal_in_universe = row["in_universe"].values[0]
rank_cols = [c for c in df.columns if c.startswith("rank_")]
eternal_ranks_null = row[rank_cols].isnull().all(axis=1).values[0]
print(f"4. ETERNAL in_universe={eternal_in_universe}, all rank cols null={eternal_ranks_null}")
if eternal_in_universe:
    assert not eternal_ranks_null, "MISMATCH: ETERNAL is in_universe but has all-null ranks"
    print("   -> Consistent: in_universe symbol has rank values")
else:
    assert eternal_ranks_null, "MISMATCH: ETERNAL is excluded but has non-null ranks"
    print("   -> Consistent: excluded symbol has no rank values")

if eternal_in_universe:
    in_uni_df = df[df["in_universe"]].copy()
    in_uni_df_sorted = in_uni_df.sort_values("ret_12m1m", ascending=False).reset_index(drop=True)
    actual_position = in_uni_df_sorted[in_uni_df_sorted["symbol"] == "ETERNAL"].index[0] + 1
    reported_rank = row["rank_ret_12m1m"].values[0]
    print(f"5. ETERNAL rank_ret_12m1m={reported_rank}, actual sorted position={actual_position}")
    assert reported_rank == actual_position or pd.isna(reported_rank), (
        f"MISMATCH: reported rank {reported_rank} != actual position {actual_position}"
    )
    print("   -> PASS: rank matches actual sorted position")

for metric in ["ret_12m1m", "simple_vol_adj_momentum", "sharpe_style_momentum", "sortino_style_momentum"]:
    r = row[f"rank_{metric}"].values[0]
    fip_r = row[f"rank_fip_{metric}"].values[0]
    in_top100 = pd.notna(r) and r <= 100
    has_fip = pd.notna(fip_r)
    status = "PASS" if (in_top100 == has_fip) else "MISMATCH"
    print(f"6. [{metric}] rank={r}, in_top100={in_top100}, rank_fip={fip_r}, has_fip={has_fip} -> {status}")

original_cols = [c for c in df.columns if c not in {"in_universe", "passes_mktcap", "passes_adtv"} | set(rank_cols)]
null_originals = row[original_cols].isnull().sum().sum()
print(f"7. Nulls among original Stage2-4 columns for ETERNAL: {null_originals} (investigate if >0)")

print("\nDone.")

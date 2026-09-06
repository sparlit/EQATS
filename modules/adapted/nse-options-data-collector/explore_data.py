"""
Explore collected data — read parquet files and analyze.

Usage:
    cd nse-options-data-collector
    python examples/explore_data.py
"""

import os
import sys
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def show_oi():
    oi_dir = os.path.join(DATA_DIR, "oi_snapshots")
    if not os.path.isdir(oi_dir):
        print("No OI data yet. Run: python examples/quick_start.py")
        return

    files = sorted(f for f in os.listdir(oi_dir) if f.startswith("oi_") and f.endswith(".parquet"))
    print(f"=== OI Snapshots ({len(files)} days) ===")
    for f in files:
        df = pd.read_parquet(os.path.join(oi_dir, f))
        ts = df["timestamp"].nunique()
        syms = df["symbol"].nunique()
        print(f"  {f}: {ts} snapshots, {syms} symbols, {len(df)} rows")

    if files:
        latest = pd.read_parquet(os.path.join(oi_dir, files[-1]))
        last_ts = latest["timestamp"].max()
        snap = latest[latest["timestamp"] == last_ts]
        print(f"\nLatest snapshot ({last_ts[:19]}):")
        print(snap[["symbol", "spot", "pcr", "ce_oi_signal", "pe_oi_signal",
                     "oi_change_pct"]].to_string(index=False))


def show_chain():
    chain_dir = os.path.join(DATA_DIR, "option_chain")
    if not os.path.isdir(chain_dir):
        return

    files = sorted(f for f in os.listdir(chain_dir) if f.startswith("chain_") and f.endswith(".parquet"))
    print(f"\n=== Option Chain ({len(files)} days) ===")
    for f in files:
        df = pd.read_parquet(os.path.join(chain_dir, f))
        ts = df["timestamp"].nunique()
        syms = df["symbol"].nunique()
        print(f"  {f}: {ts} snapshots, {syms} symbols, {len(df)} strike rows")

    if files:
        latest = pd.read_parquet(os.path.join(chain_dir, files[-1]))
        last_ts = latest["timestamp"].max()
        nifty = latest[(latest["timestamp"] == last_ts) & (latest["symbol"] == "NIFTY")]
        if not nifty.empty:
            spot = nifty["spot"].iloc[0]
            near = nifty.iloc[(nifty["strike"] - spot).abs().argsort()[:5]]
            print(f"\nNIFTY ATM (spot={spot}):")
            print(near[["strike", "ce_ltp", "ce_iv", "ce_delta", "ce_oi",
                         "pe_ltp", "pe_iv", "pe_delta", "pe_oi"]].to_string(index=False))


def show_global():
    global_dir = os.path.join(DATA_DIR, "global_cues")
    if not os.path.isdir(global_dir):
        return

    files = sorted(f for f in os.listdir(global_dir) if f.endswith(".parquet"))
    print(f"\n=== Global Cues ({len(files)} days) ===")
    if files:
        latest = pd.read_parquet(os.path.join(global_dir, files[-1]))
        for _, row in latest.iterrows():
            session = row.get("session", "?")
            cols = [c for c in row.index if c.endswith("_chg_pct")]
            changes = {c.replace("_chg_pct", ""): f"{row[c]:+.2f}%" for c in cols if row[c] != 0}
            print(f"  {session}: {changes}")


if __name__ == "__main__":
    show_oi()
    show_chain()
    show_global()

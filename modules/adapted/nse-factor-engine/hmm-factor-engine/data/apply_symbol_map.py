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
apply_symbol_map.py
===================
Applies the final confirmed symbol mappings to the price parquet.
For each old_symbol → new_symbol:
  - Copies new_symbol column data into old_symbol column
  - Both columns then have data (old for point-in-time CSV lookup,
    new for direct lookup)

Also saves symbol_map.csv for use by all factor scripts.

14 confirmed mappings. Everything else stays NaN (genuinely dead).
"""

from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).parent
PRICE_FILE = OUTPUT_DIR / "prices_hmm_daily.parquet"
VOLUME_FILE = OUTPUT_DIR / "prices_hmm_daily_volume.parquet"
MAP_FILE = OUTPUT_DIR / "symbol_map.csv"

# Final confirmed symbol map — old CSV symbol -> parquet column
SYMBOL_MAP = {
    "M& M": "M&M",
    "JUBLINGRY": "JUBLINGREA",
    "EQUITAS": "EQUITASBNK",
    "UJJIVAN": "UJJIVANSFB",
    "BALAJI": "BALAMINES",
    "HDFC": "HDFCBANK",
    "ICICI": "ICICIBANK",
    "MCDOWELL": "UNITDSPR",
    "TATASPONGE": "TATASTLLP",
    "TATAMETAL": "TATASTEEL",
    "UTTAM": "UTTAMSUGAR",
    "GARWARE": "GARFIBRES",
    "BAJAJ": "BAJAJHLDNG",
    "ITDCEMEN": "CEMPRO",
}


def main():
    print("Loading parquets ...")
    prices = pd.read_parquet(PRICE_FILE)
    volume = pd.read_parquet(VOLUME_FILE)
    print(f"  Shape before: {prices.shape}")

    print("\nApplying symbol map ...")
    print(f"  {'OLD':15s} {'NEW':15s} {'OLD_BEFORE':>10} {'OLD_AFTER':>10}  STATUS")
    print(f"  {'-' * 15} {'-' * 15} {'-' * 10} {'-' * 10}  ------")

    for old_sym, new_sym in SYMBOL_MAP.items():
        before = prices[old_sym].notna().sum() if old_sym in prices.columns else 0

        if new_sym not in prices.columns:
            print(f"  {old_sym:15s} {new_sym:15s} {before:>10} {'N/A':>10}  SKIP — new sym not in parquet")
            continue

        new_data_count = prices[new_sym].notna().sum()
        if new_data_count == 0:
            print(f"  {old_sym:15s} {new_sym:15s} {before:>10} {'N/A':>10}  SKIP — new sym has no data")
            continue

        # Copy new symbol data into old symbol column
        if old_sym in prices.columns:
            prices[old_sym] = prices[new_sym].values
            volume[old_sym] = volume[new_sym].values if new_sym in volume.columns else volume[old_sym]
        else:
            prices[old_sym] = prices[new_sym].values
            volume[old_sym] = volume[new_sym].values if new_sym in volume.columns else 0

        after = prices[old_sym].notna().sum()
        print(f"  {old_sym:15s} {new_sym:15s} {before:>10} {after:>10}  OK")

    print(f"\n  Shape after : {prices.shape}")
    print(f"  Tickers with data : {prices.notna().any().sum()}")

    # Save symbol map CSV for factor scripts
    import csv

    with open(MAP_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["csv_symbol", "parquet_col"])
        for old, new in SYMBOL_MAP.items():
            writer.writerow([old, new])
    print(f"\nSymbol map saved -> {MAP_FILE}")

    # Save patched parquets
    print("Saving parquets ...")
    prices.to_parquet(PRICE_FILE)
    volume.to_parquet(VOLUME_FILE)
    print(f"  Prices -> {PRICE_FILE}")
    print(f"  Volume -> {VOLUME_FILE}")
    print("Done.")


if __name__ == "__main__":
    main()

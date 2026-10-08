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
compute_mom.py
==============
MOM — Momentum Factor Construction (vectorized, fast)

Signal   : cumulative return months t-12 to t-2
Long leg : top decile by signal
Return   : equal-weight long leg minus short leg (next month)
Date fix : return recorded at next_date (month return is earned)
"""

import csv
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from universe import build_monthly_close, build_universe_lookup, get_pit_universe, load_prices_long

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
FACTORS_DIR = Path(__file__).parent / "data"

PRICE_FILE = DATA_DIR / "prices_hmm_daily.parquet"
CONSTITUENT_CSV = Path(
    "/home/ec2-user/nse-factor-engine/nifty_constituent_history/"
    "nifty500_2005-01-01_to_2026-06-30.csv"
)
SYMBOL_MAP_FILE = DATA_DIR / "symbol_map.csv"
OUTPUT_FILE = FACTORS_DIR / "mom_returns.parquet"
SAVE_SIGNALS = True
SIGNALS_FILE = FACTORS_DIR / "factor_mom.parquet"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKTEST_START = "2014-01"
BACKTEST_END = "2026-06"
MIN_STOCKS = 20
LONG_PCTILE = 0.90
SHORT_PCTILE = 0.10
ADTV_DAYS = 63
CRORE = 1e7

ADTV_SCHEDULE = [
    (pd.Timestamp("2018-01-01"), 10.0),
    (pd.Timestamp("2022-01-01"), 20.0),
    (pd.Timestamp("9999-01-01"), 30.0),
]


def get_adtv_threshold(date: pd.Timestamp) -> float:
    for cutoff, threshold in ADTV_SCHEDULE:
        if date < cutoff:
            return threshold
    return 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_symbol_map(map_file: Path) -> dict:
    sym_map = {}
    with open(map_file) as f:
        for row in csv.DictReader(f):
            sym_map[row["csv_symbol"]] = row["parquet_col"]
    return sym_map


# ---------------------------------------------------------------------------
# Fast vectorized ADTV — compute for ALL symbols and ALL months at once
# ---------------------------------------------------------------------------
def build_adtv_matrix(prices_long: pd.DataFrame, monthly_index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Returns DataFrame (month_end_dates x symbols) of ADTV in crore.
    Uses groupby instead of per-symbol loops — orders of magnitude faster.
    """
    print("  Precomputing ADTV matrix (vectorized) ...")
    prices_long = prices_long.copy()
    prices_long["dtv"] = prices_long["close"] * prices_long["volume"] / CRORE

    # Pivot to wide: (date x symbol) daily DTV
    dtv_wide = prices_long.pivot_table(
        index="date", columns="symbol", values="dtv", aggfunc="first"
    )
    dtv_wide.index = pd.to_datetime(dtv_wide.index)
    dtv_wide = dtv_wide.sort_index()

    # For each month-end, rolling mean of past ADTV_DAYS trading days
    records = {}
    all_dates = dtv_wide.index.values

    for month_end in monthly_index:
        mask = all_dates <= np.datetime64(month_end)
        window_dates = all_dates[mask][-ADTV_DAYS:]
        if len(window_dates) < 10:
            continue
        records[month_end] = dtv_wide.loc[window_dates].mean()

    adtv_matrix = pd.DataFrame(records).T
    adtv_matrix.index = pd.to_datetime(adtv_matrix.index)
    print(f"  ADTV matrix shape: {adtv_matrix.shape}")
    return adtv_matrix


# ---------------------------------------------------------------------------
# Main backtest — fully vectorized, no inner stock loops
# ---------------------------------------------------------------------------
def run_backtest(
    monthly_prices: pd.DataFrame,
    adtv_matrix: pd.DataFrame,
    universe_df: pd.DataFrame,
    sym_map: dict,
) -> tuple:

    # Reverse sym_map: parquet_col -> csv_symbol
    rev_map = {v: k for k, v in sym_map.items()}

    # Signal matrix: price[t-2] / price[t-12] - 1  (dates x symbols)
    print("  Building signal matrix ...")
    signal_matrix = monthly_prices.shift(2) / monthly_prices.shift(12) - 1

    # Return matrix: price[t] / price[t-1] - 1  (dates x symbols)
    # return_matrix[t] = return EARNED in month t
    print("  Building return matrix ...")
    return_matrix = monthly_prices.pct_change()

    periods = pd.period_range(start=BACKTEST_START, end=BACKTEST_END, freq="M")
    valid_dates = [
        p.to_timestamp(how="end").normalize()
        for p in periods
        if p.to_timestamp(how="end").normalize() in monthly_prices.index
    ]

    records = []
    signal_records = []
    idx = monthly_prices.index

    print(f"  Looping over {len(valid_dates)} months ...")
    for date in valid_dates:
        pos = idx.get_loc(date)
        if pos < 12 or pos >= len(idx) - 1:
            continue

        next_date = idx[pos + 1]

        # --- Universe: PIT membership ---
        pit = get_pit_universe(date, universe_df)
        if not pit:
            continue

        # --- ADTV filter (vectorized lookup) ---
        threshold = get_adtv_threshold(date)
        if date not in adtv_matrix.index:
            continue
        adtv_row = adtv_matrix.loc[date]
        pit_cols = [sym_map.get(s, s) for s in pit]
        pit_cols = [c for c in pit_cols if c in adtv_row.index]
        adtv_pass = adtv_row[pit_cols].dropna()
        adtv_pass = adtv_pass[adtv_pass >= threshold].index.tolist()

        if len(adtv_pass) < MIN_STOCKS:
            continue

        # --- Signal (vectorized lookup) ---
        sig_row = signal_matrix.loc[date, adtv_pass].dropna()
        if len(sig_row) < MIN_STOCKS:
            print(f"  SKIP {date.strftime('%Y-%m')}: only {len(sig_row)} stocks with signal")
            continue

        # --- Save signals ---
        if SAVE_SIGNALS:
            pct = sig_row.rank(pct=True)
            for col, raw in sig_row.items():
                sym = rev_map.get(col, col)
                signal_records.append(
                    {
                        "nse_ticker": sym,
                        "date": date,
                        "signal": float(raw),
                        "percentile": float(
                            pct[col].iloc[0] if hasattr(pct[col], "__len__") else pct[col]
                        ),
                    }
                )

        # --- Long / short selection ---
        long_thresh = sig_row.quantile(LONG_PCTILE)
        short_thresh = sig_row.quantile(SHORT_PCTILE)
        long_cols = sig_row[sig_row >= long_thresh].index.tolist()
        short_cols = sig_row[sig_row <= short_thresh].index.tolist()

        if not long_cols or not short_cols:
            continue

        # --- Next month returns (vectorized lookup) ---
        long_rets = return_matrix.loc[next_date, long_cols].dropna()
        short_rets = return_matrix.loc[next_date, short_cols].dropna()

        if long_rets.empty or short_rets.empty:
            continue

        records.append(
            {
                "date": next_date,  # return earned next month
                "mom_return": long_rets.mean() - short_rets.mean(),
                "long_return": long_rets.mean(),
                "short_return": short_rets.mean(),
                "long_count": len(long_rets),
                "short_count": len(short_rets),
                "universe_size": len(sig_row),
            }
        )

    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df, signal_records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    FACTORS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading symbol map ...")
    sym_map = load_symbol_map(SYMBOL_MAP_FILE)
    print(f"  {len(sym_map)} mappings loaded")

    print("Loading daily prices (long format) ...")
    prices_long = load_prices_long(PRICE_FILE)
    print(f"  Prices shape: {prices_long.shape}")

    print("Building monthly close prices ...")
    monthly_prices = build_monthly_close(prices_long)
    print(f"  Monthly shape: {monthly_prices.shape}")

    print("Building point-in-time universe lookup ...")
    universe_df = build_universe_lookup(CONSTITUENT_CSV)
    print(f"  {len(universe_df)} rebalance snapshots loaded")

    adtv_matrix = build_adtv_matrix(prices_long, monthly_prices.index)

    print(f"\nRunning backtest: {BACKTEST_START} to {BACKTEST_END} ...")
    results, signal_records = run_backtest(monthly_prices, adtv_matrix, universe_df, sym_map)

    if results.empty:
        print("ERROR: no results produced")
        return

    r = results["mom_return"]
    ann_ret = r.mean() * 12
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    drawdown = (cum / cum.cummax() - 1).min()
    hit_rate = (r > 0).mean()

    print(f"\n{'=' * 50}")
    print(f"MOM FACTOR RESULTS ({BACKTEST_START} to {BACKTEST_END})")
    print(f"{'=' * 50}")
    print(f"  Months          : {len(results)}")
    print(f"  Ann. return     : {ann_ret * 100:.2f}%")
    print(f"  Ann. volatility : {ann_vol * 100:.2f}%")
    print(f"  Sharpe ratio    : {sharpe:.3f}")
    print(f"  Max drawdown    : {drawdown * 100:.2f}%")
    print(f"  Hit rate        : {hit_rate * 100:.1f}%")
    print(f"  Avg universe    : {results['universe_size'].mean():.0f} stocks")
    print(f"  Avg long count  : {results['long_count'].mean():.0f}")
    print(f"  Avg short count : {results['short_count'].mean():.0f}")

    print("\nAround COVID (date = month return was earned):")
    covid = results.loc["2020-01":"2020-07", ["mom_return", "long_return", "short_return"]]
    print(covid.to_string())

    results.to_parquet(OUTPUT_FILE)
    print(f"\nSaved -> {OUTPUT_FILE}")

    if SAVE_SIGNALS and signal_records:
        sig_df = pd.DataFrame(signal_records)
        sig_df.to_parquet(SIGNALS_FILE, index=False)
        print(f"Saved signals -> {SIGNALS_FILE}  ({len(sig_df)} rows)")

    print("Done.")


if __name__ == "__main__":
    main()

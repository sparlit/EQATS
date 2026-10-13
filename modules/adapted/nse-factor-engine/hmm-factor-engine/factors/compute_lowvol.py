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
compute_lowvol.py
=================
LOWVOL — Low Volatility Factor Construction (vectorized, fast)

Signal   : realised annualised volatility over past 60 trading days
           circuit breaker days removed (|daily return| >= 5%)
Long leg : LOWEST vol decile
Date fix : return recorded at next_month_end (month return is earned)
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
OUTPUT_FILE = FACTORS_DIR / "lowvol_returns.parquet"
SAVE_SIGNALS = True
SIGNALS_FILE = FACTORS_DIR / "factor_lowvol.parquet"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKTEST_START = "2014-01"
BACKTEST_END = "2026-06"
MIN_STOCKS = 20
LOOKBACK_DAYS = 60
CIRCUIT_BREAKER_PCT = 0.05
MIN_DAYS_AFTER_FILTER = 20
LONG_PCTILE = 0.10
SHORT_PCTILE = 0.90
CRORE = 1e7
ADTV_DAYS = 63

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
# Fast vectorized ADTV
# ---------------------------------------------------------------------------
def build_adtv_matrix(prices_long: pd.DataFrame, monthly_index: pd.DatetimeIndex) -> pd.DataFrame:
    print("  Precomputing ADTV matrix (vectorized) ...")
    pl = prices_long.copy()
    pl["dtv"] = pl["close"] * pl["volume"] / CRORE

    dtv_wide = pl.pivot_table(index="date", columns="symbol", values="dtv", aggfunc="first")
    dtv_wide.index = pd.to_datetime(dtv_wide.index)
    dtv_wide = dtv_wide.sort_index()
    all_dates = dtv_wide.index.values

    records = {}
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
# Precompute volatility matrix (vectorized)
# ---------------------------------------------------------------------------
def build_vol_matrix(
    prices_long: pd.DataFrame,
    monthly_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    print("  Precomputing volatility matrix (vectorized) ...")

    # Wide daily returns
    daily_wide = prices_long.pivot_table(
        index="date", columns="symbol", values="close", aggfunc="first"
    )
    daily_wide.index = pd.to_datetime(daily_wide.index)
    daily_wide = daily_wide.sort_index()
    daily_ret = daily_wide.pct_change()

    # Mask circuit breaker days per stock (|ret| >= 5%)
    clean_ret = daily_ret.copy()
    clean_ret[clean_ret.abs() >= CIRCUIT_BREAKER_PCT] = np.nan

    all_dates = daily_ret.index.values
    records = {}

    for month_end in monthly_index:
        mask = all_dates <= np.datetime64(month_end)
        window_dates = all_dates[mask][-(LOOKBACK_DAYS + 1) :]
        if len(window_dates) < MIN_DAYS_AFTER_FILTER + 1:
            continue

        window = clean_ret.loc[window_dates]
        # Count valid days per stock
        valid_counts = window.notna().sum()
        # Annualised vol
        vol = window.std() * np.sqrt(252)
        # Zero out stocks with too few clean days
        vol[valid_counts < MIN_DAYS_AFTER_FILTER] = np.nan
        records[month_end] = vol

    vol_matrix = pd.DataFrame(records).T
    vol_matrix.index = pd.to_datetime(vol_matrix.index)
    print(f"  Vol matrix shape: {vol_matrix.shape}")
    return vol_matrix


# ---------------------------------------------------------------------------
# Backtest loop — vectorized
# ---------------------------------------------------------------------------
def run_backtest(
    prices_long: pd.DataFrame,
    monthly_px: pd.DataFrame,
    return_matrix: pd.DataFrame,
    vol_matrix: pd.DataFrame,
    adtv_matrix: pd.DataFrame,
    universe_df: pd.DataFrame,
    sym_map: dict,
) -> tuple:

    rev_map = {v: k for k, v in sym_map.items()}
    periods = pd.period_range(start=BACKTEST_START, end=BACKTEST_END, freq="M")
    valid_dates = [
        p.to_timestamp(how="end").normalize()
        for p in periods
        if p.to_timestamp(how="end").normalize() in monthly_px.index
    ]

    records = []
    signal_records = []
    idx = monthly_px.index

    print(f"  Looping over {len(valid_dates)} months ...")
    for _i, date in enumerate(valid_dates):
        pos = idx.get_loc(date)
        if pos >= len(idx) - 1:
            continue
        next_month_end = idx[pos + 1]

        # Universe
        pit = get_pit_universe(date, universe_df)
        if not pit:
            continue

        # ADTV filter
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

        # Vol lookup
        if date not in vol_matrix.index:
            continue
        vol_row = vol_matrix.loc[date, adtv_pass].dropna()
        vol_row = vol_row[vol_row > 0]

        if len(vol_row) < MIN_STOCKS:
            print(f"  SKIP {date.strftime('%Y-%m')}: only {len(vol_row)} stocks with vol signal")
            continue

        # Save signals
        if SAVE_SIGNALS:
            pct = 1 - vol_row.rank(pct=True)
            for col, raw in vol_row.items():
                sym = rev_map.get(col, col)
                signal_records.append(
                    {
                        "nse_ticker": sym,
                        "date": date,
                        "signal": float(raw),
                        "percentile": float(
                            pct[col] if not hasattr(pct[col], "__len__") else pct[col].iloc[0]
                        ),
                    }
                )

        # Long / short
        long_thresh = vol_row.quantile(LONG_PCTILE)
        short_thresh = vol_row.quantile(SHORT_PCTILE)
        long_cols = vol_row[vol_row <= long_thresh].index.tolist()
        short_cols = vol_row[vol_row >= short_thresh].index.tolist()

        if not long_cols or not short_cols:
            continue

        # Returns
        if next_month_end not in return_matrix.index:
            continue
        long_rets = return_matrix.loc[next_month_end, long_cols].dropna()
        short_rets = return_matrix.loc[next_month_end, short_cols].dropna()

        if long_rets.empty or short_rets.empty:
            continue

        records.append(
            {
                "date": next_month_end,
                "lowvol_return": long_rets.mean() - short_rets.mean(),
                "long_return": long_rets.mean(),
                "short_return": short_rets.mean(),
                "long_count": len(long_rets),
                "short_count": len(short_rets),
                "universe_size": len(vol_row),
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
    monthly_px = build_monthly_close(prices_long)
    print(f"  Monthly shape: {monthly_px.shape}")

    print("Building return matrix ...")
    return_matrix = monthly_px.pct_change()

    print("Building point-in-time universe lookup ...")
    universe_df = build_universe_lookup(CONSTITUENT_CSV)
    print(f"  {len(universe_df)} rebalance snapshots loaded")

    adtv_matrix = build_adtv_matrix(prices_long, monthly_px.index)
    vol_matrix = build_vol_matrix(prices_long, monthly_px.index)

    print(f"\nRunning backtest: {BACKTEST_START} to {BACKTEST_END} ...")
    results, signal_records = run_backtest(
        prices_long, monthly_px, return_matrix, vol_matrix, adtv_matrix, universe_df, sym_map
    )

    if results.empty:
        print("ERROR: no results produced")
        return

    r = results["lowvol_return"]
    ann_ret = r.mean() * 12
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    drawdown = (cum / cum.cummax() - 1).min()
    hit_rate = (r > 0).mean()

    print(f"\n{'=' * 50}")
    print(f"LOWVOL FACTOR RESULTS ({BACKTEST_START} to {BACKTEST_END})")
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
    covid = results.loc[results.index >= pd.Timestamp("2020-01-01")].head(7)[
        ["lowvol_return", "long_return", "short_return"]
    ]
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

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
compute_bab.py
==============
BAB — Betting Against Beta Factor Construction (vectorized, fast)

Signal   : rolling 60-month OLS beta vs Nifty 500 excess return
Long leg : lowest beta decile
Return   : long leg return recorded at next_date (month return is earned)
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
HMM_FILE = DATA_DIR / "nifty500_hmm_data.parquet"
CONSTITUENT_CSV = Path(
    "/home/ec2-user/nse-factor-engine/nifty_constituent_history/"
    "nifty500_2005-01-01_to_2026-06-30.csv"
)
SYMBOL_MAP_FILE = DATA_DIR / "symbol_map.csv"
OUTPUT_FILE = FACTORS_DIR / "bab_returns.parquet"
SAVE_SIGNALS = True
SIGNALS_FILE = FACTORS_DIR / "factor_bab.parquet"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKTEST_START = "2014-01"
BACKTEST_END = "2026-06"
MIN_STOCKS = 20
BETA_WINDOW = 60
MIN_OBS = 36
LONG_PCTILE = 0.10
SHORT_PCTILE = 0.90
MAX_LEVERAGE = 2.0
MIN_BETA = 0.20
MAX_BETA = 5.0
CRORE = 1e7
ADTV_DAYS = 63

ADTV_SCHEDULE = [
    (pd.Timestamp("2018-01-01"), 10.0),
    (pd.Timestamp("2022-01-01"), 20.0),
    (pd.Timestamp("9999-01-01"), 30.0),
]

RFR_SCHEDULE = [
    ("2005-04", "2011-12", 0.080),
    ("2012-01", "2019-12", 0.070),
    ("2020-01", "2021-12", 0.050),
    ("2022-01", "2099-12", 0.070),
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


def build_rfr_series(index: pd.DatetimeIndex) -> pd.Series:
    rfr = pd.Series(np.nan, index=index, name="rfr_monthly")
    for start, end, annual_rate in RFR_SCHEDULE:
        mask = (index >= pd.Period(start, "M").to_timestamp()) & (
            index <= pd.Period(end, "M").to_timestamp(how="end")
        )
        rfr[mask] = annual_rate / 12
    return rfr


def load_nifty_excess_returns(hmm_file: Path) -> pd.Series:
    hmm = pd.read_parquet(hmm_file)
    excess = hmm["excess_return"].copy()
    excess.index = pd.to_datetime(excess.index)
    print(
        f"  Nifty excess returns: {excess.index[0].date()} -> "
        f"{excess.index[-1].date()} ({len(excess)} months)"
    )
    return excess


# ---------------------------------------------------------------------------
# Fast vectorized ADTV
# ---------------------------------------------------------------------------
def build_adtv_matrix(prices_long: pd.DataFrame, monthly_index: pd.DatetimeIndex) -> pd.DataFrame:
    print("  Precomputing ADTV matrix (vectorized) ...")
    prices_long = prices_long.copy()
    prices_long["dtv"] = prices_long["close"] * prices_long["volume"] / CRORE

    dtv_wide = prices_long.pivot_table(
        index="date", columns="symbol", values="dtv", aggfunc="first"
    )
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
# Precompute beta matrix for all stocks and all months
# ---------------------------------------------------------------------------
def build_beta_matrix(
    stock_excess: pd.DataFrame,
    nifty_excess: pd.Series,
    monthly_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    print("  Precomputing beta matrix ...")
    nifty_vals = nifty_excess.reindex(stock_excess.index)
    nifty_vals.rolling(BETA_WINDOW, min_periods=MIN_OBS).var()

    beta_records = {}
    for month_end in monthly_index:
        if month_end not in stock_excess.index:
            continue
        pos = stock_excess.index.get_loc(month_end)
        if pos < MIN_OBS:
            continue

        start_pos = max(0, pos - BETA_WINDOW + 1)
        window_idx = stock_excess.index[start_pos : pos + 1]
        nifty_w = nifty_vals.reindex(window_idx).dropna()

        if len(nifty_w) < MIN_OBS:
            continue

        nv = nifty_w.var()
        if nv == 0:
            continue

        stock_w = stock_excess.reindex(window_idx)
        # Covariance of each stock with nifty
        cov = stock_w.apply(
            lambda col: col.cov(nifty_w) if col.dropna().shape[0] >= MIN_OBS else np.nan
        )
        betas = cov / nv
        # Clip to valid range
        betas = betas.where((betas >= MIN_BETA) & (betas <= MAX_BETA))
        beta_records[month_end] = betas

    beta_matrix = pd.DataFrame(beta_records).T
    beta_matrix.index = pd.to_datetime(beta_matrix.index)
    print(f"  Beta matrix shape: {beta_matrix.shape}")
    return beta_matrix


# ---------------------------------------------------------------------------
# Main backtest — vectorized
# ---------------------------------------------------------------------------
def run_backtest(
    stock_excess: pd.DataFrame,
    nifty_excess: pd.Series,
    beta_matrix: pd.DataFrame,
    adtv_matrix: pd.DataFrame,
    return_matrix: pd.DataFrame,
    universe_df: pd.DataFrame,
    sym_map: dict,
) -> tuple:

    rev_map = {v: k for k, v in sym_map.items()}

    periods = pd.period_range(start=BACKTEST_START, end=BACKTEST_END, freq="M")
    valid_dates = [
        p.to_timestamp(how="end").normalize()
        for p in periods
        if p.to_timestamp(how="end").normalize() in stock_excess.index
    ]

    records = []
    signal_records = []
    idx = stock_excess.index

    print(f"  Looping over {len(valid_dates)} months ...")
    for date in valid_dates:
        pos = idx.get_loc(date)
        if pos >= len(idx) - 1:
            continue
        next_date = idx[pos + 1]

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

        # Beta lookup
        if date not in beta_matrix.index:
            continue
        beta_row = beta_matrix.loc[date, adtv_pass].dropna()
        beta_row = beta_row[(beta_row >= MIN_BETA) & (beta_row <= MAX_BETA)]

        if len(beta_row) < MIN_STOCKS:
            print(f"  SKIP {date.strftime('%Y-%m')}: only {len(beta_row)} stocks with valid beta")
            continue

        # Save signals
        if SAVE_SIGNALS:
            pct = 1 - beta_row.rank(pct=True)
            for col, raw in beta_row.items():
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
        long_thresh = beta_row.quantile(LONG_PCTILE)
        short_thresh = beta_row.quantile(SHORT_PCTILE)
        long_cols = beta_row[beta_row <= long_thresh].index.tolist()
        short_cols = beta_row[beta_row >= short_thresh].index.tolist()

        if not long_cols or not short_cols:
            continue

        avg_beta_long = beta_row[long_cols].mean()
        avg_beta_short = beta_row[short_cols].mean()

        if avg_beta_long < MIN_BETA or avg_beta_short < MIN_BETA:
            continue

        leverage_long = min(1.0 / avg_beta_long, MAX_LEVERAGE)
        leverage_short = min(1.0 / avg_beta_short, MAX_LEVERAGE)

        # Returns
        if next_date not in return_matrix.index:
            continue
        long_rets = return_matrix.loc[next_date, long_cols].dropna()
        short_rets = return_matrix.loc[next_date, short_cols].dropna()

        if long_rets.empty or short_rets.empty:
            continue

        records.append(
            {
                "date": next_date,
                "bab_return": long_rets.mean() * leverage_long - short_rets.mean() * leverage_short,
                "long_return": long_rets.mean() * leverage_long,
                "short_return": short_rets.mean() * leverage_short,
                "long_count": len(long_rets),
                "short_count": len(short_rets),
                "universe_size": len(beta_row),
                "avg_beta_long": round(avg_beta_long, 3),
                "avg_beta_short": round(avg_beta_short, 3),
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

    print("Loading Nifty 500 excess return series ...")
    nifty_excess = load_nifty_excess_returns(HMM_FILE)

    print("Loading daily prices (long format) ...")
    prices_long = load_prices_long(PRICE_FILE)
    print(f"  Prices shape: {prices_long.shape}")

    print("Building monthly close prices ...")
    monthly_px = build_monthly_close(prices_long)
    print(f"  Monthly shape: {monthly_px.shape}")

    print("Building monthly stock excess returns ...")
    monthly_ret = monthly_px.pct_change()
    rfr = build_rfr_series(monthly_ret.index)
    stock_excess = monthly_ret.subtract(rfr, axis=0)
    print(f"  Stock excess shape: {stock_excess.shape}")

    print("Building return matrix ...")
    return_matrix = monthly_px.pct_change()

    print("Building point-in-time universe lookup ...")
    universe_df = build_universe_lookup(CONSTITUENT_CSV)
    print(f"  {len(universe_df)} rebalance snapshots loaded")

    adtv_matrix = build_adtv_matrix(prices_long, monthly_px.index)
    beta_matrix = build_beta_matrix(stock_excess, nifty_excess, monthly_px.index)

    print(f"\nRunning backtest: {BACKTEST_START} to {BACKTEST_END} ...")
    results, signal_records = run_backtest(
        stock_excess, nifty_excess, beta_matrix, adtv_matrix, return_matrix, universe_df, sym_map
    )

    if results.empty:
        print("ERROR: no results produced")
        return

    r = results["bab_return"]
    ann_ret = r.mean() * 12
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    drawdown = (cum / cum.cummax() - 1).min()
    hit_rate = (r > 0).mean()

    print(f"\n{'=' * 50}")
    print(f"BAB FACTOR RESULTS ({BACKTEST_START} to {BACKTEST_END})")
    print(f"{'=' * 50}")
    print(f"  Months              : {len(results)}")
    print(f"  Ann. return         : {ann_ret * 100:.2f}%")
    print(f"  Ann. volatility     : {ann_vol * 100:.2f}%")
    print(f"  Sharpe ratio        : {sharpe:.3f}")
    print(f"  Max drawdown        : {drawdown * 100:.2f}%")
    print(f"  Hit rate            : {hit_rate * 100:.1f}%")
    print(f"  Avg universe        : {results['universe_size'].mean():.0f} stocks")
    print(f"  Avg long count      : {results['long_count'].mean():.0f}")
    print(f"  Avg short count     : {results['short_count'].mean():.0f}")
    print(f"  Avg beta long leg   : {results['avg_beta_long'].mean():.3f}")
    print(f"  Avg beta short leg  : {results['avg_beta_short'].mean():.3f}")

    print("\nAround COVID (date = month return was earned):")
    covid = results.loc["2020-01":"2020-07", ["bab_return", "long_return", "short_return"]]
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

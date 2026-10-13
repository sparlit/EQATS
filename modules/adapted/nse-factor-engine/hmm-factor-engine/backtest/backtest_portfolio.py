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
backtest_portfolio.py
=====================
OOS Portfolio Backtest — Factor-Blended Long-Only

Method:
  1. For each month in OOS window (2024-07 to 2026-06):
     a. Load blended weights (sharpe_erc) for that month
     b. Load each factor's percentile signal for that month
     c. Compute blended score = weighted avg of percentile ranks
     d. Pick top 25 stocks by blended score
     e. Hold equal-weight, record next month return
  2. Benchmark: Nifty500 equal-weight universe return

Output:
  hmm-factor-engine/backtest/oos_backtest_results.parquet
  hmm-factor-engine/backtest/oos_backtest_summary.csv
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
FACTORS_DIR = BASE_DIR / "factors" / "data"
REGIME_DIR = BASE_DIR / "regime"
BACKTEST_DIR = Path(__file__).parent

PRICE_FILE = DATA_DIR / "prices_hmm_daily.parquet"
BLENDED_WEIGHTS = REGIME_DIR / "blended_weights.parquet"
OUTPUT_FILE = BACKTEST_DIR / "oos_backtest_results.parquet"
OUTPUT_SUMMARY = BACKTEST_DIR / "oos_backtest_summary.csv"
OUTPUT_HOLDINGS = BACKTEST_DIR / "oos_backtest_holdings.csv"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OOS_START = "2024-07"
OOS_END = "2026-06"
TOP_N = 25
METHOD = "sharpe_erc"

FACTOR_FILES = {
    "mom": ("factor_mom.parquet", "percentile"),
    "bab": ("factor_bab.parquet", "percentile"),
    "rmw_roe": ("factor_rmw.parquet", "score_combined_roe"),
    "value": ("factor_value.parquet", "score_combined"),
    "size": ("factor_size.parquet", "score"),
}


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
def load_blended_weights() -> pd.DataFrame:
    bw = pd.read_parquet(BLENDED_WEIGHTS).reset_index()
    bw["date"] = bw["date"].dt.to_timestamp()
    bw = bw[bw["method"] == METHOD].set_index("date").drop(columns=["method", "weight_sum"])
    return bw


def load_factor_signals() -> dict:
    signals = {}
    for factor, (fname, score_col) in FACTOR_FILES.items():
        df = pd.read_parquet(FACTORS_DIR / fname)
        df["date"] = pd.to_datetime(df["date"])
        df = df[["nse_ticker", "date", score_col]].rename(columns={score_col: "score"})
        # Normalize to percentile rank within each month
        df["pct_rank"] = df.groupby("date")["score"].rank(pct=True)
        signals[factor] = df.set_index(["date", "nse_ticker"])["pct_rank"]
        print(
            f"  {factor}: {len(df)} rows, dates {df['date'].min().date()} to {df['date'].max().date()}"
        )
    return signals


def load_monthly_returns(price_file: Path) -> pd.DataFrame:
    print("  Loading prices ...")
    prices = pd.read_parquet(price_file)
    prices["date"] = pd.to_datetime(prices["date"])
    monthly = (
        prices.groupby(["symbol", pd.Grouper(key="date", freq="ME")])["close"]
        .last()
        .unstack("symbol")
    )
    ret = monthly.pct_change()
    print(f"  Monthly return matrix: {ret.shape}")
    return ret


# ---------------------------------------------------------------------------
# Main backtest
# ---------------------------------------------------------------------------
def run_backtest(
    weights: pd.DataFrame,
    signals: dict,
    monthly_ret: pd.DataFrame,
    nifty_ret: pd.Series,
) -> tuple:

    periods = pd.period_range(start=OOS_START, end=OOS_END, freq="M")
    signal_dates = [p.to_timestamp(how="end").normalize() for p in periods]
    ret_idx = monthly_ret.index

    records = []
    holdings = []

    for signal_date in signal_dates:
        # Match to actual month-end in return matrix
        candidates = ret_idx[ret_idx <= signal_date + pd.offsets.Day(5)]
        if candidates.empty:
            continue
        t_end = candidates[-1]

        # Next month return date
        pos = ret_idx.get_loc(t_end)
        if pos >= len(ret_idx) - 1:
            continue
        t1_end = ret_idx[pos + 1]

        # Blended weights for this month
        w_candidates = weights.index[weights.index <= t_end]
        if w_candidates.empty:
            continue
        w = weights.loc[w_candidates[-1]]

        # Collect per-factor percentile ranks
        factor_scores = {}
        for factor, pct_series in signals.items():
            avail_dates = pct_series.index.get_level_values("date").unique()
            avail_dates = avail_dates[avail_dates <= t_end]
            if avail_dates.empty:
                continue
            t_end_f = avail_dates[-1]
            factor_scores[factor] = pct_series.loc[t_end_f].groupby(level=0).first()

        if not factor_scores:
            continue

        # Blended score = weighted avg of percentile ranks
        score_df = pd.DataFrame(factor_scores)
        active_factors = [f for f in w.index if w[f] > 0 and f in score_df.columns]
        if not active_factors:
            continue

        score_df = score_df[active_factors].dropna()
        if len(score_df) < TOP_N:
            print(f"  SKIP {t_end.strftime('%Y-%m')}: only {len(score_df)} stocks with all signals")
            continue

        active_w = w[active_factors]
        active_w = active_w / active_w.sum()
        blended = (score_df * active_w.values).sum(axis=1)
        top_stocks = blended.nlargest(TOP_N).index.tolist()

        # Next month portfolio return (equal weight)
        avail_stocks = [s for s in top_stocks if s in monthly_ret.columns]
        port_rets = monthly_ret.loc[t1_end, avail_stocks].dropna()

        if port_rets.empty:
            continue

        port_ret = port_rets.mean()

        # Benchmark: Nifty500 index return
        bench_ret = nifty_ret.get(t1_end, np.nan)

        records.append(
            {
                "date": t1_end,
                "port_return": port_ret,
                "bench_return": bench_ret,
                "excess_return": port_ret - bench_ret,
                "n_stocks": len(port_rets),
                "regime_weights": str(dict(w.round(3))),
            }
        )

        # Save holdings
        for stock in top_stocks:
            holdings.append(
                {
                    "signal_date": t_end,
                    "return_date": t1_end,
                    "nse_ticker": stock,
                    "blended_score": float(blended[stock]),
                    "weight": 1.0 / TOP_N,
                }
            )

    results_df = pd.DataFrame(records).set_index("date")
    holdings_df = pd.DataFrame(holdings)
    return results_df, holdings_df


# ---------------------------------------------------------------------------
# Print summary stats
# ---------------------------------------------------------------------------
def print_summary(results: pd.DataFrame):
    r = results["port_return"]
    b = results["bench_return"]
    ex = results["excess_return"]

    ann_port = r.mean() * 12
    ann_bench = b.mean() * 12
    ann_ex = ex.mean() * 12

    vol_port = r.std() * np.sqrt(12)
    vol_bench = b.std() * np.sqrt(12)
    vol_ex = ex.std() * np.sqrt(12)

    sharpe_port = ann_port / vol_port if vol_port > 0 else 0
    sharpe_bench = ann_bench / vol_bench if vol_bench > 0 else 0
    ir = ann_ex / vol_ex if vol_ex > 0 else 0

    cum_port = (1 + r).cumprod()
    cum_bench = (1 + b).cumprod()

    dd_port = (cum_port / cum_port.cummax() - 1).min()
    dd_bench = (cum_bench / cum_bench.cummax() - 1).min()

    hit_rate = (ex > 0).mean()

    print(f"\n{'=' * 60}")
    print(f"OOS BACKTEST RESULTS ({OOS_START} to {OOS_END})")
    print(f"{'=' * 60}")
    print(f"  Months              : {len(results)}")
    print(f"  {'Metric':<22} {'Portfolio':>12} {'Benchmark':>12}")
    print(f"  {'-' * 22} {'-' * 12} {'-' * 12}")
    print(f"  {'Ann. Return':<22} {ann_port * 100:>+11.2f}% {ann_bench * 100:>+11.2f}%")
    print(f"  {'Ann. Volatility':<22} {vol_port * 100:>11.2f}% {vol_bench * 100:>11.2f}%")
    print(f"  {'Sharpe Ratio':<22} {sharpe_port:>12.3f} {sharpe_bench:>12.3f}")
    print(f"  {'Max Drawdown':<22} {dd_port * 100:>+11.2f}% {dd_bench * 100:>+11.2f}%")
    print(f"  {'Hit Rate vs Bench':<22} {hit_rate * 100:>11.1f}%")
    print(f"  {'Info Ratio':<22} {ir:>12.3f}")
    print(f"  {'Ann. Excess Return':<22} {ann_ex * 100:>+11.2f}%")

    print("\n  Monthly detail (date = month return earned):")
    print(f"  {'Date':<12} {'Port':>8} {'Bench':>8} {'Excess':>8} {'CumPort':>9} {'CumBench':>9}")
    print(f"  {'-' * 12} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 9} {'-' * 9}")
    for dt, row in results.iterrows():
        cp = cum_port.loc[dt]
        cb = cum_bench.loc[dt]
        print(
            f"  {dt.strftime('%Y-%m-%d'):<12} "
            f"{row['port_return'] * 100:>+7.2f}% "
            f"{row['bench_return'] * 100:>+7.2f}% "
            f"{row['excess_return'] * 100:>+7.2f}% "
            f"{cp:>9.4f} "
            f"{cb:>9.4f}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading blended weights ...")
    weights = load_blended_weights()
    print(f"  {len(weights)} months, {METHOD} method")

    print("Loading factor signals ...")
    signals = load_factor_signals()

    print("Loading monthly returns ...")
    monthly_ret = load_monthly_returns(PRICE_FILE)

    print("Loading Nifty500 index returns ...")
    nifty_df = pd.read_parquet(BASE_DIR / "data" / "nifty500_hmm_data.parquet")
    nifty_ret = nifty_df["monthly_return"]
    nifty_ret.index = pd.to_datetime(nifty_ret.index)
    print(f"  Nifty500: {nifty_ret.index[0].date()} to {nifty_ret.index[-1].date()}")

    print(f"\nRunning OOS backtest: {OOS_START} to {OOS_END} ...")
    results, holdings = run_backtest(weights, signals, monthly_ret, nifty_ret)

    if results.empty:
        print("ERROR: no results produced")
        return

    print_summary(results)

    results.to_parquet(OUTPUT_FILE)
    results.to_csv(OUTPUT_SUMMARY)
    holdings.to_csv(OUTPUT_HOLDINGS, index=False)

    print("\nSaved:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {OUTPUT_SUMMARY}")
    print(f"  {OUTPUT_HOLDINGS}")
    print("Done.")


if __name__ == "__main__":
    main()

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
backtest_single_factor.py
=========================
OOS Single-Factor Portfolio Backtest — comparison against blended

For each factor, pick top 25 stocks by that factor's signal alone.
Equal weight. Same OOS period as blended backtest.
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
BACKTEST_DIR = Path(__file__).parent

PRICE_FILE = DATA_DIR / "prices_hmm_daily.parquet"
BLENDED_RESULTS = BACKTEST_DIR / "oos_backtest_results.parquet"
OUTPUT_SUMMARY = BACKTEST_DIR / "oos_single_factor_comparison.csv"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OOS_START = "2024-07"
OOS_END = "2026-06"
TOP_N = 25

# factor_name: (file, score_col, higher_is_better)
FACTORS = {
    "MOM": ("factor_mom.parquet", "percentile", True),
    "BAB": ("factor_bab.parquet", "percentile", True),  # already inverted
    "RMW_ROE": ("factor_rmw.parquet", "score_combined_roe", True),
    "VALUE": ("factor_value.parquet", "score_combined", True),
    "LOWVOL": ("factor_lowvol.parquet", "percentile", True),  # already inverted
    "SIZE": ("factor_size.parquet", "score", True),
}


# ---------------------------------------------------------------------------
# Load helpers
# ---------------------------------------------------------------------------
def load_monthly_returns() -> pd.DataFrame:
    prices = pd.read_parquet(PRICE_FILE)
    prices["date"] = pd.to_datetime(prices["date"])
    monthly = prices.groupby(["symbol", pd.Grouper(key="date", freq="ME")])["close"].last().unstack("symbol")
    return monthly.pct_change()


def load_nifty_returns() -> pd.Series:
    nifty = pd.read_parquet(DATA_DIR / "nifty500_hmm_data.parquet")
    s = nifty["monthly_return"].copy()
    s.index = pd.to_datetime(s.index)
    return s


def load_signal(fname: str, score_col: str) -> pd.Series:
    df = pd.read_parquet(FACTORS_DIR / fname)
    df["date"] = pd.to_datetime(df["date"])
    df = df[["nse_ticker", "date", score_col]].rename(columns={score_col: "score"})
    # Dedup
    df = df.sort_values("score", ascending=False).drop_duplicates(["nse_ticker", "date"])
    return df.set_index(["date", "nse_ticker"])["score"]


# ---------------------------------------------------------------------------
# Run single factor backtest
# ---------------------------------------------------------------------------
def run_single_factor(
    signal_series: pd.Series,
    monthly_ret: pd.DataFrame,
    nifty_ret: pd.Series,
    higher_is_better: bool = True,
) -> pd.DataFrame:

    periods = pd.period_range(start=OOS_START, end=OOS_END, freq="M")
    signal_dates = [p.to_timestamp(how="end").normalize() for p in periods]
    ret_idx = monthly_ret.index
    records = []

    for signal_date in signal_dates:
        candidates = ret_idx[ret_idx <= signal_date + pd.offsets.Day(5)]
        if candidates.empty:
            continue
        t_end = candidates[-1]

        pos = ret_idx.get_loc(t_end)
        if pos >= len(ret_idx) - 1:
            continue
        t1_end = ret_idx[pos + 1]

        # Get signal for this month
        avail_dates = signal_series.index.get_level_values("date").unique()
        avail_dates = avail_dates[avail_dates <= t_end]
        if avail_dates.empty:
            continue
        t_sig = avail_dates[-1]
        sig = signal_series.loc[t_sig]

        if len(sig) < TOP_N:
            continue

        # Pick top N
        top_stocks = sig.nlargest(TOP_N).index.tolist() if higher_is_better else sig.nsmallest(TOP_N).index.tolist()

        avail = [s for s in top_stocks if s in monthly_ret.columns]
        rets = monthly_ret.loc[t1_end, avail].dropna()
        if rets.empty:
            continue

        port_ret = rets.mean()
        bench_ret = nifty_ret.get(t1_end, np.nan)

        records.append(
            {
                "date": t1_end,
                "port_return": port_ret,
                "bench_return": bench_ret,
                "excess_return": port_ret - bench_ret,
            }
        )

    return pd.DataFrame(records).set_index("date")


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------
def get_stats(df: pd.DataFrame, col: str = "port_return") -> dict:
    r = df[col].dropna()
    ann_ret = r.mean() * 12
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    drawdown = (cum / cum.cummax() - 1).min()
    hit = (df["excess_return"] > 0).mean()
    ex = df["excess_return"].dropna()
    ann_ex = ex.mean() * 12
    vol_ex = ex.std() * np.sqrt(12)
    ir = ann_ex / vol_ex if vol_ex > 0 else 0
    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": drawdown,
        "hit_rate": hit,
        "ann_ex": ann_ex,
        "ir": ir,
        "cum_ret": cum.iloc[-1] - 1,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Loading monthly returns ...")
    monthly_ret = load_monthly_returns()

    print("Loading Nifty500 returns ...")
    nifty_ret = load_nifty_returns()

    print("Loading blended results ...")
    blended = pd.read_parquet(BLENDED_RESULTS)

    print("\nRunning single-factor backtests ...")
    all_results = {"BLENDED": blended}

    for factor, (fname, score_col, higher) in FACTORS.items():
        print(f"  {factor} ...")
        sig = load_signal(fname, score_col)
        res = run_single_factor(sig, monthly_ret, nifty_ret, higher)
        all_results[factor] = res

    # ── Summary table ────────────────────────────────────────────────────────
    rows = []
    for name, df in all_results.items():
        s = get_stats(df)
        rows.append({"Strategy": name, **s})

    summary = pd.DataFrame(rows).set_index("Strategy")

    print(f"\n{'=' * 75}")
    print(f"OOS COMPARISON: BLENDED vs SINGLE FACTOR  ({OOS_START} to {OOS_END})")
    print(f"{'=' * 75}")
    print(
        f"  {'Strategy':<12} {'Ann Ret':>8} {'Vol':>7} {'Sharpe':>8} {'MaxDD':>8} "
        f"{'Hit%':>6} {'Ann Ex':>8} {'IR':>7} {'CumRet':>8}"
    )
    print(f"  {'-' * 12} {'-' * 8} {'-' * 7} {'-' * 8} {'-' * 8} {'-' * 6} {'-' * 8} {'-' * 7} {'-' * 8}")
    for name, row in summary.iterrows():
        print(
            f"  {name:<12} "
            f"{row['ann_ret'] * 100:>+7.2f}% "
            f"{row['ann_vol'] * 100:>6.2f}% "
            f"{row['sharpe']:>8.3f} "
            f"{row['max_dd'] * 100:>+7.2f}% "
            f"{row['hit_rate'] * 100:>5.1f}% "
            f"{row['ann_ex'] * 100:>+7.2f}% "
            f"{row['ir']:>7.3f} "
            f"{row['cum_ret'] * 100:>+7.2f}%"
        )

    # ── Monthly returns side by side ─────────────────────────────────────────
    print(f"\n{'=' * 75}")
    print("MONTHLY RETURNS — all strategies")
    print(f"{'=' * 75}")
    cols = list(all_results.keys())
    header = f"  {'Date':<12}" + "".join(f"{c:>10}" for c in cols)
    print(header)
    print(f"  {'-' * 12}" + "".join(f"{'-' * 10}" for _ in cols))

    all_dates = sorted(set().union(*[df.index for df in all_results.values()]))
    for dt in all_dates:
        row_str = f"  {dt.strftime('%Y-%m-%d'):<12}"
        for name in cols:
            df = all_results[name]
            val = df.loc[dt, "port_return"] if dt in df.index else np.nan
            row_str += f"{val * 100:>+9.2f}%" if pd.notna(val) else f"{'n/a':>10}"
        print(row_str)

    summary.to_csv(OUTPUT_SUMMARY)
    print(f"\nSaved -> {OUTPUT_SUMMARY}")
    print("Done.")


if __name__ == "__main__":
    main()

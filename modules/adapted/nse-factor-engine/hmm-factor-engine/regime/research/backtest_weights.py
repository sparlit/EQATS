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


# Backtest: regime-conditional factor weights → blended stock portfolio
# Window : 2024-07 to 2026-06 (OOS for weights)
# Method : percentile rank all factors per month, blend by regime weights,
#          pick top 20 stocks, equal weight, hold 1 month

import json
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path("/home/ec2-user/nse-factor-engine/hmm-factor-engine")
PRICE_FILE = BASE_DIR / "data/prices_hmm_daily.parquet"
FORWARD_F = BASE_DIR / "regime/models/hmm_forward_probs_202001_202606.parquet"
WEIGHTS_F = BASE_DIR / "regime/weight_matrix.json"

BACKTEST_START = "2024-07"
BACKTEST_END = "2026-05"  # returns measured next month, so last signal month = 2026-05
TOP_N = 20

# ── Factor signal files and score columns ─────────────────────────────────────
FACTOR_SIGNALS = {
    "mom": (BASE_DIR / "factors/data/factor_mom.parquet", "percentile"),
    "lowvol": (BASE_DIR / "factors/data/factor_lowvol.parquet", "percentile"),
    "bab": (BASE_DIR / "factors/data/factor_bab.parquet", "percentile"),
    "rmw_roe": (BASE_DIR / "factors/data/factor_rmw.parquet", "score_combined_roe"),
    "rmw_op_roe": (BASE_DIR / "factors/data/factor_rmw.parquet", "score_combined_op_roe"),
    "quality": (BASE_DIR / "factors/data/factor_quality.parquet", "score_combined"),
    "value": (BASE_DIR / "factors/data/factor_value.parquet", "score_combined"),
    "size": (BASE_DIR / "factors/data/factor_size.parquet", "score"),
}

METHODS = ["erc", "sharpe_erc", "mvo_sample", "mvo_shrink"]

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading prices ...")
daily = pd.read_parquet(PRICE_FILE)
daily.index = pd.to_datetime(daily.index)
monthly = daily.resample("ME").last()

print("Loading regime labels ...")
forward = pd.read_parquet(FORWARD_F)[["regime"]]
forward.index = pd.to_datetime(forward.index).to_period("M")

print("Loading weight matrix ...")
wm = json.load(open(WEIGHTS_F))["all_methods"]

print("Loading factor signals ...")
signals_raw = {}
loaded_files = {}
for factor, (fpath, col) in FACTOR_SIGNALS.items():
    key = str(fpath)
    if key not in loaded_files:
        df = pd.read_parquet(fpath)
        df["date"] = pd.to_datetime(df["date"]).dt.to_period("M")
        loaded_files[key] = df
    signals_raw[factor] = (loaded_files[key], col)

# ── Backtest loop ─────────────────────────────────────────────────────────────
periods = pd.period_range(start=BACKTEST_START, end=BACKTEST_END, freq="M")

all_records = {m: [] for m in METHODS}

for period in periods:
    next_period = period + 1

    # Regime for this month
    if period not in forward.index:
        continue
    regime = forward.loc[period, "regime"]

    # Next month prices for return calculation
    curr_end = period.to_timestamp(how="end").normalize()
    next_end = next_period.to_timestamp(how="end").normalize()

    candidates_curr = monthly.index[monthly.index <= curr_end + pd.offsets.Day(5)]
    candidates_next = monthly.index[monthly.index <= next_end + pd.offsets.Day(5)]
    if candidates_curr.empty or candidates_next.empty:
        continue
    t0 = candidates_curr[-1]
    t1 = candidates_next[-1]
    if t0 == t1:
        continue

    # ── Build per-stock composite score ──────────────────────────────────────
    # Get all stocks with signals this month, compute percentile per factor
    stock_scores = {}  # factor -> pd.Series(ticker -> percentile)

    for factor, (df, col) in signals_raw.items():
        month_data = df[df["date"] == period][["nse_ticker", col]].dropna()
        if month_data.empty:
            continue
        month_data = month_data.set_index("nse_ticker")[col]
        # Convert to percentile rank (0-1), higher = better for long
        if factor in ("lowvol", "bab"):
            pct = month_data.rank(pct=True)  # already inverted at signal creation
        elif factor == "size":
            pct = 1 - month_data.rank(pct=True)  # smaller size = better
        else:
            pct = month_data.rank(pct=True)
        stock_scores[factor] = pct

    if not stock_scores:
        continue

    # Common universe — stocks present in at least half the active factors
    all_tickers = pd.Index(set.union(*[set(s.index) for s in stock_scores.values()]))

    for method in METHODS:
        weights = wm[method][regime]

        # Weighted composite score
        composite = pd.Series(0.0, index=all_tickers)
        total_w = 0.0
        for factor, w in weights.items():
            if w == 0 or factor not in stock_scores:
                continue
            aligned = stock_scores[factor].reindex(all_tickers).fillna(0.5)
            composite += w * aligned
            total_w += w

        if total_w == 0:
            continue
        composite /= total_w

        # Top N stocks
        top_stocks = composite.nlargest(TOP_N).index.tolist()
        if not top_stocks:
            continue

        # Equal weight return next month
        rets = []
        for ticker in top_stocks:
            if ticker in monthly.columns:
                p0 = monthly.loc[t0, ticker]
                p1 = monthly.loc[t1, ticker]
                if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                    rets.append((p1 / p0) - 1)

        if not rets:
            continue

        all_records[method].append(
            {
                "date": str(period),
                "regime": regime,
                "portfolio_return": np.mean(rets),
                "n_stocks": len(rets),
                "top_stocks": ",".join(top_stocks[:5]),  # first 5 for audit
            }
        )

# ── Results ───────────────────────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print(f"  BACKTEST RESULTS  {BACKTEST_START} → {BACKTEST_END}  (OOS)")
print(f"{'=' * 70}")
print(f"  {'Method':<14} {'Months':>7} {'Ann Ret':>9} {'Sharpe':>8} {'Hit Rate':>10} {'Cum Ret':>9}")
print(f"  {'-' * 14} {'-' * 7} {'-' * 9} {'-' * 8} {'-' * 10} {'-' * 9}")

for method in METHODS:
    records = all_records[method]
    if not records:
        print(f"  {method:<14}  no data")
        continue
    df = pd.DataFrame(records)
    r = df["portfolio_return"]
    ann_ret = r.mean() * 12
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    hit_rate = (r > 0).mean()
    cum_ret = (1 + r).prod() - 1
    print(
        f"  {method:<14} {len(r):>7} {ann_ret * 100:>+8.2f}% {sharpe:>+8.3f} {hit_rate * 100:>9.1f}% {cum_ret * 100:>+8.2f}%"
    )

# ── Monthly detail for best method ───────────────────────────────────────────
print("\n--- Monthly detail (mvo_shrink) ---")
df = pd.DataFrame(all_records["mvo_shrink"])
if not df.empty:
    print(f"  {'Date':<10} {'Regime':<10} {'Return':>8} {'N':>4} {'Top 5 stocks'}")
    print(f"  {'-' * 10} {'-' * 10} {'-' * 8} {'-' * 4} {'-' * 40}")
    for _, row in df.iterrows():
        print(
            f"  {row['date']:<10} {row['regime']:<10} {row['portfolio_return'] * 100:>+7.2f}% {int(row['n_stocks']):>4}  {row['top_stocks']}"
        )

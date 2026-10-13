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
Stage 3 Step 5 — Residual Momentum

Formula:
    stock_daily_log_ret = β1(market_daily_log_ret) + β2(sector_daily_log_ret) + ε
    residual_momentum   = sum(ε) over formation window

    No intercept — sum of residuals is non-trivially zero only without α.
    Market  = equal-weighted mean log return of all 500 symbols each day, excluding self
    Sector  = equal-weighted mean log return of same-industry symbols each day, excluding self
    JSWDULUX has null industry → market-only OLS (no β2)

Parameters:
    MIN_DAYS = 100  → symbols with fewer rows in window → NaN
    MAX_DAYS = 251  → use at most this many most-recent rows per symbol

Run from: /home/ec2-user/nse-factor-engine/
    python3 signals/stage3/stage3_step5_residual_momentum.py
"""

import numpy as np
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"
MIN_DAYS = 100
MAX_DAYS = 251

# ── Load ───────────────────────────────────────────────────────────────────
prices = pd.read_parquet(f"{BASE}/data/prices.parquet")
meta = pd.read_parquet(f"{BASE}/data/universe_metadata.parquet")

# ── Resolve T ──────────────────────────────────────────────────────────────
date_counts = prices.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
all_dates = sorted(prices[prices["date"] <= T]["date"].unique())
T_21 = all_dates[-22]
T_252 = all_dates[-253]
print(f"T={T.date()}  T-21={T_21.date()}  T-252={T_252.date()}")

# ── Window: T-252 → T-21 ──────────────────────────────────────────────────
win = (
    prices[(prices["date"] >= T_252) & (prices["date"] <= T_21)][["symbol", "date", "close"]]
    .copy()
    .sort_values(["symbol", "date"])
)

# ── Log returns ────────────────────────────────────────────────────────────
win["log_ret"] = win.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
win = win.dropna(subset=["log_ret"])


# ── Apply MAX_DAYS per symbol ──────────────────────────────────────────────
def tail_max(df):
    return df.sort_values("date").tail(MAX_DAYS)


win = win.groupby("symbol", group_keys=False).apply(tail_max).reset_index(drop=True)
print(f"Win shape after MAX_DAYS trim: {win.shape}")

# ── Pivot to wide: rows=date, cols=symbol, values=log_ret ─────────────────
wide = win.pivot(index="date", columns="symbol", values="log_ret")
print(f"Wide shape: {wide.shape}")

# ── Sector mapping ─────────────────────────────────────────────────────────
sym_industry = meta.set_index("symbol")["industry"]
ind_map = sym_industry.reindex(wide.columns)

# ── Precompute market sum and count per date ───────────────────────────────
market_sum = wide.sum(axis=1, skipna=True)
market_count = wide.notna().sum(axis=1)

# ── OLS per symbol (no intercept) ─────────────────────────────────────────
print("Running OLS per symbol...")
results = {}

for sym in wide.columns:
    ind = ind_map[sym]
    sym_series = wide[sym].dropna()

    if len(sym_series) < MIN_DAYS:
        results[sym] = (np.nan, np.nan, np.nan)
        continue

    sym_series = sym_series.iloc[-MAX_DAYS:]
    dates_used = sym_series.index

    # Market return excluding self
    self_val = wide.loc[dates_used, sym]
    mkt_sum_excl = market_sum.reindex(dates_used) - self_val.fillna(0)
    mkt_cnt_excl = market_count.reindex(dates_used) - self_val.notna().astype(int)
    mkt = mkt_sum_excl / mkt_cnt_excl

    if pd.isna(ind):
        # JSWDULUX: market-only OLS, no intercept
        sub = pd.DataFrame(
            {
                "log_ret": sym_series,
                "market_ret": mkt,
            }
        ).dropna()
        if len(sub) < MIN_DAYS:
            results[sym] = (np.nan, np.nan, np.nan)
            continue
        X = sub[["market_ret"]].values
        y = sub["log_ret"].values
        coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        residuals = y - X @ coefs
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum(y**2)  # no intercept: ss_tot uses raw y
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        results[sym] = (residuals.sum(), r2, len(sub))
        continue

    # Sector return excluding self
    peers = [s for s in wide.columns if ind_map[s] == ind and s != sym]
    if len(peers) == 0:
        sub = pd.DataFrame(
            {
                "log_ret": sym_series,
                "market_ret": mkt,
            }
        ).dropna()
        if len(sub) < MIN_DAYS:
            results[sym] = (np.nan, np.nan, np.nan)
            continue
        X = sub[["market_ret"]].values
        y = sub["log_ret"].values
        coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        residuals = y - X @ coefs
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum(y**2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        results[sym] = (residuals.sum(), r2, len(sub))
        continue

    peer_wide = wide.loc[dates_used, peers]
    sect = peer_wide.mean(axis=1, skipna=True)

    sub = pd.DataFrame(
        {
            "log_ret": sym_series,
            "market_ret": mkt,
            "sector_ret": sect,
        }
    ).dropna()

    if len(sub) < MIN_DAYS:
        results[sym] = (np.nan, np.nan, np.nan)
        continue

    X = np.column_stack([sub["market_ret"].values, sub["sector_ret"].values])
    y = sub["log_ret"].values
    coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    residuals = y - X @ coefs
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum(y**2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    results[sym] = (residuals.sum(), r2, len(sub))

# ── Assemble ───────────────────────────────────────────────────────────────
res_df = (
    pd.DataFrame.from_dict(results, orient="index", columns=["residual_momentum", "r2", "n_obs"])
    .rename_axis("symbol")
    .reset_index()
    .sort_values("symbol")
    .reset_index(drop=True)
)

# ── Sanity checks ──────────────────────────────────────────────────────────
print("\n=== Sanity Checks ===")
print(f"Total symbols        : {len(res_df)}")
print(f"NaN residual_momentum: {res_df['residual_momentum'].isna().sum()}")
print(f"Non-NaN              : {res_df['residual_momentum'].notna().sum()}")

print("\nresidual_momentum distribution:")
print(res_df["residual_momentum"].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).to_string())

print("\nr2 distribution:")
print(res_df["r2"].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).to_string())

print("\nLow R2 symbols (r2 < 0.05):")
print(
    res_df[res_df["r2"] < 0.05][["symbol", "residual_momentum", "r2", "n_obs"]].to_string(
        index=False
    )
)

print("\nTop 5 residual momentum:")
print(
    res_df.nlargest(5, "residual_momentum")[
        ["symbol", "residual_momentum", "r2", "n_obs"]
    ].to_string(index=False)
)

print("\nBottom 5 residual momentum:")
print(
    res_df.nsmallest(5, "residual_momentum")[
        ["symbol", "residual_momentum", "r2", "n_obs"]
    ].to_string(index=False)
)

print("\nJSWDULUX (market-only OLS):")
print(res_df[res_df["symbol"] == "JSWDULUX"].to_string(index=False))

print("\nENRIN:")
print(res_df[res_df["symbol"] == "ENRIN"].to_string(index=False))

print("\nNaN symbols:")
print(sorted(res_df[res_df["residual_momentum"].isna()]["symbol"].tolist()))

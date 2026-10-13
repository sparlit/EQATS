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
Stage 3 — Metric: Residual Momentum

Formula : stock_log_ret = β1(market_log_ret) + β2(sector_log_ret) + ε
          residual_momentum = sum(ε) over window
No intercept. Market and sector both exclude self.
JSWDULUX (null industry) → market-only OLS.

Inputs : window (prices T-252 → T-21), meta (universe_metadata)
Returns: dataframe with columns [symbol, residual_momentum, rm_r2, rm_n_obs]
"""

import numpy as np
import pandas as pd

MIN_DAYS = 100
MAX_DAYS = 251


def compute(window: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    rm_win = window[["symbol", "date", "close"]].copy()
    rm_win["log_ret"] = rm_win.groupby("symbol")["close"].transform(
        lambda x: np.log(x / x.shift(1))
    )
    rm_win = rm_win.dropna(subset=["log_ret"])

    def tail_max(df):
        return df.sort_values("date").tail(MAX_DAYS)

    rm_win = rm_win.groupby("symbol", group_keys=False).apply(tail_max).reset_index(drop=True)

    wide = rm_win.pivot(index="date", columns="symbol", values="log_ret")

    sym_industry = meta.set_index("symbol")["industry"]
    ind_map = sym_industry.reindex(wide.columns)

    market_sum = wide.sum(axis=1, skipna=True)
    market_count = wide.notna().sum(axis=1)

    results = {}
    for sym in wide.columns:
        ind = ind_map[sym]
        sym_series = wide[sym].dropna()

        if len(sym_series) < MIN_DAYS:
            results[sym] = (np.nan, np.nan, np.nan)
            continue

        sym_series = sym_series.iloc[-MAX_DAYS:]
        dates_used = sym_series.index

        self_val = wide.loc[dates_used, sym]
        mkt_sum_excl = market_sum.reindex(dates_used) - self_val.fillna(0)
        mkt_cnt_excl = market_count.reindex(dates_used) - self_val.notna().astype(int)
        mkt = mkt_sum_excl / mkt_cnt_excl

        if pd.isna(ind):
            sub = pd.DataFrame({"log_ret": sym_series, "market_ret": mkt}).dropna()
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

        peers = [s for s in wide.columns if ind_map[s] == ind and s != sym]
        if len(peers) == 0:
            sub = pd.DataFrame({"log_ret": sym_series, "market_ret": mkt}).dropna()
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

    return (
        pd.DataFrame.from_dict(
            results, orient="index", columns=["residual_momentum", "rm_r2", "rm_n_obs"]
        )
        .rename_axis("symbol")
        .reset_index()
    )

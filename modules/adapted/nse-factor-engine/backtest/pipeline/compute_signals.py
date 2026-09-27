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
Backtest Pipeline — compute_signals(prices, meta, T)

Single function that replicates Stage 2-5 signal logic for an arbitrary
historical date T. Called 511 times by run_historical_pipeline.py.

Inputs:
    prices : full prices_backtest.parquet (all symbols, all dates)
    meta   : universe_metadata_backtest.parquet (symbol, company_name, industry, market_cap_cr)
    T      : pd.Timestamp — the Friday rebalance date to compute signals for

Output:
    pd.DataFrame — one row per symbol, all signal columns + in_universe flag

Key differences from production pipeline:
    - passes_mktcap skipped (all 991 symbols > 500cr floor)
    - in_universe = passes_adtv only (63d ADTV > 10cr at T)
    - industry from yfinance sector (coarser than NSE classification)
    - symbol has .NS suffix throughout
    - no file I/O — pure in-memory computation
"""

import numpy as np
import pandas as pd

RF = 0.07
ADTV_FLOOR = 10  # cr
ADTV_WINDOW = 63
MIN_DAYS = 100
MAX_DAYS = 251
TOP_N_FIP = 100


# ── Helpers ───────────────────────────────────────────────────────────────────


def _realised_vol(lr, ddof=1):
    return np.std(lr, ddof=ddof) * np.sqrt(252) if len(lr) >= ddof + 1 else np.nan


def _downside_vol(lr, ddof=1):
    neg = lr[lr < 0]
    return np.std(neg, ddof=ddof) * np.sqrt(252) if len(neg) >= ddof + 1 else np.nan


def _safe_div(num, den):
    return num / den if not (pd.isna(num) or pd.isna(den) or den == 0) else np.nan


def _pct_ret(end, start):
    return (end - start) / start if not (pd.isna(end) or pd.isna(start) or start == 0) else np.nan


# ── Main function ─────────────────────────────────────────────────────────────


def compute_signals(prices: pd.DataFrame, meta: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """
    prices : full prices dataframe (all symbols, all dates)
    meta   : universe_metadata_backtest dataframe
    T      : rebalance Friday (pd.Timestamp)

    Returns: signals dataframe, one row per symbol
    """

    # ── Step 0: slice price history up to T ──────────────────────────────────
    px = prices[prices["date"] <= T]
    px = px.sort_values(["symbol", "date"]).reset_index(drop=True)

    # sorted trading dates up to T
    all_dates = sorted(px["date"].unique())

    T_pos = all_dates.index(T)  # index of T in all_dates
    T_21 = all_dates[T_pos - 21]  # T-21 trading days
    T_7 = all_dates[T_pos - 7]  # T-7 trading days
    all_dates[T_pos - 63]  # T-63 (lottery window anchor)
    T_64 = all_dates[T_pos - 64]  # T-64 (anchor close for lottery)
    all_dates[T_pos - 126]  # T-126 (6m)
    T_252 = all_dates[T_pos - 252]  # T-252 (12m)

    # formation window T-252 → T-21 (used by Stage 3 metrics)
    window = px[(px["date"] >= T_252) & (px["date"] <= T_21)].copy()

    # ── Step 1: ADTV — in_universe gate ──────────────────────────────────────
    adtv_window = px[px["date"] > all_dates[T_pos - ADTV_WINDOW]].copy()
    adtv_window["daily_value_cr"] = adtv_window["close"] * adtv_window["volume"] / 1e7
    adtv = adtv_window.groupby("symbol")["daily_value_cr"].mean().rename("adtv_63_cr").reset_index()
    adtv["passes_adtv"] = adtv["adtv_63_cr"] >= ADTV_FLOOR
    adtv["in_universe"] = adtv["passes_adtv"]

    # ── Step 2: Stage 2 — momentum core ──────────────────────────────────────
    records = []
    for sym, grp in px.groupby("symbol"):
        closes = grp.sort_values("date")["close"].values
        dates = grp.sort_values("date")["date"].values
        n = len(dates)

        # find T index within this symbol's own date series
        t_idx = np.searchsorted(dates, np.datetime64(T))
        if t_idx >= n or dates[t_idx] != np.datetime64(T):
            continue  # symbol has no data at T — skip

        def _get_close(offset):
            idx = t_idx - offset
            return closes[idx] if idx >= 0 else np.nan

        ret_12m1m = _pct_ret(_get_close(21), _get_close(252))
        ret_6m1m = _pct_ret(_get_close(21), _get_close(126))
        ret_3m1m = _pct_ret(_get_close(21), _get_close(63))

        # vol_252: T-252 → T
        s252 = t_idx - 252
        if s252 >= 0:
            sl = closes[s252 : t_idx + 1]
            lr = np.log(sl[1:] / sl[:-1])
            v_252 = _realised_vol(lr)
            dv_252 = _downside_vol(lr)
        else:
            v_252 = dv_252 = np.nan

        # vol_231: T-252 → T-21
        s231, e231 = t_idx - 252, t_idx - 21
        if s231 >= 0 and e231 > s231:
            sl = closes[s231 : e231 + 1]
            lr = np.log(sl[1:] / sl[:-1])
            v_231 = _realised_vol(lr)
            dv_231 = _downside_vol(lr)
        else:
            v_231 = dv_231 = np.nan

        vol_adj_ret = _safe_div(ret_12m1m, v_231)
        sharpe_style = _safe_div(ret_12m1m - RF, v_231)
        sortino_style = _safe_div(ret_12m1m - RF, dv_231)

        records.append(
            {
                "symbol": sym,
                "as_of_date": T,
                "ret_12m1m": ret_12m1m,
                "ret_6m1m": ret_6m1m,
                "ret_3m1m": ret_3m1m,
                "vol_252": v_252,
                "vol_231": v_231,
                "downside_vol_252": dv_252,
                "downside_vol_231": dv_231,
                "simple_vol_adj_momentum": vol_adj_ret,
                "sharpe_style_momentum": sharpe_style,
                "sortino_style_momentum": sortino_style,
            }
        )

    signals = pd.DataFrame(records)

    # ── Step 3: Stage 3 — momentum quality ───────────────────────────────────

    # FIP
    wr = window.copy()
    wr["log_ret"] = wr.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
    wr = wr.dropna(subset=["log_ret"])

    def _fip_components(group):
        total = len(group)
        if total == 0:
            return pd.Series({"pct_pos_days": np.nan, "pct_neg_days": np.nan})
        pos = (group["log_ret"] > 0).sum()
        neg = (group["log_ret"] < 0).sum()
        return pd.Series({"pct_pos_days": pos / total, "pct_neg_days": neg / total})

    fip_df = wr.groupby("symbol", group_keys=False).apply(_fip_components, include_groups=False).reset_index()
    fip_df = fip_df.merge(signals[["symbol", "ret_12m1m"]], on="symbol", how="left")
    fip_df["fip_score"] = np.sign(fip_df["ret_12m1m"]) * (fip_df["pct_neg_days"] - fip_df["pct_pos_days"])

    # Smoothness
    def _smoothness(group):
        group = group.reset_index(drop=True)
        n = len(group)
        complete_weeks = n // 5
        if complete_weeks == 0:
            return pd.Series({"smoothness": np.nan})
        pos_weeks = sum(1 for i in range(complete_weeks) if group.loc[i * 5 + 4, "close"] > group.loc[i * 5, "open"])
        return pd.Series({"smoothness": pos_weeks / complete_weeks})

    smooth_df = window.groupby("symbol", group_keys=False).apply(_smoothness, include_groups=False).reset_index()

    # 52w proximity
    close_T = px[px["date"] == T][["symbol", "close"]].rename(columns={"close": "close_T"})
    high_52w = (
        px[(px["date"] >= T_252) & (px["date"] <= T)]
        .groupby("symbol")["high"]
        .max()
        .reset_index()
        .rename(columns={"high": "high_52w"})
    )
    prox_df = close_T.merge(high_52w, on="symbol", how="left")
    prox_df["proximity_52w_high"] = prox_df["close_T"] / prox_df["high_52w"]

    # Residual momentum
    rm_win = window[["symbol", "date", "close"]].copy()
    rm_win["log_ret"] = rm_win.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
    rm_win = rm_win.dropna(subset=["log_ret"])
    rm_win = (
        rm_win.groupby("symbol", group_keys=False)
        .apply(lambda df: df.sort_values("date").tail(MAX_DAYS))
        .reset_index(drop=True)
    )
    wide = rm_win.pivot(index="date", columns="symbol", values="log_ret")
    sym_ind = meta.set_index("symbol")["industry"]
    ind_map = pd.Series({sym: sym_ind.get(sym, np.nan) for sym in wide.columns})
    mkt_sum = wide.sum(axis=1, skipna=True)
    mkt_count = wide.notna().sum(axis=1)
    rm_results = {}
    for sym in wide.columns:
        ind = ind_map[sym]
        sym_series = wide[sym].dropna()
        if len(sym_series) < MIN_DAYS:
            rm_results[sym] = (np.nan, np.nan, np.nan)
            continue
        sym_series = sym_series.iloc[-MAX_DAYS:]
        dates_used = sym_series.index
        self_val = wide.loc[dates_used, sym]
        mkt_sum_excl = mkt_sum.reindex(dates_used) - self_val.fillna(0)
        mkt_cnt_excl = mkt_count.reindex(dates_used) - self_val.notna().astype(int)
        mkt = mkt_sum_excl / mkt_cnt_excl
        if pd.isna(ind):
            sub = pd.DataFrame({"log_ret": sym_series, "market_ret": mkt}).dropna()
            if len(sub) < MIN_DAYS:
                rm_results[sym] = (np.nan, np.nan, np.nan)
                continue
            X = sub[["market_ret"]].values
            y = sub["log_ret"].values
            coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            residuals = y - X @ coefs
            ss_res = np.sum(residuals**2)
            ss_tot = np.sum(y**2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
            rm_results[sym] = (residuals.sum(), r2, len(sub))
            continue
        peers = [s for s in wide.columns if ind_map.get(s) == ind and s != sym]
        if len(peers) == 0:
            sub = pd.DataFrame({"log_ret": sym_series, "market_ret": mkt}).dropna()
            if len(sub) < MIN_DAYS:
                rm_results[sym] = (np.nan, np.nan, np.nan)
                continue
            X = sub[["market_ret"]].values
            y = sub["log_ret"].values
            coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            residuals = y - X @ coefs
            ss_res = np.sum(residuals**2)
            ss_tot = np.sum(y**2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
            rm_results[sym] = (residuals.sum(), r2, len(sub))
            continue
        peer_wide = wide.loc[dates_used, peers]
        sect = peer_wide.mean(axis=1, skipna=True)
        sub = pd.DataFrame({"log_ret": sym_series, "market_ret": mkt, "sector_ret": sect}).dropna()
        if len(sub) < MIN_DAYS:
            rm_results[sym] = (np.nan, np.nan, np.nan)
            continue
        X = np.column_stack([sub["market_ret"].values, sub["sector_ret"].values])
        y = sub["log_ret"].values
        coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        residuals = y - X @ coefs
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum(y**2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        rm_results[sym] = (residuals.sum(), r2, len(sub))

    rm_df = (
        pd.DataFrame.from_dict(rm_results, orient="index", columns=["residual_momentum", "rm_r2", "rm_n_obs"])
        .rename_axis("symbol")
        .reset_index()
    )

    # Leading industry
    li_win = window.copy()
    li_win["log_ret"] = li_win.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
    li_win = li_win.dropna(subset=["log_ret"])
    li_win["industry"] = li_win["symbol"].map(meta.set_index("symbol")["industry"])
    ind_cum_ret = (
        li_win.groupby(["industry", "date"])["log_ret"].mean().groupby("industry").sum().rename("industry_cum_ret")
    )
    ind_rank = ind_cum_ret.rank(pct=True).rename("industry_rank")
    li_df = meta[["symbol"]].copy()
    _ind_map = meta.set_index("symbol")["industry"]
    li_df["industry_cum_ret"] = li_df["symbol"].map(_ind_map).map(ind_cum_ret)
    li_df["industry_rank"] = li_df["symbol"].map(_ind_map).map(ind_rank)

    # Weinstein
    ws_px = px[["symbol", "date", "close"]].copy()
    ws_px["week"] = ws_px["date"].dt.to_period("W")
    weekly = ws_px.groupby(["symbol", "week"])["close"].last().reset_index()
    weekly = weekly.sort_values(["symbol", "week"])
    weekly["ma30w"] = weekly.groupby("symbol")["close"].transform(lambda x: x.rolling(30, min_periods=20).mean())
    weekly["ma30w_prev"] = weekly.groupby("symbol")["ma30w"].transform(lambda x: x.shift(1))
    weekly["weinstein_stage2"] = (weekly["close"] > weekly["ma30w"]) & (weekly["ma30w"] > weekly["ma30w_prev"])
    ws_df = weekly.sort_values("week").groupby("symbol").last().reset_index()[["symbol", "weinstein_stage2"]]

    # 150-day SMA > 200-day SMA (daily, at T)
    ws_px["sma150"] = ws_px.groupby("symbol")["close"].transform(lambda x: x.rolling(150, min_periods=100).mean())
    ws_px["sma200"] = ws_px.groupby("symbol")["close"].transform(lambda x: x.rolling(200, min_periods=130).mean())
    sma_df = ws_px.sort_values("date").groupby("symbol").last().reset_index()[["symbol", "sma150", "sma200"]]
    sma_df["sma150_gt_sma200"] = sma_df["sma150"] > sma_df["sma200"]

    ws_df = ws_df.merge(sma_df[["symbol", "sma150_gt_sma200"]], on="symbol", how="left")
    ws_df["weinstein_stage2"] = ws_df["weinstein_stage2"] & ws_df["sma150_gt_sma200"]
    ws_df = ws_df[["symbol", "weinstein_stage2"]]

    # Relative strength
    rs_win = window.copy()
    rs_win["log_ret"] = rs_win.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
    rs_win = rs_win.dropna(subset=["log_ret"])
    sym_cum_ret = rs_win.groupby("symbol")["log_ret"].sum().rename("stock_cum_ret")
    market_cum_ret = rs_win.groupby("date")["log_ret"].mean().sum()
    rs_df = sym_cum_ret.reset_index()
    rs_df["rs_excess_ret_mkt"] = rs_df["stock_cum_ret"] - market_cum_ret
    rs_df["rs_rank_500"] = rs_df["stock_cum_ret"].rank(pct=True)

    # ── Step 4: Stage 4 — entry quality ──────────────────────────────────────

    # STPB
    close_T21 = px[px["date"] == T_21][["symbol", "close"]].rename(columns={"close": "close_T21"})
    close_T7 = px[px["date"] == T_7][["symbol", "close"]].rename(columns={"close": "close_T7"})
    stpb = close_T.merge(close_T21, on="symbol", how="outer").merge(close_T7, on="symbol", how="outer")
    stpb["stpb_ret_21d"] = (stpb["close_T"] - stpb["close_T21"]) / stpb["close_T21"]
    stpb["stpb_ret_7d"] = (stpb["close_T"] - stpb["close_T7"]) / stpb["close_T7"]
    ma_21 = px[(px["date"] > T_21) & (px["date"] <= T)].groupby("symbol")["close"].mean().rename("ma_21").reset_index()
    stpb = stpb.merge(ma_21, on="symbol", how="left")
    stpb["stpb_ma_distance_21d"] = (stpb["close_T"] - stpb["ma_21"]) / stpb["ma_21"]
    stpb = stpb.merge(signals[["symbol", "vol_231"]], on="symbol", how="left")
    stpb["stpb_zscore_21d"] = stpb["stpb_ret_21d"] / stpb["vol_231"]
    stpb["stpb_zscore_7d"] = stpb["stpb_ret_7d"] / stpb["vol_231"]
    stpb_out = stpb[
        ["symbol", "stpb_ret_21d", "stpb_ret_7d", "stpb_zscore_21d", "stpb_zscore_7d", "stpb_ma_distance_21d"]
    ]

    # Volume confirmation
    avg_vol_21 = (
        px[(px["date"] > T_21) & (px["date"] <= T)]
        .groupby("symbol")["volume"]
        .mean()
        .rename("avg_vol_21")
        .reset_index()
    )
    avg_vol_252 = (
        px[(px["date"] > T_252) & (px["date"] <= T)]
        .groupby("symbol")["volume"]
        .mean()
        .rename("avg_vol_252")
        .reset_index()
    )
    volconf = avg_vol_21.merge(avg_vol_252, on="symbol", how="outer")
    volconf["vol_ratio_21_252"] = volconf["avg_vol_21"] / volconf["avg_vol_252"]
    volconf = volconf.merge(stpb_out[["symbol", "stpb_ret_21d"]], on="symbol", how="left")
    volconf["volume_price_pos_move_confirmed"] = (volconf["stpb_ret_21d"] > 0) & (volconf["vol_ratio_21_252"] > 1.2)
    volconf_out = volconf[["symbol", "vol_ratio_21_252", "volume_price_pos_move_confirmed"]]

    # Lottery classifier
    lot_window = px[(px["date"] >= T_64) & (px["date"] <= T)].copy()
    lot_window = lot_window.sort_values(["symbol", "date"])
    lot_window["daily_ret"] = lot_window.groupby("symbol")["close"].pct_change()
    lot_rets = lot_window.dropna(subset=["daily_ret"]).copy()
    lot_rets["abs_ret"] = lot_rets["daily_ret"].abs()

    def _bucket_counts(g):
        return pd.Series(
            {
                "days_bw_15_20perc": (g["abs_ret"] >= 0.15).sum(),
                "days_bw_10_15perc": ((g["abs_ret"] >= 0.10) & (g["abs_ret"] < 0.15)).sum(),
                "days_bw_5_10perc": ((g["abs_ret"] >= 0.05) & (g["abs_ret"] < 0.10)).sum(),
                "days_bw_2_5perc": ((g["abs_ret"] >= 0.02) & (g["abs_ret"] < 0.05)).sum(),
            }
        )

    lot_df = lot_rets.groupby("symbol", group_keys=False).apply(_bucket_counts, include_groups=False).reset_index()
    conditions = [
        lot_df["days_bw_15_20perc"] > 2,
        lot_df["days_bw_15_20perc"] > 0,
        lot_df["days_bw_10_15perc"] > 0,
        lot_df["days_bw_5_10perc"] > 0,
        lot_df["days_bw_2_5perc"] > 0,
    ]
    choices = ["EXTREME LOTTERY", "LOTTERY", "BORDER_LOTTERY", "CAUTIOUS", "ALRIGHT"]
    lot_df["lottery_class"] = np.select(conditions, choices, default="BORING")

    # ── Step 5: Stage 5 — ranks ───────────────────────────────────────────────
    RANK_METRICS = [
        "ret_12m1m",
        "ret_6m1m",
        "ret_3m1m",
        "simple_vol_adj_momentum",
        "sharpe_style_momentum",
        "sortino_style_momentum",
    ]

    # assemble full signals before ranking
    out = signals.copy()
    out = out.merge(fip_df[["symbol", "fip_score", "pct_pos_days", "pct_neg_days"]], on="symbol", how="left")
    out = out.merge(smooth_df, on="symbol", how="left")
    out = out.merge(prox_df[["symbol", "proximity_52w_high"]], on="symbol", how="left")
    out = out.merge(rm_df, on="symbol", how="left")
    out = out.merge(li_df, on="symbol", how="left")
    out = out.merge(ws_df, on="symbol", how="left")
    out = out.merge(rs_df[["symbol", "stock_cum_ret", "rs_excess_ret_mkt", "rs_rank_500"]], on="symbol", how="left")
    out = out.merge(stpb_out, on="symbol", how="left")
    out = out.merge(volconf_out, on="symbol", how="left")
    out = out.merge(lot_df, on="symbol", how="left")
    out = out.merge(adtv[["symbol", "adtv_63_cr", "passes_adtv", "in_universe"]], on="symbol", how="left")

    # rs_excess_ret_industry = stock_cum_ret - industry_cum_ret (point-in-time sector comparison)
    out["rs_excess_ret_industry"] = out["stock_cum_ret"] - out["industry_cum_ret"]
    out = out.drop(columns=["stock_cum_ret"])

    # ranks — in-universe only
    in_univ = out[out["in_universe"]].copy()
    for metric in RANK_METRICS:
        rank_col = f"rank_{metric}"
        out.loc[out["in_universe"], rank_col] = (
            in_univ[metric].rank(method="min", ascending=False).astype("Int64").values
        )

    # rank_rs_excess_ret_mkt — cross-sectional rank within in_universe (kept for backward compat)
    out.loc[out["in_universe"], "rank_rs_excess_ret_mkt"] = (
        in_univ["rs_excess_ret_mkt"].rank(method="min", ascending=False).astype("Int64").values
    )

    # rank_alpha_12m1m_ew — new name for same computation as rank_rs_excess_ret_mkt
    out.loc[out["in_universe"], "rank_alpha_12m1m_ew"] = (
        in_univ["rs_excess_ret_mkt"].rank(method="min", ascending=False).astype("Int64").values
    )

    # FIP rerank — top 100 per metric
    for metric in RANK_METRICS:
        rank_col = f"rank_{metric}"
        fip_rank_col = f"rank_fip_{metric}"
        pool = out[out[rank_col] <= TOP_N_FIP].copy()
        if len(pool) > 0:
            fip_ranks = pool["fip_score"].rank(method="min", ascending=True).astype("Int64")
            out.loc[fip_ranks.index, fip_rank_col] = fip_ranks.values

    return out

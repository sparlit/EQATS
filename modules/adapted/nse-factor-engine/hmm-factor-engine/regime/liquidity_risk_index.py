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


from datetime import date

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BASE = "/home/ec2-user/nse-factor-engine"
DATA_DIR = f"{BASE}/hmm-factor-engine/data"
OUT_DIR = f"{BASE}/hmm-factor-engine/regime/data"

# Single source of truth for index OHLCV
INDEX_PARQUET = f"{BASE}/data/index_prices.parquet"

UNIVERSES = {
    "nifty500": ("^CRSLDX", f"{BASE}/nifty500_symbols.csv"),
    "nifty100": ("^CNX100", f"{BASE}/nifty100_symbols.csv"),
    "niftymidcap150": ("NIFTYMIDCAP150.NS", f"{BASE}/niftymidcap150_symbols.csv"),
    "niftysmallcap250": ("NIFTYSMLCAP250.NS", f"{BASE}/niftysmallcap250_symbols.csv"),
}

ROLL_SHORT = 21
ROLL_LONG = 252
ROLL_SKEW = 60
WINSOR_PCT = 99


# ═════════════════════════════════════════════
# SECTION 1 — DATA LOADING
# ═════════════════════════════════════════════


def load_data():
    print("Loading corporate action flags...")
    ca = pd.read_parquet(f"{DATA_DIR}/corporate_action_flags.parquet")
    ca.columns = ca.columns.str.strip().str.lower()
    excluded = set(ca["symbol"].tolist())
    print(f"  Excluded symbols: {excluded}")

    print("Loading prices...")
    prices = pd.read_parquet(f"{DATA_DIR}/prices_hmm_daily.parquet")
    prices.columns = prices.columns.str.strip().str.lower()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices[~prices["symbol"].isin(excluded)].copy()
    print(f"  Price shape after exclusions: {prices.shape}")

    print("Loading shares outstanding...")
    shares_df = pd.read_parquet(f"{DATA_DIR}/shares_outstanding.parquet")
    shares_df.columns = shares_df.columns.str.strip().str.lower()
    shares_df = shares_df.dropna(subset=["shares_outstanding"])
    shares_df = shares_df[~shares_df["symbol"].isin(excluded)]
    shares = shares_df.set_index("symbol")["shares_outstanding"]

    return prices, shares, excluded


def load_universe_members(csv_path, excluded):
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip().str.lower()
    members = set(df["symbol"].tolist()) - excluded
    print(f"  Members loaded: {len(members)}")
    return members


def pivot_prices(prices, members):
    px = prices[prices["symbol"].isin(members)].copy()
    px = px.sort_values(["symbol", "date"])
    close_w = px.pivot(index="date", columns="symbol", values="close")
    volume_w = px.pivot(index="date", columns="symbol", values="volume")
    high_w = px.pivot(index="date", columns="symbol", values="high")
    low_w = px.pivot(index="date", columns="symbol", values="low")
    returns_w = close_w.pct_change(fill_method=None)
    return {
        "close": close_w,
        "volume": volume_w,
        "high": high_w,
        "low": low_w,
        "returns": returns_w,
    }


# ═════════════════════════════════════════════
# SECTION 2 — HELPERS
# ═════════════════════════════════════════════


def rolling_zscore(s, window=ROLL_LONG):
    m = s.rolling(window, min_periods=window // 2).mean()
    sd = s.rolling(window, min_periods=window // 2).std()
    return (s - m) / sd.replace(0, np.nan)


def minmax_roll(s, window=ROLL_LONG):
    lo = s.rolling(window, min_periods=window // 2).min()
    hi = s.rolling(window, min_periods=window // 2).max()
    return (s - lo) / (hi - lo).replace(0, np.nan)


def winsorize_row(row, pct=WINSOR_PCT):
    clean = row.dropna()
    if clean.empty:
        return row
    upper = np.nanpercentile(clean, pct)
    return row.clip(upper=upper)


# ═════════════════════════════════════════════
# SECTION 3 — LIQUIDITY INDEX COMPONENTS
# ═════════════════════════════════════════════


def compute_amihud(close_w, volume_w):
    print("  Computing Amihud...")
    returns_w = close_w.pct_change(fill_method=None)
    rupee_vol = close_w * volume_w
    illiq = returns_w.abs() / rupee_vol.replace(0, np.nan)
    illiq_roll = illiq.rolling(ROLL_SHORT, min_periods=ROLL_SHORT // 2).mean()
    amihud_cs = illiq_roll.apply(winsorize_row, axis=1).mean(axis=1)
    amihud_cs.name = "amihud"
    print(f"    Shape: {amihud_cs.shape}  Nulls: {amihud_cs.isna().sum()}")
    return amihud_cs


def compute_cs_spread(high_w, low_w):
    print("  Computing Corwin-Schultz spread...")

    def _cs_per_stock(high, low):
        hl = np.log(high / low)
        beta = hl**2 + hl.shift(1) ** 2
        gamma = (
            np.log(
                pd.concat([high, high.shift(1)], axis=1).max(axis=1)
                / pd.concat([low, low.shift(1)], axis=1).min(axis=1)
            )
            ** 2
        )
        denom = 3 - 2 * (2**0.5)
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)
        spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
        return spread.clip(lower=0)

    cs_list = [_cs_per_stock(high_w[sym], low_w[sym]).rename(sym) for sym in high_w.columns]
    cs_w = pd.concat(cs_list, axis=1)

    trading_dates = pd.Series(range(len(cs_w.index)), index=cs_w.index)
    row_gaps = trading_dates.diff()
    bad_dates = row_gaps[row_gaps != 1].index
    cs_w.loc[bad_dates] = float("nan")

    cs_cs = cs_w.mean(axis=1)
    cs_cs.name = "cs_spread"
    print(f"    Shape: {cs_cs.shape}  Nulls: {cs_cs.isna().sum()}")
    return cs_cs


def compute_turnover(close_w, volume_w, shares):
    print("  Computing Turnover...")
    syms = [s for s in close_w.columns if s in shares.index]
    close_ts = close_w[syms]
    volume_ts = volume_w[syms]
    so = shares[syms]
    mktcap = close_ts.multiply(so, axis=1)
    turnover = (close_ts * volume_ts) / mktcap.replace(0, np.nan)
    turnover_roll = turnover.rolling(ROLL_SHORT, min_periods=ROLL_SHORT // 2).mean()
    turnover_cs = turnover_roll.mean(axis=1)
    turnover_cs.name = "turnover"
    print(f"    Shape: {turnover_cs.shape}  Nulls: {turnover_cs.isna().sum()}")
    return turnover_cs


def compute_li(amihud_cs, cs_cs, turnover_cs):
    print("  Building LI composite...")
    z_amihud = rolling_zscore(1 / amihud_cs.replace(0, np.nan))
    z_cs = rolling_zscore(-cs_cs)
    z_turnover = rolling_zscore(turnover_cs)
    li = pd.concat([z_amihud, z_cs, z_turnover], axis=1).mean(axis=1)
    li.name = "li"
    print(f"    Shape: {li.shape}  Nulls: {li.isna().sum()}")
    return li


# ═════════════════════════════════════════════
# SECTION 4 — INDEX DATA  (reads shared parquet, no yfinance)
# ═════════════════════════════════════════════


def fetch_index_ohlcv(ticker, start_date, end_date):
    """
    Read index OHLCV from the shared data/index_prices.parquet.
    Signature kept identical to the old yfinance version so no callers change.
    Returns DataFrame with lowercase columns, date index.
    """
    print(f"  Loading index from parquet: {ticker}...")

    prices = pd.read_parquet(INDEX_PARQUET)
    prices["date"] = pd.to_datetime(prices["date"])
    prices.columns = prices.columns.str.strip().str.lower()

    mask = (
        (prices["symbol"] == ticker)
        & (prices["date"] >= pd.Timestamp(start_date))
        & (prices["date"] <= pd.Timestamp(end_date))
    )
    df = prices[mask].copy()
    df = df.drop(columns=["symbol"]).set_index("date").sort_index()

    print(f"    Index shape: {df.shape}")
    return df


# ═════════════════════════════════════════════
# SECTION 5 — RISK INDEX COMPONENTS
# ═════════════════════════════════════════════


def compute_rv(idx_ret):
    print("  Computing RI-1 Realized Vol...")
    rv = np.sqrt(252 * (idx_ret**2).rolling(ROLL_SHORT, min_periods=ROLL_SHORT // 2).mean())
    rv.name = "rv"
    print(f"    Shape: {rv.shape}  Nulls: {rv.isna().sum()}")
    return rv


def compute_vov(rv):
    print("  Computing RI-2 VoV...")
    vov = rv.rolling(ROLL_SHORT, min_periods=ROLL_SHORT // 2).std()
    vov.name = "vov"
    print(f"    Shape: {vov.shape}  Nulls: {vov.isna().sum()}")
    return vov


def compute_dispersion(returns_w):
    print("  Computing RI-3 Dispersion...")
    dispersion = returns_w.std(axis=1)
    dispersion.name = "dispersion"
    print(f"    Shape: {dispersion.shape}  Nulls: {dispersion.isna().sum()}")
    return dispersion


def compute_avg_corr(returns_w, idx_ret):
    print("  Computing RI-4 Avg Corr (PCA proxy)...")
    idx_aligned = idx_ret.reindex(returns_w.index)
    corr_cols = [
        returns_w[sym].rolling(ROLL_SHORT, min_periods=ROLL_SHORT // 2).corr(idx_aligned).rename(sym)
        for sym in returns_w.columns
    ]
    avg_corr = pd.concat(corr_cols, axis=1).mean(axis=1)
    avg_corr.name = "avg_corr"
    print(f"    Shape: {avg_corr.shape}  Nulls: {avg_corr.isna().sum()}")
    return avg_corr


def compute_drawdown(idx_close):
    print("  Computing RI-5 Drawdown...")
    roll_max = idx_close.rolling(ROLL_LONG, min_periods=ROLL_LONG // 2).max()
    drawdown = (idx_close - roll_max) / roll_max.replace(0, np.nan)
    drawdown.name = "drawdown"
    print(f"    Shape: {drawdown.shape}  Nulls: {drawdown.isna().sum()}")
    return drawdown


def compute_skew(idx_ret):
    print("  Computing RI-6 Skewness...")
    skew = idx_ret.rolling(ROLL_SKEW, min_periods=ROLL_SKEW // 2).skew()
    skew.name = "skew"
    print(f"    Shape: {skew.shape}  Nulls: {skew.isna().sum()}")
    return skew


def compute_ri(rv, vov, dispersion, avg_corr, drawdown, skew, common_idx):
    print("  Building RI composite...")

    def align(s):
        return s.reindex(common_idx)

    z_rv = rolling_zscore(align(rv))
    z_vov = rolling_zscore(align(vov))
    z_disp = rolling_zscore(dispersion)
    z_corr = rolling_zscore(avg_corr)
    z_dd = rolling_zscore(-align(drawdown))
    z_skew = rolling_zscore(-align(skew))

    ri_df = pd.concat([z_rv, z_vov, z_disp, z_corr, z_dd, z_skew], axis=1)
    valid_counts = ri_df.notna().sum(axis=1)
    ri = ri_df.mean(axis=1)
    ri[valid_counts < 5] = float("nan")
    ri.name = "ri"
    print(f"    Shape: {ri.shape}  Nulls: {ri.isna().sum()}")
    return ri


# ═════════════════════════════════════════════
# SECTION 6 — STRESS SCORE
# ═════════════════════════════════════════════


def compute_stress(li, ri):
    print("  Building Stress Score...")
    li_norm = minmax_roll(li)
    ri_norm = minmax_roll(ri)
    stress = 0.5 * (1 - li_norm) + 0.5 * ri_norm
    stress.name = "stress_score"
    print(f"    Shape: {stress.shape}  Nulls: {stress.isna().sum()}")
    return stress


# ═════════════════════════════════════════════
# SECTION 7 — PER-UNIVERSE RUNNER
# ═════════════════════════════════════════════


def run_universe(univ_name, idx_ticker, csv_path, prices, shares, excluded):
    print(f"\n{'=' * 60}")
    print(f"Processing: {univ_name}")
    print(f"{'=' * 60}")

    members = load_universe_members(csv_path, excluded)
    wide = pivot_prices(prices, members)

    close_w = wide["close"]
    volume_w = wide["volume"]
    high_w = wide["high"]
    low_w = wide["low"]
    returns_w = wide["returns"]
    common_idx = returns_w.index

    start_date = prices["date"].min()
    end_date = prices["date"].max()

    # ── LI components ───────────────────────
    amihud_cs = compute_amihud(close_w, volume_w)
    cs_cs = compute_cs_spread(high_w, low_w)
    turnover_cs = compute_turnover(close_w, volume_w, shares)

    # ── Index data from shared parquet ───────
    idx_df = fetch_index_ohlcv(idx_ticker, start_date, end_date)
    idx_close = idx_df["close"]
    idx_ret = idx_close.pct_change()

    # ── RI components ────────────────────────
    rv = compute_rv(idx_ret)
    vov = compute_vov(rv)
    dispersion = compute_dispersion(returns_w)
    avg_corr = compute_avg_corr(returns_w, idx_ret)
    drawdown = compute_drawdown(idx_close)
    skew = compute_skew(idx_ret)
    compute_ri(rv, vov, dispersion, avg_corr, drawdown, skew, common_idx)

    # ── Assemble & save ──────────────────────
    def align(s):
        return s.reindex(common_idx)

    out = pd.DataFrame(
        {
            "amihud": amihud_cs,
            "cs_spread": cs_cs,
            "turnover": turnover_cs,
            "rv": align(rv),
            "vov": align(vov),
            "dispersion": dispersion,
            "avg_corr": avg_corr,
            "drawdown": align(drawdown),
            "skew": align(skew),
        },
        index=common_idx,
    )

    out.index.name = "date"
    out = out.dropna(how="all")

    out_path = f"{OUT_DIR}/liquidity_risk_{univ_name}.parquet"
    out.to_parquet(out_path)
    print(f"\n  Saved → {out_path}  shape={out.shape}")
    return out


# ═════════════════════════════════════════════
# SECTION 8 — MAIN
# ═════════════════════════════════════════════


def main():
    # Staleness check
    import os
    from pathlib import Path

    pq = Path(INDEX_PARQUET)
    if not pq.exists():
        msg = f"ERROR: {INDEX_PARQUET} not found.\nRun data/fetch_index_data.py first."
        raise FileNotFoundError(msg)
    index_mtime = date.fromtimestamp(pq.stat().st_mtime)
    if index_mtime < date.today():
        msg = f"ERROR: {INDEX_PARQUET} is stale (last modified {index_mtime}).\nRun data/fetch_index_data.py first."
        raise RuntimeError(msg)

    prices, shares, excluded = load_data()
    for univ_name, (idx_ticker, csv_path) in UNIVERSES.items():
        run_universe(univ_name, idx_ticker, csv_path, prices, shares, excluded)
    print("\nAll universes complete.")


if __name__ == "__main__":
    main()

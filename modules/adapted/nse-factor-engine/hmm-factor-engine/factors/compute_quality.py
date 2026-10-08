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
compute_quality.py
==================
Quality Factor Construction (vectorized, fast)

Non-financials: Quality = 0.33*Z(ROCE) - 0.33*Z(D/E) - 0.33*Z(EPS_growth_std)
Financials:     Quality = 0.5*Z(ROE)   - 0.5*Z(EPS_growth_std)
Date fix: return recorded at t1_end (month return is earned)
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
FUND_FILE = DATA_DIR / "fundamentals_annual.parquet"
SECTOR_FILE = DATA_DIR / "ticker_to_sector.csv"
SYMBOL_MAP_FILE = DATA_DIR / "symbol_map.csv"
CONSTITUENT_CSV = Path(
    "/home/ec2-user/nse-factor-engine/nifty_constituent_history/"
    "nifty500_2005-01-01_to_2026-06-30.csv"
)
OUTPUT_FILE = FACTORS_DIR / "factor_quality.parquet"
OUTPUT_RET = FACTORS_DIR / "quality_returns.parquet"

LONG_PCTILE = 0.90
SHORT_PCTILE = 0.10
MIN_STOCKS = 20

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKTEST_START = "2020-07"
BACKTEST_END = "2026-06"
WINSOR_LOW = 0.01
WINSOR_HIGH = 0.99
MIN_EPS_YEARS = 3
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
def parse_fiscal_year_end(fy_str: str) -> pd.Timestamp:
    month_map = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    try:
        mon_str, yr_str = fy_str[:3], fy_str[4:]
        month = month_map[mon_str]
        year = 2000 + int(yr_str)
        ts = pd.Timestamp(year=year, month=month, day=1)
        return ts + pd.offsets.MonthEnd(0)
    except Exception:
        return pd.NaT


def load_symbol_map() -> dict:
    sym_map = {}
    with open(SYMBOL_MAP_FILE) as f:
        for row in csv.DictReader(f):
            sym_map[row["csv_symbol"]] = row["parquet_col"]
    return sym_map


def load_sector_map() -> pd.DataFrame:
    df = pd.read_csv(SECTOR_FILE)
    df["is_financial"] = df["is_financial"].astype(str).str.strip().str.lower()
    df["is_financial"] = df["is_financial"].isin(["true", "1", "yes"])
    return df.set_index("nse_ticker")


def winsorise(s: pd.Series) -> pd.Series:
    lo = s.quantile(WINSOR_LOW)
    hi = s.quantile(WINSOR_HIGH)
    return s.clip(lo, hi)


def zscore(s: pd.Series) -> pd.Series:
    mu, sigma = s.mean(), s.std()
    if sigma == 0 or pd.isna(sigma):
        return pd.Series(np.nan, index=s.index)
    return (s - mu) / sigma


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
# Fundamentals
# ---------------------------------------------------------------------------
def annualise_current_year(ticker_df: pd.DataFrame) -> pd.DataFrame:
    df = ticker_df.copy().sort_values("fy_end").reset_index(drop=True)
    latest = df.iloc[-1]

    if latest["fy_month"] == 3:
        return df

    latest_year = latest["fy_end"].year
    latest_month = latest["fy_month"]
    current_yr_rows = df[df["fy_end"].dt.year == latest_year].copy()

    def get_q(month):
        row = current_yr_rows[current_yr_rows["fy_month"] == month]
        return row.iloc[0]["net_profit"] if len(row) > 0 else np.nan

    q1, q2, q3 = get_q(6), get_q(9), get_q(12)
    ann_np = np.nan

    if latest_month == 6:
        if pd.notna(q1):
            ann_np = q1 * 4
    elif latest_month == 9:
        if pd.notna(q2) and pd.notna(q1):
            ann_np = (q2 + q1) * 2
        elif pd.notna(q2):
            ann_np = q2 * 2
    elif latest_month == 12:
        if pd.notna(q3) and pd.notna(q2) and pd.notna(q1):
            ann_np = (q3 + q2 + q1) * (4 / 3)
        elif pd.notna(q3) and pd.notna(q1):
            ann_np = (q3 + q1) * (4 / 3)
        elif pd.notna(q3):
            ann_np = q3 * (4 / 3)

    df.loc[df.index[-1], "net_profit_ann"] = ann_np
    return df


def load_fundamentals() -> pd.DataFrame:
    df = pd.read_parquet(FUND_FILE)
    df["fy_end"] = df["fiscal_year"].apply(parse_fiscal_year_end)
    df = df[df["fy_end"].notna()].copy()
    df["fy_month"] = df["fy_end"].dt.month
    df = df.sort_values(["nse_ticker", "fy_end"]).reset_index(drop=True)

    for col in ["book_equity", "shares_cr", "total_debt"]:
        df[col] = df.groupby("nse_ticker")[col].ffill()

    df["total_debt"] = df["total_debt"].fillna(0)
    df["net_profit_ann"] = df["net_profit"]

    results = []
    for _ticker, grp in df.groupby("nse_ticker"):
        if grp.iloc[-1]["fy_month"] != 3:
            grp = annualise_current_year(grp)
        results.append(grp)

    df = pd.concat(results, ignore_index=True)
    df["available_from"] = df["fy_end"] + pd.Timedelta(days=90)
    return df


def build_eps_history(fund_df: pd.DataFrame) -> dict:
    eps_history = {}
    for ticker, grp in fund_df.groupby("nse_ticker"):
        grp = grp.sort_values("fy_end").copy()
        march_rows = grp[grp["fy_month"] == 3].copy()
        latest_row = grp.iloc[[-1]]

        if latest_row.iloc[0]["fy_month"] != 3:
            annual_rows = pd.concat([march_rows, latest_row], ignore_index=True)
        else:
            annual_rows = march_rows.copy()

        annual_rows = annual_rows[
            annual_rows["net_profit_ann"].notna()
            & annual_rows["shares_cr"].notna()
            & (annual_rows["shares_cr"] > 0)
        ].copy()

        if len(annual_rows) < MIN_EPS_YEARS:
            continue

        annual_rows["eps"] = annual_rows["net_profit_ann"] / annual_rows["shares_cr"]
        eps_history[ticker] = annual_rows.set_index("fy_end")["eps"]

    return eps_history


def get_eps_growth_std(ticker, date, eps_history, available_from_map) -> float:
    if ticker not in eps_history:
        return np.nan

    eps = eps_history[ticker]
    avail_dates = available_from_map.get(ticker, {})
    valid_eps = eps[eps.index.map(lambda d: avail_dates.get(d, pd.NaT)) <= date]

    if len(valid_eps) < MIN_EPS_YEARS:
        return np.nan

    eps_growth = valid_eps.iloc[-5:].pct_change().dropna()
    if len(eps_growth) < 2:
        return np.nan

    return eps_growth.std()


# ---------------------------------------------------------------------------
# Signal at date T
# ---------------------------------------------------------------------------
def get_signals_at_date(
    date: pd.Timestamp,
    universe: list,
    fund_df: pd.DataFrame,
    sector_map: pd.DataFrame,
    eps_history: dict,
    available_from_map: dict,
) -> pd.DataFrame:
    avail = fund_df[(fund_df["available_from"] <= date) & (fund_df["book_equity"].notna())]
    latest = (
        avail[avail["nse_ticker"].isin(universe)]
        .sort_values("fy_end")
        .groupby("nse_ticker", as_index=False)
        .nth(-1)
    )

    if latest.empty:
        return pd.DataFrame()

    latest = latest.join(sector_map[["is_financial"]], on="nse_ticker", how="left")
    latest["is_financial"] = latest["is_financial"].fillna(False)

    rows = []
    for _, row in latest.iterrows():
        ticker = row["nse_ticker"]
        is_fin = row["is_financial"]
        be = row["book_equity"]

        if pd.isna(be) or be == 0:
            continue

        np_ann = row["net_profit_ann"]
        raw_roe = (np_ann / be) if pd.notna(np_ann) else np.nan

        if is_fin:
            raw_roce = np.nan
        else:
            op = row.get("operating_profit", np.nan)
            td = row.get("total_debt", np.nan)
            td = 0.0 if pd.isna(td) else td
            ce = be + td
            raw_roce = (op / ce) if (pd.notna(op) and ce != 0) else np.nan

        raw_de = (
            (row["total_debt"] / be) if (not is_fin and pd.notna(row["total_debt"])) else np.nan
        )
        raw_eps_std = get_eps_growth_std(ticker, date, eps_history, available_from_map)

        profitability = raw_roce if not is_fin else raw_roe
        if pd.isna(profitability) and pd.isna(raw_eps_std):
            continue

        rows.append(
            {
                "nse_ticker": ticker,
                "is_financial": is_fin,
                "raw_roe": raw_roe,
                "raw_roce": raw_roce,
                "raw_de": raw_de,
                "raw_eps_std": raw_eps_std,
            }
        )

    return pd.DataFrame(rows)


def compute_scores(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return signals

    result = signals.copy().reset_index(drop=True)
    result["score_within"] = np.nan
    result["score_combined"] = np.nan

    for is_fin in [False, True]:
        mask = result["is_financial"] == is_fin
        grp = result[mask].copy()
        if len(grp) < 5:
            continue

        prof_col = "raw_roce" if not is_fin else "raw_roe"

        z_prof = pd.Series(np.nan, index=grp.index)
        if grp[prof_col].notna().sum() >= 5:
            valid = grp[prof_col].dropna()
            z_prof[valid.index] = zscore(winsorise(valid)).values

        z_eps = pd.Series(np.nan, index=grp.index)
        if grp["raw_eps_std"].notna().sum() >= 5:
            valid = grp["raw_eps_std"].dropna()
            z_eps[valid.index] = zscore(winsorise(valid)).values

        z_de = pd.Series(np.nan, index=grp.index)
        if not is_fin and grp["raw_de"].notna().sum() >= 5:
            valid = grp["raw_de"].dropna()
            z_de[valid.index] = zscore(winsorise(valid)).values

        for idx in grp.index:
            zp = z_prof[idx]
            ze = z_eps[idx]
            zd = z_de[idx]
            hp = pd.notna(zp)
            he = pd.notna(ze)
            hd = pd.notna(zd)

            if not is_fin:
                if hp and hd and he:
                    s = 0.33 * zp - 0.33 * zd - 0.33 * ze
                elif hp and hd:
                    s = 0.50 * zp - 0.50 * zd
                elif hp and he:
                    s = 0.50 * zp - 0.50 * ze
                elif hp:
                    s = zp
                else:
                    s = np.nan
            else:
                if hp and he:
                    s = 0.50 * zp - 0.50 * ze
                elif hp:
                    s = zp
                else:
                    s = np.nan

            result.loc[idx, "score_within"] = s

    valid = result["score_within"].dropna()
    if len(valid) >= 5:
        result["score_combined"] = zscore(result["score_within"])

    return result


# ---------------------------------------------------------------------------
# Backtest loop
# ---------------------------------------------------------------------------
def run_backtest(
    monthly_px: pd.DataFrame,
    return_matrix: pd.DataFrame,
    adtv_matrix: pd.DataFrame,
    universe_df: pd.DataFrame,
    fund_df: pd.DataFrame,
    sector_map: pd.DataFrame,
    eps_history: dict,
    available_from_map: dict,
    sym_map: dict,
) -> pd.DataFrame:

    rev_map = {v: k for k, v in sym_map.items()}
    periods = pd.period_range(start=BACKTEST_START, end=BACKTEST_END, freq="M")
    dates = [p.to_timestamp(how="end").normalize() for p in periods]
    valid_dates = [d for d in dates if d in monthly_px.index]
    all_records = []

    for date in valid_dates:
        pit = get_pit_universe(date, universe_df)
        if not pit:
            continue

        threshold = get_adtv_threshold(date)
        if date not in adtv_matrix.index:
            continue
        adtv_row = adtv_matrix.loc[date]
        pit_cols = [sym_map.get(s, s) for s in pit]
        pit_cols = [c for c in pit_cols if c in adtv_row.index]
        adtv_pass = adtv_row[pit_cols].dropna()
        adtv_pass = adtv_pass[adtv_pass >= threshold].index.tolist()
        universe = [rev_map.get(c, c) for c in adtv_pass]

        if len(universe) < MIN_STOCKS:
            continue

        signals = get_signals_at_date(
            date, universe, fund_df, sector_map, eps_history, available_from_map
        )
        if signals.empty or len(signals) < 10:
            print(f"  SKIP {date.strftime('%Y-%m')}: only {len(signals)} stocks with signal")
            continue

        scored = compute_scores(signals)
        scored["date"] = date
        all_records.append(
            scored[
                [
                    "nse_ticker",
                    "date",
                    "is_financial",
                    "raw_roe",
                    "raw_roce",
                    "raw_de",
                    "raw_eps_std",
                    "score_within",
                    "score_combined",
                ]
            ]
        )

    if not all_records:
        return pd.DataFrame()

    return pd.concat(all_records, ignore_index=True)


# ---------------------------------------------------------------------------
# Vectorized return computation
# ---------------------------------------------------------------------------
def compute_long_short_returns(
    scores_df: pd.DataFrame,
    score_col: str,
    monthly_px: pd.DataFrame,
    return_matrix: pd.DataFrame,
    sym_map: dict,
) -> pd.DataFrame:
    records = []
    idx = monthly_px.index

    for date in sorted(scores_df["date"].unique()):
        month_df = scores_df[scores_df["date"] == date][["nse_ticker", score_col]].dropna(
            subset=[score_col]
        )

        if len(month_df) < MIN_STOCKS:
            continue

        if date not in idx:
            continue
        pos = idx.get_loc(date)
        if pos >= len(idx) - 1:
            continue
        t1_end = idx[pos + 1]

        long_thresh = month_df[score_col].quantile(LONG_PCTILE)
        short_thresh = month_df[score_col].quantile(SHORT_PCTILE)
        long_tickers = month_df[month_df[score_col] >= long_thresh]["nse_ticker"].tolist()
        short_tickers = month_df[month_df[score_col] <= short_thresh]["nse_ticker"].tolist()

        long_cols = [sym_map.get(t, t) for t in long_tickers]
        short_cols = [sym_map.get(t, t) for t in short_tickers]
        long_cols = [c for c in long_cols if c in return_matrix.columns]
        short_cols = [c for c in short_cols if c in return_matrix.columns]

        if t1_end not in return_matrix.index:
            continue

        long_rets = return_matrix.loc[t1_end, long_cols].dropna()
        short_rets = return_matrix.loc[t1_end, short_cols].dropna()

        if long_rets.empty or short_rets.empty:
            continue

        records.append(
            {
                "date": t1_end,
                "quality_return": long_rets.mean() - short_rets.mean(),
                "long_return": long_rets.mean(),
                "short_return": short_rets.mean(),
                "long_count": len(long_rets),
                "short_count": len(short_rets),
                "universe_size": len(month_df),
            }
        )

    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df


def print_return_stats(df: pd.DataFrame, name: str):
    if df.empty:
        print(f"  {name}: NO RESULTS")
        return
    ret_col = [
        c for c in df.columns if c.endswith("_return") and "long" not in c and "short" not in c
    ][0]
    r = df[ret_col]
    ann_ret = r.mean() * 12
    ann_vol = r.std() * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    drawdown = (cum / cum.cummax() - 1).min()
    hit_rate = (r > 0).mean()
    print(
        f"  {name}: months={len(df)}  ann_ret={ann_ret * 100:.2f}%  "
        f"vol={ann_vol * 100:.2f}%  sharpe={sharpe:.3f}  "
        f"maxDD={drawdown * 100:.2f}%  hit={hit_rate * 100:.1f}%"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    FACTORS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading symbol map ...")
    sym_map = load_symbol_map()
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

    print("Loading fundamentals ...")
    fund_df = load_fundamentals()
    print(f"  {len(fund_df)} rows, {fund_df['nse_ticker'].nunique()} tickers")

    print("Loading sector map ...")
    sector_map = load_sector_map()

    print("Building EPS history ...")
    eps_history = build_eps_history(fund_df)
    print(f"  {len(eps_history)} tickers with valid EPS history")

    print("Building available_from lookup ...")
    available_from_map = {
        ticker: dict(zip(grp["fy_end"], grp["available_from"], strict=False))
        for ticker, grp in fund_df.groupby("nse_ticker")
    }

    adtv_matrix = build_adtv_matrix(prices_long, monthly_px.index)

    print(f"\nRunning backtest: {BACKTEST_START} to {BACKTEST_END} ...")
    results = run_backtest(
        monthly_px,
        return_matrix,
        adtv_matrix,
        universe_df,
        fund_df,
        sector_map,
        eps_history,
        available_from_map,
        sym_map,
    )

    if results.empty:
        print("ERROR: no results produced")
        return

    results.to_parquet(OUTPUT_FILE)
    print(f"Saved -> {OUTPUT_FILE}")

    print("\nComputing long-short return series ...")
    quality_returns = compute_long_short_returns(
        results, "score_combined", monthly_px, return_matrix, sym_map
    )
    print_return_stats(quality_returns, "QUALITY")
    quality_returns.to_parquet(OUTPUT_RET)

    print("\nAround COVID (date = month return was earned):")
    covid = quality_returns.loc[quality_returns.index >= pd.Timestamp("2020-01-01")].head(7)[
        ["quality_return", "long_return", "short_return"]
    ]
    print(covid.to_string())

    print("Done.")


if __name__ == "__main__":
    main()

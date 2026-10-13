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
compute_value.py
================
Value Factor Construction (vectorized, fast)

Non-financials: Value = Z(E/P)/3 + Z(B/P)/3 + Z(S/P)/3
Financials:     Value = Z(E/P)/2 + Z(B/P)/2
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
OUTPUT_FILE = FACTORS_DIR / "factor_value.parquet"
OUTPUT_RET = FACTORS_DIR / "value_returns.parquet"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BACKTEST_START = "2018-07"
BACKTEST_END = "2026-06"
WINSOR_LOW = 0.01
WINSOR_HIGH = 0.99
EXCLUDE_TICKERS = {"ABBOTINDIA", "PFIZER"}
MIN_STOCKS = 20
LONG_PCTILE = 0.90
SHORT_PCTILE = 0.10
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
# Annualise P&L for incomplete fiscal year
# ---------------------------------------------------------------------------
def annualise_current_year(grp: pd.DataFrame) -> pd.DataFrame:
    grp = grp.copy().sort_values("fy_end").reset_index(drop=True)
    latest = grp.iloc[-1]

    if latest["fy_month"] == 3:
        return grp

    latest_year = latest["fy_end"].year
    current_yr_rows = grp[grp["fy_end"].dt.year == latest_year]

    def get_q(month, field):
        row = current_yr_rows[current_yr_rows["fy_month"] == month]
        if len(row) == 0:
            return np.nan
        return row.iloc[0][field]

    for field in ["net_profit_ann", "sales_ann"]:
        src = "net_profit" if field == "net_profit_ann" else "sales"
        q1 = get_q(6, src)
        q2 = get_q(9, src)
        q3 = get_q(12, src)
        lm = latest["fy_month"]

        ann = np.nan
        if lm == 6:
            if pd.notna(q1):
                ann = q1 * 4
        elif lm == 9:
            if pd.notna(q2) and pd.notna(q1):
                ann = (q2 + q1) * 2
            elif pd.notna(q2):
                ann = q2 * 2
        elif lm == 12:
            if pd.notna(q3) and pd.notna(q2) and pd.notna(q1):
                ann = (q3 + q2 + q1) * (4 / 3)
            elif pd.notna(q3) and pd.notna(q1):
                ann = (q3 + q1) * (4 / 3)
            elif pd.notna(q3):
                ann = q3 * (4 / 3)

        grp.loc[grp.index[-1], field] = ann

    return grp


def load_fundamentals() -> pd.DataFrame:
    df = pd.read_parquet(FUND_FILE)
    df["fy_end"] = df["fiscal_year"].apply(parse_fiscal_year_end)
    df = df[df["fy_end"].notna()].copy()
    df["fy_month"] = df["fy_end"].dt.month
    df = df.sort_values(["nse_ticker", "fy_end"]).reset_index(drop=True)

    for col in ["book_equity", "shares_cr", "total_debt"]:
        df[col] = df.groupby("nse_ticker")[col].ffill()

    df["net_profit_ann"] = df["net_profit"]
    df["sales_ann"] = df["sales"]

    results = []
    for _ticker, grp in df.groupby("nse_ticker"):
        if grp.iloc[-1]["fy_month"] != 3:
            grp = annualise_current_year(grp)
        results.append(grp)

    df = pd.concat(results, ignore_index=True)
    df["available_from"] = df["fy_end"] + pd.Timedelta(days=90)
    return df


# ---------------------------------------------------------------------------
# Signal at date T
# ---------------------------------------------------------------------------
def get_signals_at_date(
    date: pd.Timestamp,
    universe: list,
    fund_df: pd.DataFrame,
    sector_map: pd.DataFrame,
    monthly_px: pd.DataFrame,
    sym_map: dict,
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
        sc = row["shares_cr"]

        if pd.isna(be) or pd.isna(sc) or sc <= 0:
            continue

        col = sym_map.get(ticker, ticker)
        if col not in monthly_px.columns or date not in monthly_px.index:
            continue
        price = monthly_px.loc[date, col]
        if pd.isna(price) or price <= 0:
            continue

        market_cap_cr = price * sc
        if market_cap_cr <= 0:
            continue

        np_ann = row["net_profit_ann"]
        raw_ep = (np_ann / market_cap_cr) if pd.notna(np_ann) else np.nan
        raw_bp = be / market_cap_cr
        raw_sp = np.nan
        if not is_fin:
            s_ann = row["sales_ann"]
            raw_sp = (s_ann / market_cap_cr) if pd.notna(s_ann) else np.nan

        if pd.isna(raw_ep) and pd.isna(raw_bp):
            continue

        rows.append(
            {
                "nse_ticker": ticker,
                "is_financial": is_fin,
                "raw_ep": raw_ep,
                "raw_bp": raw_bp,
                "raw_sp": raw_sp,
            }
        )

    return pd.DataFrame(rows)


def compute_scores(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return signals

    result = signals.copy().reset_index(drop=True)

    for col, z_col in [("raw_ep", "z_ep"), ("raw_bp", "z_bp"), ("raw_sp", "z_sp")]:
        valid = result[col].dropna()
        if len(valid) >= 5:
            result.loc[valid.index, z_col] = zscore(winsorise(valid)).values
        else:
            result[z_col] = np.nan

    result["score_within"] = np.nan
    for idx, row in result.iterrows():
        is_fin = row["is_financial"]
        z_ep = row.get("z_ep", np.nan)
        z_bp = row.get("z_bp", np.nan)
        z_sp = row.get("z_sp", np.nan)
        have_ep = pd.notna(z_ep)
        have_bp = pd.notna(z_bp)
        have_sp = pd.notna(z_sp)

        if is_fin:
            if have_ep and have_bp:
                s = 0.5 * z_ep + 0.5 * z_bp
            elif have_ep:
                s = z_ep
            elif have_bp:
                s = z_bp
            else:
                s = np.nan
        else:
            if have_ep and have_bp and have_sp:
                s = z_ep / 3 + z_bp / 3 + z_sp / 3
            elif have_ep and have_bp:
                s = 0.5 * z_ep + 0.5 * z_bp
            elif have_ep and have_sp:
                s = 0.5 * z_ep + 0.5 * z_sp
            elif have_bp and have_sp:
                s = 0.5 * z_bp + 0.5 * z_sp
            elif have_ep:
                s = z_ep
            elif have_bp:
                s = z_bp
            else:
                s = np.nan

        result.loc[idx, "score_within"] = s

    valid = result["score_within"].dropna()
    if len(valid) >= 5:
        result["score_combined"] = zscore(result["score_within"])
    else:
        result["score_combined"] = np.nan

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
        universe = [
            rev_map.get(c, c) for c in adtv_pass if rev_map.get(c, c) not in EXCLUDE_TICKERS
        ]

        if len(universe) < MIN_STOCKS:
            continue

        signals = get_signals_at_date(date, universe, fund_df, sector_map, monthly_px, sym_map)
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
                    "raw_ep",
                    "raw_bp",
                    "raw_sp",
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
                "value_return": long_rets.mean() - short_rets.mean(),
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

    print("Loading and preparing fundamentals ...")
    fund_df = load_fundamentals()
    print(f"  {len(fund_df)} rows after preparation")

    print("Loading sector map ...")
    sector_map = load_sector_map()

    adtv_matrix = build_adtv_matrix(prices_long, monthly_px.index)

    print(f"\nRunning backtest: {BACKTEST_START} to {BACKTEST_END} ...")
    results = run_backtest(
        monthly_px, return_matrix, adtv_matrix, universe_df, fund_df, sector_map, sym_map
    )

    if results.empty:
        print("ERROR: no results produced")
        return

    results.to_parquet(OUTPUT_FILE)
    print(f"Saved -> {OUTPUT_FILE}")

    print("\nComputing long-short return series ...")
    value_returns = compute_long_short_returns(
        results, "score_combined", monthly_px, return_matrix, sym_map
    )
    print_return_stats(value_returns, "VALUE")
    value_returns.to_parquet(OUTPUT_RET)

    print("\nAround COVID (date = month return was earned):")
    covid = value_returns.loc[value_returns.index >= pd.Timestamp("2020-01-01")].head(7)[
        ["value_return", "long_return", "short_return"]
    ]
    print(covid.to_string())

    print("Done.")


if __name__ == "__main__":
    main()

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


import numpy as np
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"
RF = 0.07  # Indian 10Y G-Sec constant — placeholder until Stage 6 G-Sec time series
T_SKIP = 21  # skip-month offset (trading days)

# KI-001: VEDL split adjustment missing in yfinance source data.
# Vol metrics artificially inflated. Flagged in data_quality_flag column.
DATA_QUALITY_FLAGS = {"VEDL": "KI-001: missing split adjustment 2026-04-30"}

px = pd.read_parquet(f"{BASE}/data/prices.parquet")
px["date"] = pd.to_datetime(px["date"])
px = px.sort_values(["symbol", "date"]).reset_index(drop=True)
px["close"] = px.groupby("symbol")["close"].ffill()

date_counts = px.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()


def realised_vol(lr, ddof=1):
    if len(lr) < ddof + 1:
        return np.nan
    return np.std(lr, ddof=ddof) * np.sqrt(252)


def downside_vol(lr, ddof=1):
    neg = lr[lr < 0]
    if len(neg) < ddof + 1:
        return np.nan
    return np.std(neg, ddof=ddof) * np.sqrt(252)


def safe_div(num, den):
    if pd.isna(num) or pd.isna(den) or den == 0:
        return np.nan
    return num / den


records = []
for sym, grp in px.groupby("symbol"):
    dates = grp["date"].sort_values().reset_index(drop=True)
    closes = grp.sort_values("date")["close"].reset_index(drop=True)
    n = len(dates)

    T_pos = dates[dates == T].index
    T_pos_i = T_pos[0] if len(T_pos) > 0 else n - 1

    def get_close(offset):
        idx = T_pos_i - offset
        return closes.iloc[idx] if idx >= 0 else np.nan

    def pct_ret(end, start):
        if pd.isna(end) or pd.isna(start) or start == 0:
            return np.nan
        return (end - start) / start

    # --- returns ---
    ret_12m1m = pct_ret(get_close(21), get_close(252))
    ret_6m1m = pct_ret(get_close(21), get_close(126))
    ret_3m1m = pct_ret(get_close(21), get_close(63))

    # --- vol_252: T-252 → T (253 closes → 252 log rets) ---
    s252 = T_pos_i - 252
    if s252 >= 0:
        sl = closes.iloc[s252 : T_pos_i + 1]
        lr = np.log(sl.values[1:] / sl.values[:-1])
        v_252 = realised_vol(lr)
        dv_252 = downside_vol(lr)
    else:
        v_252 = dv_252 = np.nan

    # --- vol_231: T-252 → T-21 (232 closes → 231 log rets) ---
    s231 = T_pos_i - 252
    e231 = T_pos_i - 21
    if s231 >= 0 and e231 > s231:
        sl = closes.iloc[s231 : e231 + 1]
        lr = np.log(sl.values[1:] / sl.values[:-1])
        v_231 = realised_vol(lr)
        dv_231 = downside_vol(lr)
    else:
        v_231 = dv_231 = np.nan

    # --- composites (all use vol_231 as denominator — matched window) ---
    vol_adj_ret = safe_div(ret_12m1m, v_231)
    sharpe_style = safe_div(ret_12m1m - RF, v_231)
    # EXTENSION beyond PDF Stage 2 spec: per-stock Sortino using downside vol
    sortino_style = safe_div(ret_12m1m - RF, dv_231)

    records.append(
        {
            "symbol": sym,
            "as_of_date": T.date(),
            # returns
            "ret_12m1m": ret_12m1m,
            "ret_6m1m": ret_6m1m,
            "ret_3m1m": ret_3m1m,
            # vol
            "vol_252": v_252,
            "vol_231": v_231,
            "downside_vol_252": dv_252,
            "downside_vol_231": dv_231,
            # composites
            "vol_adj_ret": vol_adj_ret,
            "sharpe_style": sharpe_style,
            "sortino_style": sortino_style,
            # data quality
            "data_quality_flag": DATA_QUALITY_FLAGS.get(sym, ""),
        }
    )

df = pd.DataFrame(records)

# --- sanity checks ---
print(f"Rows: {len(df)}  |  Columns: {list(df.columns)}")

print("\nNaN counts — all signal columns:")
sig_cols = [
    "ret_12m1m",
    "ret_6m1m",
    "ret_3m1m",
    "vol_252",
    "vol_231",
    "downside_vol_252",
    "downside_vol_231",
    "vol_adj_ret",
    "sharpe_style",
    "sortino_style",
]
print(df[sig_cols].isna().sum().to_string())

print("\nDescriptive stats — composites:")
print(df[["vol_adj_ret", "sharpe_style", "sortino_style"]].describe().round(4).to_string())

# arithmetic self-check: sharpe_style = vol_adj_ret - RF/vol_231
valid = df.dropna(subset=["vol_adj_ret", "sharpe_style", "vol_231"])
residual = (valid["sharpe_style"] - valid["vol_adj_ret"] + RF / valid["vol_231"]).abs().max()
print(f"\nArithmetic self-check sharpe vs vol_adj (max residual, expect ~0): {residual:.2e}")

# sortino magnitude >= sharpe magnitude (downside_vol <= total_vol for most)
valid2 = df.dropna(subset=["sharpe_style", "sortino_style"])
viol = (valid2["sortino_style"].abs() < valid2["sharpe_style"].abs()).sum()
print(f"Sortino |score| < Sharpe |score| count (expect low): {viol}")

# data quality flag check
flagged = df[df["data_quality_flag"] != ""]
print(f"\nData quality flagged symbols: {len(flagged)}")
print(
    flagged[["symbol", "data_quality_flag", "vol_252", "vol_adj_ret", "sharpe_style", "sortino_style"]].to_string(
        index=False
    )
)

print("\nSample — 5 clean symbols, all signals valid:")
clean = df[(df["data_quality_flag"] == "") & df["sortino_style"].notna()]
print(
    clean.head(5)[
        ["symbol", "ret_12m1m", "vol_231", "downside_vol_231", "vol_adj_ret", "sharpe_style", "sortino_style"]
    ].to_string(index=False)
)

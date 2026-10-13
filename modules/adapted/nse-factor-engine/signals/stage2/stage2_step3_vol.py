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
px = pd.read_parquet(f"{BASE}/data/prices.parquet")
px["date"] = pd.to_datetime(px["date"])
px = px.sort_values(["symbol", "date"]).reset_index(drop=True)
px["close"] = px.groupby("symbol")["close"].ffill()

date_counts = px.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()


def realised_vol(log_rets, ddof=1):
    """Annualised vol from an array of daily log returns."""
    if len(log_rets) < ddof + 1:
        return np.nan
    return np.std(log_rets, ddof=ddof) * np.sqrt(252)


def downside_vol(log_rets, ddof=1):
    """Annualised downside vol — negative log returns only. NaN if <2 negative days."""
    neg = log_rets[log_rets < 0]
    if len(neg) < ddof + 1:
        return np.nan
    return np.std(neg, ddof=ddof) * np.sqrt(252)


records = []
for sym, grp in px.groupby("symbol"):
    dates = grp["date"].sort_values().reset_index(drop=True)
    closes = grp.sort_values("date")["close"].reset_index(drop=True)
    n = len(dates)

    T_pos = dates[dates == T].index
    T_pos_i = T_pos[0] if len(T_pos) > 0 else n - 1

    # --- vol_252 & downside_vol_252: T-252 → T (full window) ---
    start_252 = T_pos_i - 252
    if start_252 >= 0:
        sl_252 = closes.iloc[start_252 : T_pos_i + 1]  # 253 closes → 252 log rets
        lr_252 = np.log(sl_252.values[1:] / sl_252.values[:-1])
        v_252 = realised_vol(lr_252)
        dv_252 = downside_vol(lr_252)
    else:
        v_252 = dv_252 = np.nan

    # --- vol_231 & downside_vol_231: T-252 → T-21 (skip-month window) ---
    start_231 = T_pos_i - 252
    end_231 = T_pos_i - 21
    if start_231 >= 0 and end_231 > start_231:
        sl_231 = closes.iloc[start_231 : end_231 + 1]  # 232 closes → 231 log rets
        lr_231 = np.log(sl_231.values[1:] / sl_231.values[:-1])
        v_231 = realised_vol(lr_231)
        dv_231 = downside_vol(lr_231)
    else:
        v_231 = dv_231 = np.nan

    records.append(
        {
            "symbol": sym,
            "vol_252": v_252,
            "vol_231": v_231,
            "downside_vol_252": dv_252,
            "downside_vol_231": dv_231,
        }
    )

df = pd.DataFrame(records)

# --- sanity checks ---
print(f"Rows: {len(df)}  |  Columns: {list(df.columns)}")

print("\nNaN counts:")
print(df[["vol_252", "vol_231", "downside_vol_252", "downside_vol_231"]].isna().sum().to_string())

print("\nDescriptive stats:")
print(
    df[["vol_252", "vol_231", "downside_vol_252", "downside_vol_231"]]
    .describe()
    .round(4)
    .to_string()
)

print("\nSample — 5 symbols with all vol cols valid:")
print(df.dropna().head(5).to_string(index=False))

# downside vol should always be ≤ total vol (if computed from same window)
valid = df.dropna()
viol_252 = (valid["downside_vol_252"] > valid["vol_252"]).sum()
viol_231 = (valid["downside_vol_231"] > valid["vol_231"]).sum()
print(f"\ndownside_vol_252 > vol_252 (expect 0): {viol_252}")
print(f"downside_vol_231 > vol_231 (expect 0): {viol_231}")

# correlation matrix across all four vol cols
print("\nCorrelation matrix:")
print(
    df[["vol_252", "vol_231", "downside_vol_252", "downside_vol_231"]].corr().round(4).to_string()
)

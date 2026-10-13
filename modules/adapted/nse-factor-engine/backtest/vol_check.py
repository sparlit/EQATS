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

ACTIVITY = (
    "/home/ec2-user/nse-factor-engine/backtest/results/backtest_portfolio_activity_09072026.parquet"
)
PRICES = "/home/ec2-user/nse-factor-engine/backtest/data/prices_backtest.parquet"

# Load
act = pd.read_parquet(ACTIVITY)
act = act[(act["cell_id"] == "G6_C6") & (act["action"].isin(["BUY", "HOLD"]))].copy()
act["friday_date"] = pd.to_datetime(act["friday_date"])

prices = pd.read_parquet(PRICES)
prices["date"] = pd.to_datetime(prices["date"])

# Weekly close: last trading day per symbol per week
prices["week"] = prices["date"].dt.to_period("W").apply(lambda r: r.end_time.date())
weekly_close = prices.sort_values("date").groupby(["symbol", "week"])["close"].last().reset_index()
weekly_close["week"] = pd.to_datetime(weekly_close["week"])

# Weekly return per symbol
weekly_close = weekly_close.sort_values(["symbol", "week"])
weekly_close["ret"] = weekly_close.groupby("symbol")["close"].pct_change()

# Pivot: rows=week, cols=symbol
ret_pivot = weekly_close.pivot(index="week", columns="symbol", values="ret")

# For each friday, compute 26w vol for each holding (point-in-time: use data UP TO but not including friday)
fridays = sorted(act["friday_date"].unique())
LOOKBACK = 26

results = []
for fri in fridays:
    holdings = act[act["friday_date"] == fri]["symbol"].tolist()
    # Use weeks strictly before this friday
    hist = ret_pivot[ret_pivot.index < fri][holdings]
    hist = hist.tail(LOOKBACK)
    if len(hist) < LOOKBACK:
        # burn-in: skip vol check, mark as EW
        for s in holdings:
            results.append({"friday_date": fri, "symbol": s, "vol": np.nan, "burn_in": True})
        continue
    vols = hist.std()
    for s in holdings:
        results.append(
            {"friday_date": fri, "symbol": s, "vol": vols.get(s, np.nan), "burn_in": False}
        )

vol_df = pd.DataFrame(results)

print("=== Vol computation complete ===")
print("Total rows:", len(vol_df))
print("Burn-in weeks (EW fallback):", vol_df[vol_df["burn_in"]]["friday_date"].nunique())
print("Non-burn-in weeks:", vol_df[~vol_df["burn_in"]]["friday_date"].nunique())
print()
print("=== Vol distribution (non-burn-in) ===")
v = vol_df[~vol_df["burn_in"]]["vol"].dropna()
print(v.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).round(4))
print()
print("=== Symbols with missing vol (non-burn-in) ===")
missing = vol_df[(~vol_df["burn_in"]) & (vol_df["vol"].isna())]
print("Count:", len(missing))
if len(missing) > 0:
    print(missing.groupby("symbol").size().sort_values(ascending=False).head(10))

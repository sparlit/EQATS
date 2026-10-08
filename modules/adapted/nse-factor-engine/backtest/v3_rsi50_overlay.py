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
V3 + Day15 RSI<50 Overlay
Confirmed result: CAGR 37.83% | Sharpe 1.484 | MaxDD -19.82%
Backtest period: Jan 2016 -> Jun 2026 (126 months)
Weights: 60/40 (12m:6m momentum, vol-adjusted, z-scored)
"""

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

COST = 0.0004
PORTFOLIO_N = 25
CHECK_DAY = 15
RSI_THRESH = 50
RESULTS_DIR = "backtest/results"
ACTIVITY_FILE = "backtest/results/MR_M_V3_activity_31082026.csv"
PRICES_PATH = "backtest/data/prices_backtest.parquet"

# ── Load prices ───────────────────────────────────────────────────────────────
print("Loading prices ...")
prices = pd.read_parquet(PRICES_PATH, columns=["symbol", "date", "open", "close"])
prices["date"] = pd.to_datetime(prices["date"])
prices_by_sym = {
    sym: grp.sort_values("date").reset_index(drop=True) for sym, grp in prices.groupby("symbol")
}
print(f"  {len(prices_by_sym)} symbols")
del prices


# ── Wilder RSI (simple average, not EMA) ─────────────────────────────────────
def wilder_rsi(closes):
    if len(closes) < 15:
        return np.nan
    deltas = np.diff(closes[-15:])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains.mean()
    avg_loss = losses.mean()
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


# ── Load activity ─────────────────────────────────────────────────────────────
print("Loading activity CSV ...")
act = pd.read_csv(ACTIVITY_FILE, parse_dates=["friday_date", "signal_date"])

all_periods = sorted(act["friday_date"].unique())
period_to_next = {all_periods[i]: all_periods[i + 1] for i in range(len(all_periods) - 1)}

price_lookup = act[act["action"].isin(["BUY", "HOLD", "SELL"])][
    ["friday_date", "symbol", "price"]
].rename(columns={"friday_date": "next_period", "price": "next_price"})

holdings = act[act["action"].isin(["BUY", "HOLD"])].copy()
holdings = holdings[holdings["friday_date"].isin(period_to_next)].copy()
holdings["next_period"] = holdings["friday_date"].map(period_to_next)
holdings = holdings.merge(price_lookup, on=["next_period", "symbol"], how="left")
holdings["normal_ret"] = holdings["next_price"] / holdings["price"] - 1

# ── Day15 RSI overlay ─────────────────────────────────────────────────────────
print(f"Computing Day15 RSI ({len(holdings)} holdings) ...")
mid15_rsi_list, exit15_open = [], []

for _, row in holdings.iterrows():
    sym = row["symbol"]
    entry = row["friday_date"]
    next_per = row["next_period"]
    sym_df = prices_by_sym.get(sym)

    if sym_df is None:
        mid15_rsi_list.append(np.nan)
        exit15_open.append(np.nan)
        continue

    intra = sym_df[(sym_df["date"] >= entry) & (sym_df["date"] < next_per)].reset_index(drop=True)

    if len(intra) >= CHECK_DAY:
        d15_date = intra.loc[CHECK_DAY - 1, "date"]
        prior_d15 = sym_df[sym_df["date"] <= d15_date]["close"].values
        mid15_rsi_list.append(wilder_rsi(prior_d15))
        if len(intra) > CHECK_DAY:
            exit15_open.append(intra.loc[CHECK_DAY, "open"])
        else:
            exit15_open.append(intra.loc[CHECK_DAY - 1, "close"])
    else:
        mid15_rsi_list.append(np.nan)
        exit15_open.append(np.nan)

holdings["mid15_rsi"] = mid15_rsi_list
holdings["exit15_open"] = exit15_open
holdings["rsi_exit"] = (holdings["mid15_rsi"] < RSI_THRESH) & holdings["mid15_rsi"].notna()
holdings["mid_ret"] = holdings["exit15_open"] / holdings["price"] - 1
holdings["stock_ret"] = np.where(holdings["rsi_exit"], holdings["mid_ret"], holdings["normal_ret"])
holdings["extra_trade"] = holdings["rsi_exit"].astype(int)

rsi_computable = holdings["mid15_rsi"].notna().sum()
rsi_triggered = holdings["rsi_exit"].sum()
print(f"  Day15 RSI computable : {rsi_computable} ({rsi_computable / len(holdings) * 100:.1f}%)")
print(f"  Triggered (RSI<50)   : {rsi_triggered} ({rsi_triggered / len(holdings) * 100:.1f}%)")

# ── Period returns + costs ────────────────────────────────────────────────────
ew_ret = holdings.groupby("next_period")["stock_ret"].mean().rename("port_ret")
extra = holdings.groupby("next_period")["extra_trade"].sum().rename("extra_trades")
period_rets = pd.concat([ew_ret, extra], axis=1).reset_index()
period_rets.columns = ["friday_date", "port_ret", "extra_trades"]

trade_counts = (
    act[act["action"].isin(["BUY", "SELL"])]
    .groupby("friday_date")
    .size()
    .reset_index(name="n_trades")
)
period_rets = period_rets.merge(trade_counts, on="friday_date", how="left")
period_rets["n_trades"] = period_rets["n_trades"].fillna(0)
period_rets["extra_trades"] = period_rets["extra_trades"].fillna(0)
period_rets["cost_drag"] = (
    (period_rets["n_trades"] + period_rets["extra_trades"]) * COST / PORTFOLIO_N
)
period_rets["net_ret"] = period_rets["port_ret"] - period_rets["cost_drag"]

avg_cost = period_rets["cost_drag"].mean()
total_extra = int(period_rets["extra_trades"].sum())

# ── Metrics ───────────────────────────────────────────────────────────────────
s = period_rets["net_ret"].dropna()
nav = (1 + s).cumprod()
years = len(nav) / 12
cagr = nav.iloc[-1] ** (1 / years) - 1
sharpe = s.mean() / s.std() * np.sqrt(12)
max_dd = (nav / nav.cummax() - 1).min()
worst = s.min()
tail = s[s <= s.quantile(0.10)].mean()

print(f"\n{'=' * 55}")
print("RESULTS: V3 + Day15 RSI<50 overlay (net of costs)")
print(f"{'=' * 55}")
print(f"  Periods          : {len(s)}")
print(f"  Total RSI exits  : {total_extra}")
print(f"  Avg cost/period  : {avg_cost * 100:.4f}%")
print("")
print(f"  CAGR        : {cagr * 100:.2f}%")
print(f"  Sharpe      : {sharpe:.3f}")
print(f"  Max DD      : {max_dd * 100:.2f}%")
print(f"  Worst month : {worst * 100:.2f}%")
print(f"  Mean tail   : {tail * 100:.2f}%")
print(f"{'=' * 55}")
print("\nConfirmed baseline: CAGR 37.83% | Sharpe 1.484 | MaxDD -19.82%")

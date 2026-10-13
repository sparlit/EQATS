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
V3 + Day15 RSI Overlay with Mid-Month Replacement
===================================================
Extends v3_rsi50_overlay.py: instead of going to cash after a day-15 RSI exit,
deploys the freed capital into the best available watchlist stock
with day-15 RSI > RSI_ENTRY_THRESH.

Replacement logic:
  Pool   : stocks ranked <= BUFFER_ZONE in that month's signal, not already in portfolio
  Filter : day-15 RSI > RSI_ENTRY_THRESH (configurable; default = RSI_EXIT_THRESH)
  Sort   : by mr_rank ascending (best momentum first)
  Entry  : day-16 open (same day exit proceeds are freed)
  Exit   : next month exec_date open

Slot return for replaced exit:
  (1 + exit_ret) * (1 + replacement_ret) - 1

Key configurable parameters:
  RSI_EXIT_THRESH  = 50   exit held stock if day-15 RSI < this
  RSI_ENTRY_THRESH = 50   replacement must have day-15 RSI > this

Baseline (v3_rsi50_overlay.py -- goes to cash):
  CAGR 37.83% | Sharpe 1.484 | MaxDD -19.82%

Run from repo root:
  cd /home/ec2-user/nse-factor-engine
  python3 backtest/v3_rsi_replacement_overlay.py
"""

import gc
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/ec2-user/nse-factor-engine")

# ── Config ────────────────────────────────────────────────────────────────────
COST = 0.0004
PORTFOLIO_N = 25
CHECK_DAY = 15
RSI_EXIT_THRESH = 50  # exit held stock if day-15 RSI < this
RSI_ENTRY_THRESH = 50  # replacement must have day-15 RSI > this
BUFFER_ZONE = 38
W_12M, W_6M = 0.60, 0.40

RESULTS_DIR = "backtest/results"
ACTIVITY_FILE = "backtest/results/MR_M_V3_activity_31082026.csv"
PRICES_PATH = "backtest/data/prices_backtest.parquet"
FRI_SIG_DIR = "backtest/signals/historical"
RUN_DATE = time.strftime("%d%m%Y")

# ── Load prices ───────────────────────────────────────────────────────────────
print("Loading prices ...")
prices = pd.read_parquet(PRICES_PATH, columns=["symbol", "date", "open", "close"])
prices["date"] = pd.to_datetime(prices["date"])
prices_by_sym = {
    sym: grp[["date", "open", "close"]].sort_values("date").reset_index(drop=True)
    for sym, grp in prices.groupby("symbol")
}
all_trading_days = sorted(pd.to_datetime(prices["date"].unique()))
print(f"  {len(prices_by_sym)} symbols | {len(all_trading_days)} trading days")
del prices
gc.collect()


# ── RSI (identical to v3_rsi50_overlay.py) ───────────────────────────────────
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


def compute_rsi(sym, up_to_date):
    sym_df = prices_by_sym.get(sym)
    if sym_df is None:
        return np.nan
    closes = sym_df[sym_df["date"] <= up_to_date]["close"].values
    return wilder_rsi(closes)


def get_open(sym, date):
    """Open price for sym on date; falls back to nearest prior trading day."""
    sym_df = prices_by_sym.get(sym)
    if sym_df is None:
        return np.nan
    row = sym_df[sym_df["date"] == date]
    if not row.empty:
        return float(row.iloc[0]["open"])
    prior = sym_df[sym_df["date"] < date]
    return float(prior.iloc[-1]["open"]) if not prior.empty else np.nan


# ── Scoring (identical to v3_backtest.py) ────────────────────────────────────
def compute_mr_scores(signals_df):
    df = signals_df[signals_df["in_universe"]].copy()
    bad = (
        df["vol_252"].isna() | (df["vol_252"] == 0) | df["ret_12m1m"].isna() | df["ret_6m1m"].isna()
    )
    df = df[~bad].copy()
    if len(df) < 10:
        return pd.DataFrame()
    df["mr_12"] = df["ret_12m1m"] / df["vol_252"]
    df["mr_6"] = df["ret_6m1m"] / df["vol_252"]
    df["z_12"] = (df["mr_12"] - df["mr_12"].mean()) / df["mr_12"].std(ddof=1)
    df["z_6"] = (df["mr_6"] - df["mr_6"].mean()) / df["mr_6"].std(ddof=1)
    df["weighted_z"] = W_12M * df["z_12"] + W_6M * df["z_6"]
    df["norm_momentum_score"] = df["weighted_z"].apply(
        lambda wz: 1 + wz if wz >= 0 else 1.0 / (1.0 - wz)
    )
    df["mr_rank"] = df["norm_momentum_score"].rank(method="min", ascending=False).astype("Int64")
    return df.sort_values("mr_rank").reset_index(drop=True)


def signal_path(sig_date):
    d = pd.Timestamp(sig_date).strftime("%d%m%Y")
    return f"{FRI_SIG_DIR}/signals_{d}.parquet"


# ── Load activity ─────────────────────────────────────────────────────────────
print("Loading activity CSV ...")
act = pd.read_csv(ACTIVITY_FILE, parse_dates=["friday_date", "signal_date"])

all_periods = sorted(pd.to_datetime(act["friday_date"].unique()))
period_to_next = {all_periods[i]: all_periods[i + 1] for i in range(len(all_periods) - 1)}

# Signal date per exec period
period_sig_map = (
    act[["friday_date", "signal_date"]]
    .drop_duplicates("friday_date")
    .assign(friday_date=lambda x: pd.to_datetime(x["friday_date"]))
    .set_index("friday_date")["signal_date"]
    .to_dict()
)

# ── Per-period processing ─────────────────────────────────────────────────────
print(f"Processing {len(all_periods) - 1} periods ...")
t0 = time.time()
period_results = []
total_exits = 0
total_replaced = 0

for period in all_periods[:-1]:
    next_per = period_to_next[period]

    held = act[
        (pd.to_datetime(act["friday_date"]) == period) & (act["action"].isin(["BUY", "HOLD"]))
    ].copy()
    if held.empty:
        continue

    # Trading days in this period [exec_date, next_exec_date)
    intra_days = [td for td in all_trading_days if period <= td < next_per]

    # ── Not enough trading days for mid-month check → normal hold ─────────────
    if len(intra_days) < CHECK_DAY:
        for _, row in held.iterrows():
            ep = get_open(row["symbol"], next_per)
            if np.isnan(row["price"]) or row["price"] == 0 or np.isnan(ep):
                continue
            period_results.append(
                {
                    "period": period,
                    "symbol": row["symbol"],
                    "slot_ret": ep / row["price"] - 1,
                    "extra_trades": 0,
                }
            )
        continue

    d15_date = intra_days[CHECK_DAY - 1]
    d16_date = intra_days[CHECK_DAY] if len(intra_days) > CHECK_DAY else intra_days[-1]

    # ── Day-15 RSI for all holdings ───────────────────────────────────────────
    held = held.copy()
    held["d15_rsi"] = held["symbol"].apply(lambda s: compute_rsi(s, d15_date))
    held["exit15_open"] = held["symbol"].apply(lambda s: get_open(s, d16_date))
    held["rsi_exit"] = (held["d15_rsi"] < RSI_EXIT_THRESH) & held["d15_rsi"].notna()

    exits = held[held["rsi_exit"]].copy()
    no_exits = held[~held["rsi_exit"]].copy()
    n_exits = len(exits)
    total_exits += n_exits

    # ── Normal holds ──────────────────────────────────────────────────────────
    for _, row in no_exits.iterrows():
        ep = get_open(row["symbol"], next_per)
        if np.isnan(row["price"]) or row["price"] == 0 or np.isnan(ep):
            continue
        period_results.append(
            {
                "period": period,
                "symbol": row["symbol"],
                "slot_ret": ep / row["price"] - 1,
                "extra_trades": 0,
            }
        )

    # ── Build replacement pool from watchlist ─────────────────────────────────
    replacements = []
    if n_exits > 0:
        sig_date = period_sig_map.get(period)
        spath = signal_path(sig_date) if pd.notna(sig_date) else None
        if spath and os.path.exists(spath):
            signals = pd.read_parquet(spath)
            ranked_df = compute_mr_scores(signals)
            if not ranked_df.empty:
                portfolio_syms = set(held["symbol"])
                watchlist = (
                    ranked_df[
                        (ranked_df["mr_rank"] <= BUFFER_ZONE)
                        & (~ranked_df["symbol"].isin(portfolio_syms))
                    ]
                    .sort_values("mr_rank")
                    .reset_index(drop=True)
                )

                for _, wrow in watchlist.iterrows():
                    if len(replacements) >= n_exits:
                        break
                    sym = wrow["symbol"]
                    d15_rsi = compute_rsi(sym, d15_date)
                    if pd.isna(d15_rsi) or d15_rsi <= RSI_ENTRY_THRESH:
                        continue
                    d16_open = get_open(sym, d16_date)
                    next_open = get_open(sym, next_per)
                    if np.isnan(d16_open) or d16_open == 0 or np.isnan(next_open):
                        continue
                    replacements.append(
                        {
                            "symbol": sym,
                            "mr_rank": int(wrow["mr_rank"]),
                            "d16_open": d16_open,
                            "next_open": next_open,
                            "d15_rsi": d15_rsi,
                        }
                    )

    # ── RSI exits: replace or go to cash ─────────────────────────────────────
    replaced = 0
    for idx, (_, erow) in enumerate(exits.iterrows()):
        entry_price = erow["price"]
        exit15_open = erow["exit15_open"]

        if np.isnan(entry_price) or entry_price == 0:
            continue

        exit_ret = (
            float(exit15_open) / entry_price - 1
            if pd.notna(exit15_open) and exit15_open > 0
            else 0.0
        )

        if idx < len(replacements):
            repl = replacements[idx]
            repl_ret = repl["next_open"] / repl["d16_open"] - 1
            slot_ret = (1 + exit_ret) * (1 + repl_ret) - 1
            extra = 2  # sell exited + buy replacement
            replaced += 1
        else:
            slot_ret = exit_ret  # cash for rest of period
            extra = 1  # just the exit sell

        period_results.append(
            {
                "period": period,
                "symbol": erow["symbol"],
                "slot_ret": slot_ret,
                "extra_trades": extra,
            }
        )

    total_replaced += replaced
    gc.collect()

elapsed = time.time() - t0
print(f"  Processed in {elapsed / 60:.1f} min")
print(f"  Total RSI exits  : {total_exits}")
print(
    f"  Total replaced   : {total_replaced} ({total_replaced / max(1, total_exits) * 100:.1f}% of exits)"
)
print(f"  Went to cash     : {total_exits - total_replaced}")

# ── Period returns + costs ────────────────────────────────────────────────────
results_df = pd.DataFrame(period_results)
port_ret = results_df.groupby("period")["slot_ret"].mean().rename("port_ret")
extra_trades = results_df.groupby("period")["extra_trades"].sum().rename("extra_trades")

trade_counts = (
    act[act["action"].isin(["BUY", "SELL"])]
    .assign(friday_date=lambda x: pd.to_datetime(x["friday_date"]))
    .groupby("friday_date")
    .size()
    .reset_index(name="n_trades")
    .rename(columns={"friday_date": "period"})
)

period_df = pd.concat([port_ret, extra_trades], axis=1).reset_index()
period_df = period_df.merge(trade_counts, on="period", how="left")
period_df["n_trades"] = period_df["n_trades"].fillna(0)
period_df["extra_trades"] = period_df["extra_trades"].fillna(0)
period_df["cost_drag"] = (period_df["n_trades"] + period_df["extra_trades"]) * COST / PORTFOLIO_N
period_df["net_ret"] = period_df["port_ret"] - period_df["cost_drag"]

# ── Metrics ───────────────────────────────────────────────────────────────────
s = period_df["net_ret"].dropna()
nav = (1 + s).cumprod()
years = len(nav) / 12
cagr = nav.iloc[-1] ** (1 / years) - 1
sharpe = s.mean() / s.std() * np.sqrt(12)
max_dd = (nav / nav.cummax() - 1).min()
worst = s.min()
tail = s[s <= s.quantile(0.10)].mean()
avg_cost = period_df["cost_drag"].mean()

print(f"\n{'=' * 62}")
print("RESULTS: V3 + Day15 RSI Overlay with Mid-Month Replacement")
print(f"{'=' * 62}")
print(f"  RSI_EXIT_THRESH  : {RSI_EXIT_THRESH}")
print(f"  RSI_ENTRY_THRESH : {RSI_ENTRY_THRESH}")
print(f"  Periods          : {len(s)}")
print(f"  Total RSI exits  : {total_exits}")
print(f"  Replaced         : {total_replaced} ({total_replaced / max(1, total_exits) * 100:.1f}%)")
print(f"  Went to cash     : {total_exits - total_replaced}")
print(f"  Avg cost/period  : {avg_cost * 100:.4f}%")
print("")
print(f"  CAGR        : {cagr * 100:.2f}%")
print(f"  Sharpe      : {sharpe:.3f}")
print(f"  Max DD      : {max_dd * 100:.2f}%")
print(f"  Worst month : {worst * 100:.2f}%")
print(f"  Mean tail   : {tail * 100:.2f}%")
print(f"{'=' * 62}")
print("  vs V3 overlay (cash): CAGR 37.83% | Sharpe 1.484 | MaxDD -19.82%")
print(f"  CAGR delta          : {(cagr * 100 - 37.83):+.2f}%")
print(f"{'=' * 62}")

# ── Save ──────────────────────────────────────────────────────────────────────
os.makedirs(RESULTS_DIR, exist_ok=True)
out_path = f"{RESULTS_DIR}/MR_M_V3_rsi_replacement_{RUN_DATE}.csv"
period_df.to_csv(out_path, index=False)
print(f"\n  Saved: {out_path}")
print(f"  Time : {elapsed / 60:.1f} min")

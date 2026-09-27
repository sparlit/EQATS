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
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

ACTIVITY = "/home/ec2-user/nse-factor-engine/backtest/results/backtest_portfolio_activity_09072026.parquet"
PRICES = "/home/ec2-user/nse-factor-engine/backtest/data/prices_backtest.parquet"
LOOKBACK = 26
MAX_W = 0.10

act = pd.read_parquet(ACTIVITY)
act = act[(act["cell_id"] == "G6_C6") & (act["action"].isin(["BUY", "HOLD"]))].copy()
act["friday_date"] = pd.to_datetime(act["friday_date"])
fridays = sorted(act["friday_date"].unique())

all_symbols = act["symbol"].unique().tolist()
print(f"Loading prices for {len(all_symbols)} unique symbols...")
prices = pd.read_parquet(PRICES, filters=[("symbol", "in", all_symbols)])
prices["date"] = pd.to_datetime(prices["date"])
prices["week"] = prices["date"].dt.to_period("W").apply(lambda r: r.end_time.date())
prices["week"] = pd.to_datetime(prices["week"])
weekly_close = prices.sort_values("date").groupby(["symbol", "week"])["close"].last()
weekly_ret = weekly_close.groupby(level="symbol").pct_change().reset_index()
weekly_ret.columns = ["symbol", "week", "ret"]
del prices
print("Weekly returns computed.")


def hrp_weights(cov, symbols):
    corr = np.corrcoef(cov.values)
    dist = np.sqrt(np.clip((1 - corr) / 2, 0, None))
    np.fill_diagonal(dist, 0)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="single")
    order = leaves_list(link)
    ordered = [symbols[i] for i in order]

    def bisect(items):
        if len(items) == 1:
            return {items[0]: 1.0}
        mid = len(items) // 2
        left, right = items[:mid], items[mid:]

        def cluster_var(cluster):
            c = cov.loc[cluster, cluster]
            w = np.ones(len(cluster)) / len(cluster)
            return float(w @ c.values @ w)

        cv_l = cluster_var(left)
        cv_r = cluster_var(right)
        total = cv_l + cv_r
        alpha = 1 - cv_l / total if total > 0 else 0.5
        wl = bisect(left)
        wr = bisect(right)
        out = {}
        for s, w in wl.items():
            out[s] = w * (1 - alpha)
        for s, w in wr.items():
            out[s] = w * alpha
        return out

    return bisect(ordered)


def apply_cap(w_series, cap):
    w = w_series.copy()
    for _ in range(50):
        over = w[w > cap]
        if over.empty:
            break
        excess = (w[w > cap] - cap).sum()
        w[w > cap] = cap
        under = w < cap
        if under.sum() == 0:
            break
        w[under] += excess * (w[under] / w[under].sum())
    return w


records = []

for i, fri in enumerate(fridays):
    if i % 50 == 0:
        print(f"  Processing week {i + 1}/{len(fridays)}: {fri.date()}")

    holdings = act[act["friday_date"] == fri]["symbol"].tolist()
    n = len(holdings)

    # History: LOOKBACK weeks strictly before this friday
    sym_data = weekly_ret[(weekly_ret["symbol"].isin(holdings)) & (weekly_ret["week"] < fri)]
    sym_data = sym_data.sort_values("week").groupby("symbol").tail(LOOKBACK)
    hist = sym_data.pivot(index="week", columns="symbol", values="ret")
    hist = hist.dropna(axis=1)
    available = hist.columns.tolist()

    burn_in = (len(hist) < LOOKBACK) or (len(available) < 2)

    # Vol-Scaled
    if burn_in:
        vs_w = dict.fromkeys(holdings, 1 / n)
    else:
        vols = hist.std()
        inv_vol = 1.0 / vols.clip(lower=1e-6)
        raw_w = inv_vol / inv_vol.sum()
        capped = apply_cap(raw_w, MAX_W)
        missing = [s for s in holdings if s not in available]
        if missing:
            miss_w = len(missing) / n
            capped = capped * (1 - miss_w)
            miss_each = miss_w / len(missing)
            vs_w = {s: float(capped.get(s, miss_each)) for s in holdings}
        else:
            vs_w = {s: float(capped[s]) for s in holdings}

    # HRP
    if burn_in or len(available) < 2:
        hrp_w = dict.fromkeys(holdings, 1 / n)
    else:
        cov = hist.cov()
        raw_hrp = hrp_weights(cov, available)
        hrp_series = apply_cap(pd.Series(raw_hrp), MAX_W)
        missing = [s for s in holdings if s not in available]
        if missing:
            miss_w = len(missing) / n
            hrp_series = hrp_series * (1 - miss_w)
            miss_each = miss_w / len(missing)
            hrp_w = {s: float(hrp_series.get(s, miss_each)) for s in holdings}
        else:
            hrp_w = {s: float(hrp_series[s]) for s in holdings}

    # Next week stock returns (fri close → next fri close)
    cutoff = fri + pd.Timedelta(days=7)
    next_raw = (
        weekly_ret[(weekly_ret["symbol"].isin(holdings)) & (weekly_ret["week"] > cutoff)]
        .sort_values("week")
        .groupby("symbol", as_index=False)
        .first()
    )
    next_rets = next_raw.set_index("symbol")["ret"]

    # All 3 use same stock returns, different weights
    ew_w = dict.fromkeys(holdings, 1 / n)
    ew_ret_val = sum(ew_w.get(s, 0) * next_rets.get(s, 0) for s in holdings)
    vs_ret_val = sum(vs_w.get(s, 0) * next_rets.get(s, 0) for s in holdings)
    hrp_ret_val = sum(hrp_w.get(s, 0) * next_rets.get(s, 0) for s in holdings)

    records.append(
        {
            "friday_date": fri,
            "ew_ret": ew_ret_val,
            "vs_ret": vs_ret_val,
            "hrp_ret": hrp_ret_val,
            "burn_in": burn_in,
            "n_holdings": n,
        }
    )

df = pd.DataFrame(records).set_index("friday_date")


def metrics(rets, label):
    rets = rets.dropna()
    n = len(rets)
    cagr = (1 + rets).prod() ** (52 / n) - 1
    sharpe = rets.mean() / rets.std() * np.sqrt(52)
    neg = rets[rets < 0]
    sortino = rets.mean() / neg.std() * np.sqrt(52) if len(neg) > 0 else np.nan
    nav = (1 + rets).cumprod()
    roll_max = nav.cummax()
    dd = (nav - roll_max) / roll_max
    max_dd = dd.min()
    gut_punch = (rets < -0.10).sum()
    print(
        f"{label:<20} CAGR={cagr * 100:.2f}%  Sharpe={sharpe:.3f}  Sortino={sortino:.3f}  MaxDD={max_dd * 100:.2f}%  GutPunch={gut_punch}"
    )


print()
print("=== Position Sizing Comparison — G6_C6 ===")
print(f"Weeks: {len(df)}  |  Burn-in weeks (EW fallback): {df['burn_in'].sum()}")
print()
metrics(df["ew_ret"], "EW (baseline)")
metrics(df["vs_ret"], "Vol-Scaled")
metrics(df["hrp_ret"], "HRP")

print()
print("=== DIAGNOSTICS ===")
print()
print("Weekly return correlations:")
print(df[["ew_ret", "vs_ret", "hrp_ret"]].corr().round(3).to_string())
print()
vs_wins = (df["vs_ret"] > df["ew_ret"]).sum()
hrp_wins = (df["hrp_ret"] > df["ew_ret"]).sum()
print(f"Weeks Vol-Scaled beats EW: {vs_wins}/{len(df)} ({vs_wins / len(df) * 100:.1f}%)")
print(f"Weeks HRP beats EW: {hrp_wins}/{len(df)} ({hrp_wins / len(df) * 100:.1f}%)")

# Top 5 DD periods for each
print()
for col, label in [("ew_ret", "EW"), ("vs_ret", "Vol-Scaled"), ("hrp_ret", "HRP")]:
    r = df[col].dropna()
    nav = (1 + r).cumprod()
    dd = (nav - nav.cummax()) / nav.cummax()
    worst = dd.nsmallest(5)
    print(f"{label} worst DD dates:")
    for d, v in worst.items():
        print(f"  {d.date()}: {v * 100:.2f}%")
    print()

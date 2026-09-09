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


"""v8: US large-cap monthly momentum (us/PROTOCOL_V8.md).

    python -m us.momentum

Reuses backtest.monthly.simulate via adapter dicts; point-in-time S&P 500
membership enforced through select_fn.
"""
from pathlib import Path

import pandas as pd
from backtest import monthly

DATA = Path(__file__).resolve().parent / "data"


def load():
    px = pd.read_parquet(DATA / "prices.parquet")
    close = px.pivot_table(index="date", columns="symbol", values="close")
    open_ = px.pivot_table(index="date", columns="symbol", values="open")

    m = pd.read_csv(DATA / "sp500_hist.csv", parse_dates=["date"])
    m["set"] = m["tickers"].map(lambda s: frozenset(t.strip().replace(".", "-") for t in s.split(",")))
    members = m.set_index("date")["set"].sort_index().reindex(close.index, method="ffill")

    p = {
        "close": close,
        "open": open_,
        # membership replaces the turnover filter; make it a no-op
        "turnover_lacs": pd.DataFrame(1e9, index=close.index, columns=close.columns),
    }
    ctx = {"bench": close["SPY"], "stocks": [c for c in close.columns if c != "SPY"]}
    return p, ctx, members


def member_top(members, n=20):
    def sel(t, m):
        mem = members.loc[t] or frozenset()
        s = m[m.index.isin(mem)]
        return list(s.nlargest(n).index)

    return sel


def window(p, ctx, start, end):
    idx = p["close"].index
    mask = pd.Series(True, index=idx)
    if start:
        mask &= idx >= start
    if end:
        mask &= idx <= end
    q = {k: v.loc[mask.values] for k, v in p.items()}
    c = {"bench": ctx["bench"].loc[mask.values], "stocks": ctx["stocks"]}
    return q, c


def run():
    p, ctx, members = load()
    for label, start, end in (("IN-SAMPLE 2023-26", "2022-01-03", None), ("OUT-OF-SAMPLE 2016-22", None, "2022-12-31")):
        print(f"\n=== {label} ===")
        q, c = window(p, ctx, start, end)
        base = {"regime_filter": True, "cost": 0.001, "select_fn": member_top(members)}
        monthly.report("v8 baseline", monthly.simulate(q, c, **base))
        monthly.report("spy_no_regime", monthly.simulate(q, c, **{**base, "regime_filter": False}))
        monthly.report("top10", monthly.simulate(q, c, **{**base, "select_fn": member_top(members, 10)}))
        monthly.report("top30", monthly.simulate(q, c, **{**base, "select_fn": member_top(members, 30)}))
        monthly.report("skip0", monthly.simulate(q, c, **{**base, "skip": 0}))
        monthly.report("cost_2.5x", monthly.simulate(q, c, **{**base, "cost": 0.0025}))


if __name__ == "__main__":
    run()

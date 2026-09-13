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


"""v12: short-horizon news-pop reaction, India + US (PROTOCOL_V12.md).

    python -m backtest.reaction

Grid: entry {next_open, event_close} × hold {1,2,5} sessions.
Reports gross mean/median excess and cost-adjusted mean (net).
"""
import numpy as np
import pandas as pd
from backtest import features
from ingest import etf_list


def horizon_study(close, open_, events, bench_close, bench_open, rt_cost, label):
    """events: list of (symbol, t_idx). Prints the entry×hold grid."""
    dates = close.index
    print(f"--- {label}: {len(events)} events ---")
    for entry in ("next_open", "event_close"):
        for hold in (1, 2, 5):
            rows = []
            for sym, t in events:
                if entry == "next_open":
                    e_idx, x_idx = t + 1, t + hold
                    p0 = open_.iloc[e_idx].get(sym)
                    b0 = bench_open.iloc[e_idx]
                else:
                    e_idx, x_idx = t, t + hold
                    p0 = close.iloc[e_idx].get(sym)
                    b0 = bench_close.iloc[e_idx]
                if x_idx >= len(dates):
                    continue
                p1 = close.iloc[x_idx].get(sym)
                if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
                    continue
                raw = p1 / p0 - 1
                b = bench_close.iloc[x_idx] / b0 - 1
                rows.append(100 * (raw - b))
            r = pd.Series(rows)
            if not len(r):
                continue
            net = r.mean() - 100 * rt_cost
            print(
                f"  {entry:>11} h{hold}: n={len(r):4d}  "
                f"mean={r.mean():+6.2f}  median={r.median():+6.2f}  "
                f"win={100 * (r > 0).mean():4.1f}%  net_mean={net:+6.2f}"
            )


def india():
    p = features._panel(None, None)
    close, open_, vol = p["close"], p["open"], p["volume"]
    stocks = [s for s in close.columns if s not in etf_list.symbols()]
    ma200 = close.rolling(200).mean()
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    ret = close.pct_change()
    volx = vol >= 3 * vol.rolling(20).mean().shift(1)
    pop = ((ret >= 0.05) & volx & (close > ma200) & liquid.fillna(False))[stocks]

    dates = close.index
    ev, last = [], {}
    for t, sym in zip(*np.where(pop.values), strict=False):
        s = pop.columns[sym]
        if t - last.get(s, -99) <= 21 or t + 6 >= len(dates):
            continue
        last[s] = t
        ev.append((s, t, dates[t]))
    bench_c, bench_o = close["NIFTYBEES"], open_["NIFTYBEES"]
    for label, lo, hi in (
        ("INDIA IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
        ("INDIA OUT-OF-SAMPLE 2017-22", "2017-01-01", "2023-01-01"),
    ):
        sel = [(s, t) for s, t, d in ev if lo <= str(d.date()) < hi]
        horizon_study(close, open_, sel, bench_c, bench_o, 0.005, label)


def us():
    from us.event_study import load

    close, open_, vol, member_at = load()
    stocks = [c for c in close.columns if c != "SPY"]
    ma200 = close.rolling(200).mean()
    ret = close.pct_change()
    volx = vol >= 3 * vol.rolling(20).mean().shift(1)
    pop = ((ret >= 0.07) & volx & (close > ma200))[stocks]
    dates = close.index
    ev, last = [], {}
    for t, sym in zip(*np.where(pop.values), strict=False):
        s = pop.columns[sym]
        mem = member_at.iloc[t]
        if not mem or s not in mem:
            continue
        if t - last.get(s, -99) <= 21 or t + 6 >= len(dates):
            continue
        last[s] = t
        ev.append((s, t, dates[t]))
    bench_c, bench_o = close["SPY"], open_["SPY"]
    for label, lo, hi in (
        ("US IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
        ("US OUT-OF-SAMPLE 2017-22", "2017-01-01", "2023-01-01"),
    ):
        sel = [(s, t) for s, t, d in ev if lo <= str(d.date()) < hi]
        horizon_study(close, open_, sel, bench_c, bench_o, 0.002, label)


if __name__ == "__main__":
    us()
    india()

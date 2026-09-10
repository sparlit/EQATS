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


"""v6 rally-following event study (us/PROTOCOL_V6.md).

    python us/event_study.py

Enumerates every "obvious rally" event in the point-in-time S&P 500 and
measures forward excess returns vs SPY. No portfolio sim — the claim under
test is about the per-event distribution ("guaranteed profit").
"""
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"


def load():
    px = pd.read_parquet(DATA / "prices.parquet")
    close = px.pivot_table(index="date", columns="symbol", values="close")
    open_ = px.pivot_table(index="date", columns="symbol", values="open")
    vol = px.pivot_table(index="date", columns="symbol", values="volume")

    m = pd.read_csv(DATA / "sp500_hist.csv", parse_dates=["date"])
    m["set"] = m["tickers"].map(lambda s: frozenset(t.strip().replace(".", "-") for t in s.split(",")))
    m = m.set_index("date")["set"].sort_index()
    member_at = m.reindex(close.index, method="ffill")
    return close, open_, vol, member_at


def events(close, open_, vol, member_at, pop=0.07, vmult=3.0, hold=21, trend_filter=True):
    ret = close.pct_change()
    vol_ok = vol >= vmult * vol.rolling(20).mean().shift(1)
    cand = (ret >= pop) & vol_ok
    if trend_filter:
        cand &= close > close.rolling(200).mean()
    cand = cand.drop(columns=["SPY"], errors="ignore")

    spy_c, spy_o = close["SPY"], open_["SPY"]
    dates = close.index
    rows, last_event = [], {}
    for t_idx, sym in zip(*np.where(cand.values), strict=False):
        d = dates[t_idx]
        sym_name = cand.columns[sym]
        if sym_name not in (member_at.loc[d] or frozenset()):
            continue
        if t_idx - last_event.get(sym_name, -(10**9)) <= hold:
            continue
        if t_idx + 1 + hold >= len(dates):
            continue  # not enough future data yet
        e_open = open_.iloc[t_idx + 1][sym_name]
        x_close = close.iloc[t_idx + 1 + hold][sym_name]
        if pd.isna(e_open) or pd.isna(x_close) or e_open <= 0:
            continue
        last_event[sym_name] = t_idx
        raw = x_close / e_open - 1
        spy = spy_c.iloc[t_idx + 1 + hold] / spy_o.iloc[t_idx + 1] - 1
        rows.append({"date": d, "symbol": sym_name, "raw_pct": 100 * raw, "excess_pct": 100 * (raw - spy)})
    return pd.DataFrame(rows)


def report(name, ev):
    if ev.empty:
        print(f"{name}: no events")
        return None
    q = ev.assign(qtr=ev["date"].dt.to_period("Q")).groupby("qtr")["excess_pct"].sum()
    pos_total = q[q > 0].sum()
    out = {
        "variant": name,
        "events": len(ev),
        "mean_excess": round(ev["excess_pct"].mean(), 2),
        "median_excess": round(ev["excess_pct"].median(), 2),
        "win_raw_pct": round(100 * (ev["raw_pct"] > 0).mean(), 1),
        "win_excess_pct": round(100 * (ev["excess_pct"] > 0).mean(), 1),
        "worst_pct": round(ev["raw_pct"].min(), 1),
        "max_qtr_share": round(100 * q.max() / pos_total) if pos_total > 0 else None,
    }
    print(out)
    return out


def main():
    close, open_, vol, member_at = load()
    for label, lo, hi in (
        ("IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
        ("OUT-OF-SAMPLE 2017-22", "2017-01-01", "2023-01-01"),
    ):
        print(f"\n=== {label} ===")

        def win(ev):
            return ev[(ev["date"] >= lo) & (ev["date"] < hi)]

        base = events(close, open_, vol, member_at)
        report("baseline(7%,3x,21d,trend)", win(base))
        for name, kw in (
            ("pop_5", {"pop": 0.05}),
            ("pop_10", {"pop": 0.10}),
            ("vol_2x", {"vmult": 2.0}),
            ("vol_5x", {"vmult": 5.0}),
            ("hold_10", {"hold": 10}),
            ("hold_42", {"hold": 42}),
            ("hold_63", {"hold": 63}),
            ("no_trend", {"trend_filter": False}),
        ):
            report(name, win(events(close, open_, vol, member_at, **kw)))
        win(base).to_csv(DATA / f"v6_events_{lo[:4]}.csv", index=False)


if __name__ == "__main__":
    main()

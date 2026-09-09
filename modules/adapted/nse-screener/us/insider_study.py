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


"""v9 insider-cluster event study (us/PROTOCOL_V9.md).

    python -m us.insider_study

Cluster = ≥3 distinct insiders of one company filing purchases within 21
calendar days, combined ≥$250k. Event = filing that completes the cluster.
Entry next open, hold 63 sessions, excess vs SPY, S&P 500 members only.
"""
import numpy as np
import pandas as pd
from us.event_study import load
from us.event_study import report as ev_report
from us.insiders import load_all

OFFICER_RE = r"CEO|CFO|COO|Pres|Chief"


def clusters(ins: pd.DataFrame, n_insiders=3, min_value=250_000, window=21, officers_only=False) -> pd.DataFrame:
    d = ins.copy()
    if officers_only:
        d = d[d["title"].astype(str).str.contains(OFFICER_RE, case=False, na=False)]
    d["fday"] = d["filing"].dt.normalize()
    d = d.sort_values("fday")
    events = []
    for tkr, g in d.groupby("ticker"):
        g = g.reset_index(drop=True)
        for i in range(len(g)):
            t0 = g.loc[i, "fday"]
            w = g[(g["fday"] > t0 - pd.Timedelta(days=window)) & (g["fday"] <= t0)]
            if w["insider"].nunique() >= n_insiders and w["value"].sum() >= min_value:
                events.append(
                    {
                        "ticker": tkr,
                        "date": t0,
                        "n_insiders": int(w["insider"].nunique()),
                        "value": float(w["value"].sum()),
                    }
                )
    ev = pd.DataFrame(events)
    if ev.empty:
        return ev
    # one event per ticker per hold window (first wins)
    ev = ev.sort_values("date")
    keep, last = [], {}
    for _, r in ev.iterrows():
        if (r["date"] - last.get(r["ticker"], pd.Timestamp("1900-01-01"))).days > 92:
            keep.append(r)
            last[r["ticker"]] = r["date"]
    return pd.DataFrame(keep)


def study(ev, close, open_, member_at, hold=63):
    spy_c, spy_o = close["SPY"], open_["SPY"]
    dates = close.index
    rows = []
    for _, e in ev.iterrows():
        tkr = str(e["ticker"]).replace(".", "-")
        if tkr not in close.columns:
            continue
        pos = dates.searchsorted(e["date"], side="right")  # next session
        if pos + hold >= len(dates) or pos >= len(dates):
            continue
        dates[pos]
        mem = member_at.loc[dates[max(0, pos - 1)]]
        if not mem or tkr not in mem:
            continue
        p0 = open_.iloc[pos][tkr]
        p1 = close.iloc[pos + hold][tkr]
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            continue
        raw = p1 / p0 - 1
        spy = spy_c.iloc[pos + hold] / spy_o.iloc[pos] - 1
        rows.append({"date": e["date"], "symbol": tkr, "raw_pct": 100 * raw, "excess_pct": 100 * (raw - spy)})
    return pd.DataFrame(rows)


def main():
    close, open_, _vol, member_at = load()
    ins = load_all()
    print(f"{len(ins)} insider purchase filings loaded")

    variants = [
        ("baseline(3x,250k,63d)", {}),
        ("cluster_2", {"n_insiders": 2}),
        ("value_100k", {"min_value": 100_000}),
        ("hold_21", {}, 21),
        ("hold_126", {}, 126),
        ("officers_only", {"officers_only": True}),
    ]
    for label, lo, hi in (
        ("IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
        ("OUT-OF-SAMPLE 2016-22", "2016-01-01", "2023-01-01"),
    ):
        print(f"\n=== {label} ===")
        for v in variants:
            name, kw = v[0], v[1]
            hold = v[2] if len(v) > 2 else 63
            ev = clusters(ins, **kw)
            res = study(ev, close, open_, member_at, hold=hold)
            res = res[(res["date"] >= lo) & (res["date"] < hi)]
            ev_report(name, res)


if __name__ == "__main__":
    main()

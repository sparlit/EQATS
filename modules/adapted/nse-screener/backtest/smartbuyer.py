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


"""v18: smart-buyer track records (PROTOCOL_V18.md).

    python -m backtest.smartbuyer
"""
import numpy as np
import pandas as pd
from backtest import features
from ingest import deals_hist, etf_list, renames


def deal_outcomes(hold: int = 63):
    """All net-buy deals with their forward excess. One pass, reused."""
    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    dates = close.index
    bench_c, bench_o = close["NIFTYBEES"], open_["NIFTYBEES"]
    etfs = etf_list.symbols()

    d = deals_hist.load_all()
    d["symbol"] = renames.canonical(d["symbol"])
    d = d[~d["symbol"].isin(etfs)]
    d["side"] = np.where(d["buy_sell"].str.upper().str.startswith("B"), 1, -1)
    d["net"] = d["qty"] * d["side"]
    net = d.groupby(["date", "symbol", "client_name"], as_index=False)["net"].sum()
    net = net[net["net"] > 0]

    rows = []
    for _, r in net.iterrows():
        sym = r["symbol"]
        if sym not in close.columns:
            continue
        pos = dates.searchsorted(r["date"], side="right")
        if pos < 1 or pos + hold >= len(dates):
            continue
        if not bool(liquid.iloc[pos - 1].get(sym, False)):
            continue
        p0, p1 = open_.iloc[pos].get(sym), close.iloc[pos + hold].get(sym)
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            continue
        b = bench_c.iloc[pos + hold] / bench_o.iloc[pos] - 1
        rows.append({"date": r["date"], "symbol": sym, "client": r["client_name"], "excess": 100 * (p1 / p0 - 1 - b)})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def run_variant(deals, min_n=10, min_t=1.0, top_decile=False, lag_days=95):
    """Walk deals chronologically; follow proven clients' new buys."""
    hist = {}  # client → list of completed-outcome excesses
    pending = []  # (available_date, client, excess)
    events, last_evt = [], {}
    for _, r in deals.iterrows():
        d = r["date"]
        while pending and pending[0][0] <= d:  # mature old outcomes
            _, c, x = pending.pop(0)
            hist.setdefault(c, []).append(x)
        c = r["client"]
        past = hist.get(c, [])
        proven = False
        if len(past) >= min_n:
            m, s = np.mean(past), np.std(past, ddof=1)
            t = m / (s / np.sqrt(len(past))) if s > 0 else 0
            proven = m > 0 and t >= min_t
            if top_decile:
                means = [np.mean(v) for v in hist.values() if len(v) >= min_n]
                proven = len(past) >= min_n and len(means) >= 10 and np.mean(past) >= np.quantile(means, 0.9)
        if proven:
            k = r["symbol"]
            if (d - last_evt.get(k, pd.Timestamp("1900-01-01"))).days > 92:
                events.append(r)
                last_evt[k] = d
        pending.append((d + pd.Timedelta(days=lag_days), c, r["excess"]))
        pending.sort(key=lambda x: x[0])
    return pd.DataFrame(events)


def report(name, df, base, lo, hi):
    w = df[(df["date"] >= lo) & (df["date"] < hi)] if len(df) else df
    bw = base[(base["date"] >= lo) & (base["date"] < hi)]
    if len(w) == 0:
        print(f"  {name:>22}: no events")
        return
    e = w["excess"]
    q = w.assign(q=w["date"].dt.to_period("Q")).groupby("q")["excess"].sum()
    pos = q[q > 0].sum()
    print(
        f"  {name:>22}: n={len(e):5d}  mean={e.mean():+6.2f}  "
        f"median={e.median():+6.2f}  net={e.mean() - 0.5:+6.2f}  "
        f"win={100 * (e > 0).mean():4.1f}%  "
        f"vs_all_deals={e.mean() - bw['excess'].mean():+6.2f}  "
        f"maxQtr={round(100 * q.max() / pos) if pos > 0 else '-'}%"
    )


def main():
    deals = deal_outcomes()
    print(f"{len(deals)} net-buy deal outcomes computed ({deals['client'].nunique()} clients)")
    variants = [
        ("baseline n10 t1", {}),
        ("n20", {"min_n": 20}),
        ("t2", {"min_t": 2.0}),
        ("top_decile", {"top_decile": True}),
    ]
    cache = {n: run_variant(deals, **kw) for n, kw in variants}
    for label, lo, hi in (
        ("IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
        ("OUT-OF-SAMPLE 2017-22", "2017-01-01", "2023-01-01"),
    ):
        print(f"=== {label} ===")
        print(
            f"  {'ALL-DEALS null':>22}: mean="
            f"{deals[(deals['date'] >= lo) & (deals['date'] < hi)]['excess'].mean():+6.2f}"
        )
        for n, _ in variants:
            report(n, cache[n], deals, lo, hi)


if __name__ == "__main__":
    main()

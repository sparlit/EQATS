"""v27.1 (index flows on real reconstitution announcements).
Per PROTOCOL_V27.1.md. Variable-exit engine: entry next open after
ANNOUNCE, exit at close of EFFECTIVE (cell E) or fixed holds. Nulls are
same-day pseudo-events that INHERIT the parent event's exit, so every
comparison holds the identical window.

    python -m backtest.inclusion271
"""
import numpy as np
import pandas as pd

import config
from backtest import features
from ingest import etf_list

INDICES = ("nifty 50", "nifty next 50", "nifty 100", "nifty 500",
           "nifty midcap 150")


def run(ev, close, open_, bench_c, bench_o, liquid, use_effective=False,
        hold=None):
    dates = close.index
    rows = []
    for _, e in ev.iterrows():
        sym = e["symbol"]
        if sym not in close.columns:
            continue
        pos = dates.searchsorted(e["an_dt"], side="right")
        if pos < 1 or pos >= len(dates):
            continue
        if use_effective:
            if pd.isna(e["effective"]):
                continue
            xpos = dates.searchsorted(e["effective"], side="right") - 1
            if xpos <= pos or xpos >= len(dates):
                continue
        else:
            xpos = pos + hold
            if xpos >= len(dates):
                continue
        if not bool(liquid.iloc[pos - 1].get(sym, False)):
            continue
        p0, p1 = open_.iloc[pos].get(sym), close.iloc[xpos].get(sym)
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            continue
        b = bench_c.iloc[xpos] / bench_o.iloc[pos] - 1
        rows.append({"date": dates[pos], "symbol": sym,
                     "excess": 100 * (p1 / p0 - 1 - b)})
    return pd.DataFrame(rows)


def make_nulls(ev, close, liquid, mom, k=20):
    """Same-day pseudo-events inheriting the parent's effective date.
    Returns (random_null, momentum_matched_null)."""
    dates = close.index
    rng = np.random.default_rng(7)
    rnd, mm = [], []
    for _, e in ev.iterrows():
        pos = dates.searchsorted(e["an_dt"], side="right")
        if pos < 1 or pos >= len(dates):
            continue
        day = dates[pos - 1]
        liq = liquid.loc[day]
        pool = liq.index[liq.fillna(False)]
        pool = pool[pool != e["symbol"]]
        if len(pool):
            for s in rng.choice(pool, size=min(k, len(pool)),
                                replace=False):
                rnd.append({"an_dt": e["an_dt"],
                            "effective": e["effective"], "symbol": s})
        m = mom.loc[day].dropna()
        m = m[m.index.isin(pool)]
        if e["symbol"] in mom.columns and pd.notna(mom.loc[day].get(
                e["symbol"])) and len(m) > 20:
            dec = pd.qcut(m, 10, labels=False, duplicates="drop")
            target = pd.qcut(
                pd.concat([m, pd.Series({e["symbol"]:
                                         mom.loc[day, e["symbol"]]})]),
                10, labels=False, duplicates="drop")[e["symbol"]]
            cands = dec.index[dec == target]
            if len(cands):
                for s in rng.choice(cands, size=min(k, len(cands)),
                                    replace=False):
                    mm.append({"an_dt": e["an_dt"],
                               "effective": e["effective"], "symbol": s})
    return pd.DataFrame(rnd), pd.DataFrame(mm)


def stat(df):
    return (f"n={len(df):5d} mean={df['excess'].mean():+6.2f} "
            f"med={df['excess'].median():+6.2f}") if len(df) else "n=    0"


def verdict(a, n1, n2, screen=False):
    if not (len(a) >= 30 and len(n1) and len(n2)):
        return "fail (n)"
    if screen:
        ok = (a["excess"].mean() <= n1["excess"].mean() - 3
              and a["excess"].mean() <= n2["excess"].mean() - 3)
        return "CONFIRMED" if ok else "fail"
    ok = (a["excess"].mean() >= n1["excess"].mean() + 3
          and a["excess"].mean() >= n2["excess"].mean() + 3
          and a["excess"].median() > n1["excess"].median()
          and a["excess"].median() > n2["excess"].median())
    return "PASS (confirmatory-only)" if ok else "fail"


def main():
    ev = pd.read_parquet(config.DATA_DIR / "reconstitution"
                         / "events.parquet")
    ev = ev[ev["index"].isin(INDICES)].copy()
    ev["an_dt"] = ev["announce"]
    # pooled: dedupe, attribute to largest index per frozen order
    order = {n: i for i, n in enumerate(INDICES)}
    pooled = (ev.sort_values("index", key=lambda s: s.map(order))
                .drop_duplicates(["announce", "symbol", "action"]))

    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)
    mom = close.shift(21) / close.shift(252) - 1

    cells = (("E ann→eff", dict(use_effective=True)),
             ("F21", dict(hold=21)), ("F63", dict(hold=63)))
    groups = [("POOLED", pooled)] + [(n, ev[ev["index"] == n])
                                     for n in INDICES]
    for gname, g in groups:
        adds = g[g["action"] == "add"]
        drops = g[g["action"] == "drop"]
        if not len(adds):
            continue
        rnd_a, mm_a = make_nulls(adds, close, liquid, mom)
        rnd_d, mm_d = make_nulls(drops, close, liquid, mom)
        print(f"\n#### {gname}: adds={len(adds)} drops={len(drops)}")
        for label, lo, hi in (("IS 2023-26 (DECISION)", "2023-01-01",
                               "2027-01-01"),
                              ("OOS 2016-22 (single shot)", "2016-01-01",
                               "2023-01-01")):
            print(f"=== {label} ===")
            def W(d):
                return d[(d["an_dt"] >= lo) & (d["an_dt"] < hi)] \
                    if len(d) else d
            for cname, kw in cells:
                a = run(W(adds), *args, **kw)
                n1 = run(W(rnd_a), *args, **kw)
                n2 = run(W(mm_a), *args, **kw)
                print(f"  ADD {cname:<10}: {stat(a)}")
                print(f"      random-null : {stat(n1)}")
                print(f"      mom-null    : {stat(n2)}")
                print(f"      verdict: {verdict(a, n1, n2)}")
            d = run(W(drops), *args, use_effective=True)
            n1d = run(W(rnd_d), *args, use_effective=True)
            n2d = run(W(mm_d), *args, use_effective=True)
            print(f"  DROP E       : {stat(d)}  "
                  f"[nulls {stat(n1d)} | {stat(n2d)}]")
            print(f"      verdict: {verdict(d, n1d, n2d, screen=True)}")


if __name__ == "__main__":
    main()

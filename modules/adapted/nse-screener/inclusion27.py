"""v27 (index-inclusion flows on synthetic constituents).
Per PROTOCOL_V27.md — deep boundary crossings, two nulls including the
momentum-matched one. Events require OBSERVED ranks on both sides of
the crossing (a jump from unranked is an IPO/data artifact, not a flow).

    python -m backtest.inclusion27
"""
import pandas as pd

import config
from backtest import features
from backtest.events17 import run_kind
from ingest import etf_list

BOUNDS = (("50", 60, 40, "ffmcap"), ("100", 120, 80, "ffmcap"),
          ("500", 550, 450, "mcap"))
HOLD = {"50": (63, 21, 126), "100": (63, 21, 126), "500": (63,)}


def rank_matrix(kind):
    d = pd.read_parquet(config.DATA_DIR / "constituents_synth.parquet")
    d = d[d["kind"] == kind]
    return d.pivot_table(index="date", columns="symbol", values="rank")


def crossings(rk, hi, lo):
    """adds: observed >hi at t-1 → <=lo at t; drops: mirror."""
    prev = rk.shift(1)
    adds, drops = [], []
    for t in rk.index[1:]:
        p, c = prev.loc[t], rk.loc[t]
        obs = p.notna() & c.notna()
        for s in rk.columns[obs & (p > hi) & (c <= lo)]:
            adds.append({"an_dt": t, "symbol": s})
        for s in rk.columns[obs & (p <= lo) & (c > hi)]:
            drops.append({"an_dt": t, "symbol": s})
    return pd.DataFrame(adds), pd.DataFrame(drops)


def near_null(rk, n):
    """non-crossers sitting in [0.8N, 1.2N] two consecutive months"""
    prev = rk.shift(1)
    rows = []
    for t in rk.index[1:]:
        p, c = prev.loc[t], rk.loc[t]
        band = (c >= 0.8 * n) & (c <= 1.2 * n) & (p >= 0.8 * n) \
            & (p <= 1.2 * n)
        for s in rk.columns[band.fillna(False)]:
            rows.append({"an_dt": t, "symbol": s})
    return pd.DataFrame(rows)


def mom_null(rk, events, mom, n):
    """same month, same 12-1 momentum decile, rank in [0.5N, 2N],
    not itself a crosser that month"""
    ev_by_month = events.groupby("an_dt")["symbol"].apply(set)
    rows = []
    for t, ev_syms in ev_by_month.items():
        if t not in mom.index:
            continue
        m = mom.loc[t].dropna()
        try:
            dec = pd.qcut(m, 10, labels=False, duplicates="drop")
        except ValueError:
            continue
        c = rk.loc[t]
        band = set(c[(c >= 0.5 * n) & (c <= 2 * n)].index)
        for s in ev_syms:
            if s not in dec.index:
                continue
            for cand in dec.index[(dec == dec[s])]:
                if cand in band and cand not in ev_syms:
                    rows.append({"an_dt": t, "symbol": cand})
    return pd.DataFrame(rows).drop_duplicates()


def stat(df):
    return (f"n={len(df):4d}  mean={df['excess'].mean():+6.2f}  "
            f"median={df['excess'].median():+6.2f}") if len(df) else "n=   0"


def main():
    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)
    mom = (close.shift(21) / close.shift(252) - 1)

    for name, hi, lo, kind in BOUNDS:
        rk = rank_matrix(kind)
        n = int(name)
        adds, drops = crossings(rk, hi, lo)
        near = near_null(rk, n)
        momn_a = mom_null(rk, adds, mom, n) if len(adds) else pd.DataFrame()
        print(f"\n#### boundary {name} ({kind}): adds={len(adds)} "
              f"drops={len(drops)} near-null={len(near)} "
              f"mom-null={len(momn_a)}")
        for label, lo_w, hi_w in (("IS 2023-26 (DECISION)",
                                   "2023-01-01", "2027-01-01"),
                                  ("OOS 2018-22 (single shot)",
                                   "2018-01-01", "2023-01-01")):
            print(f"=== {label} ===")
            def W(d):
                return d[(d["an_dt"] >= lo_w) & (d["an_dt"] < hi_w)] \
                    if len(d) else d
            for hold in HOLD[name]:
                a = run_kind(W(adds), *args, hold=hold, gap_days=126)
                n1 = run_kind(W(near), *args, hold=hold, gap_days=0)
                n2 = run_kind(W(momn_a), *args, hold=hold, gap_days=0)
                print(f"  A{name} h{hold:<3}: {stat(a)}")
                print(f"    near-null   : {stat(n1)}")
                print(f"    mom-null    : {stat(n2)}")
                if len(a) and len(n1) and len(n2):
                    ok = (a["excess"].mean() >= n1["excess"].mean() + 3
                          and a["excess"].mean() >= n2["excess"].mean() + 3
                          and a["excess"].median() > n1["excess"].median()
                          and a["excess"].median() > n2["excess"].median()
                          and len(a) >= 30)
                    print(f"    verdict h{hold}: "
                          f"{'PASS (confirmatory-only)' if ok else 'fail'}")
            d63 = run_kind(W(drops), *args, hold=63, gap_days=126)
            n1d = run_kind(W(near), *args, hold=63, gap_days=0)
            print(f"  D{name} h63 : {stat(d63)}   "
                  f"(near-null mean {n1d['excess'].mean():+.2f})"
                  if len(n1d) else f"  D{name} h63 : {stat(d63)}")


if __name__ == "__main__":
    main()

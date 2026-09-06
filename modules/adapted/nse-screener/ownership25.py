"""v25 (promoter ownership-trend from quarterly shareholding patterns).
Per PROTOCOL_V25.md — v21 family, two-null design, IS-only decision.

    python -m backtest.ownership25
"""
from pathlib import Path

import pandas as pd

import config
from backtest import features
from backtest.events17 import run_kind, report as _rep
from backtest.pit_study import load_ann
from ingest import etf_list, renames


def load_shareholding() -> pd.DataFrame:
    df = pd.concat(map(pd.read_parquet,
                       Path(config.DATA_DIR / "shareholding")
                       .glob("*.parquet")), ignore_index=True)
    df["symbol"] = renames.canonical(df["symbol"].astype(str).str.strip())
    df["qdate"] = pd.to_datetime(df["date"], format="%d-%b-%Y",
                                 errors="coerce")
    df["an_dt"] = pd.to_datetime(df["broadcastDate"],
                                 format="%d-%b-%Y %H:%M:%S", errors="coerce")
    df["prom"] = pd.to_numeric(df["pr_and_prgrp"], errors="coerce")
    df = df.dropna(subset=["an_dt", "qdate", "prom", "symbol"])
    df = df[df["qdate"].dt.is_quarter_end]          # PIT era, real quarters
    df = (df.sort_values("an_dt")
            .drop_duplicates(["symbol", "qdate"], keep="last")  # revisions
            .sort_values(["symbol", "qdate"]))
    g = df.groupby("symbol")
    df["dprom"] = g["prom"].diff()
    df["dprom_prev"] = g["dprom"].shift(1)
    df["qgap"] = g["qdate"].diff().dt.days          # consecutive-quarter guard
    df["qgap_prev"] = g["qgap"].shift(1)
    return df.dropna(subset=["dprom"])


def main():
    sh = load_shareholding()
    e1 = sh[(sh["dprom"] >= 0.5) & (sh["prom"] > 0)]
    e2 = sh[(sh["dprom"] >= 2.0) & (sh["prom"] > 0)]
    e3 = sh[(sh["dprom"] <= -0.5) & (sh["prom"] > 0)]
    e4 = sh[(sh["dprom"] > 0) & (sh["dprom_prev"] > 0)
            & (sh["qgap"] <= 100) & (sh["qgap_prev"] <= 100)]
    print(f"events: E1={len(e1)} E2={len(e2)} E3={len(e3)} E4={len(e4)} "
          f"(all-filings null pool: {len(sh)})")

    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)

    baseline_pool = load_ann().sample(n=60000, random_state=7)

    for label, lo, hi in (
            ("IS 2023-26 (DECISION)", "2023-01-01", "2027-01-01"),
            ("OOS 2018-22 (family-spent, consistency only)",
             "2018-01-01", "2023-01-01")):
        print(f"=== {label} ===")
        def W(d):
            return d[(d["an_dt"] >= lo) & (d["an_dt"] < hi)]
        nullb = run_kind(W(baseline_pool), *args, gap_days=0)
        nm = nullb["excess"].mean() if len(nullb) else 0.0
        print(f"  {'random-announcement null':>28}: n={len(nullb):5d}  "
              f"mean={nm:+6.2f}  median={nullb['excess'].median():+6.2f}")
        nulls = run_kind(W(sh), *args, gap_days=0)
        print(f"  {'all-filings null':>28}: n={len(nulls):5d}  "
              f"mean={nulls['excess'].mean():+6.2f}  "
              f"median={nulls['excess'].median():+6.2f}")
        for name, ev in (("E1 incr>=0.5pp", e1), ("E2 incr>=2pp", e2),
                         ("E3 decr<=-0.5pp", e3), ("E4 two-up-quarters", e4)):
            _rep(f"{name} h63", run_kind(W(ev), *args, gap_days=63), nm)
        for name, ev in (("E1", e1), ("E3", e3)):
            _rep(f"{name} h21", run_kind(W(ev), *args, hold=21,
                                         gap_days=63), nm)
            _rep(f"{name} h126", run_kind(W(ev), *args, hold=126,
                                          gap_days=63), nm)


if __name__ == "__main__":
    main()

"""v28 (institutional accumulation from FII/DII quarterly detail).
Per PROTOCOL_V28.md — exact era-canonical labels (never substring,
never subtotals), horizon ladder h21/63/126 with per-hold nulls.

    python -m backtest.ownership28
"""
from pathlib import Path

import pandas as pd

import config
from backtest import features
from backtest.events17 import run_kind
from backtest.pit_study import load_ann
from ingest import etf_list, renames

MF = {"mutual funds/", "mutual funds"}
FPI = {"foreign portfolio investors",
       "foreign portfolio investors category i",
       "foreign portfolio investors category ii",
       "foreign portfolio investor (category - iii)",
       "foreign portfolio investors (category iii)"}


def load_detail() -> pd.DataFrame:
    df = pd.concat(map(pd.read_parquet,
                       Path(config.DATA_DIR / "shareholding_detail")
                       .glob("*.parquet")), ignore_index=True)
    df["qdate"] = pd.to_datetime(df["date"], format="%d-%b-%Y",
                                 errors="coerce")
    df = df[df["qdate"].dt.is_quarter_end]
    df["cat"] = (df["category"].astype(str).str.strip()
                 .str.replace(r"\s+", " ", regex=True).str.lower())
    df["pct_n"] = pd.to_numeric(df["pct"], errors="coerce")
    df["an_dt"] = pd.to_datetime(df["broadcastDate"],
                                 format="%d-%b-%Y %H:%M:%S", errors="coerce")
    df = df.dropna(subset=["an_dt", "pct_n"])
    df["symbol"] = renames.canonical(df["symbol"].astype(str))
    # latest recordId per (symbol, quarter) — revisions supersede
    latest = (df.sort_values("recordId")
                .drop_duplicates(["symbol", "qdate"], keep="last")
                [["symbol", "qdate", "recordId", "an_dt"]])
    df = df.merge(latest, on=["symbol", "qdate", "recordId", "an_dt"])
    mf = (df[df["cat"].isin(MF)]
          .groupby(["symbol", "qdate", "an_dt"])["pct_n"].last()
          .rename("mf"))
    fpi = (df[df["cat"].isin(FPI)]
           .groupby(["symbol", "qdate", "an_dt"])["pct_n"].sum()
           .rename("fpi"))
    out = pd.concat([mf, fpi], axis=1).reset_index()
    out = out.sort_values(["symbol", "qdate"])
    g = out.groupby("symbol")
    out["dmf"] = g["mf"].diff()
    out["dfpi"] = g["fpi"].diff()
    return out.dropna(subset=["dmf", "dfpi"], how="all")


def stat(df):
    return (f"n={len(df):5d} mean={df['excess'].mean():+6.2f} "
            f"med={df['excess'].median():+6.2f}") if len(df) else "n=    0"


def main():
    d = load_detail()
    ev = {
        "E1 MF+0.5": d[d["dmf"] >= 0.5],
        "E2 FPI+0.5": d[d["dfpi"] >= 0.5],
        "E3 both+0.25": d[(d["dmf"] >= 0.25) & (d["dfpi"] >= 0.25)],
        "E4 MF-0.5": d[d["dmf"] <= -0.5],
        "E5 FPI-0.5": d[d["dfpi"] <= -0.5],
    }
    print("events:", {k: len(v) for k, v in ev.items()},
          f"| all-filings pool: {len(d)}")

    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)
    baseline = load_ann().sample(n=60000, random_state=7)

    for label, lo, hi in (("IS 2023-26 (DECISION)", "2023-01-01",
                           "2027-01-01"),
                          ("OOS 2017-22 (single shot)", "2017-01-01",
                           "2023-01-01")):
        print(f"\n=== {label} ===")
        def W(x):
            return x[(x["an_dt"] >= lo) & (x["an_dt"] < hi)]
        for hold in (21, 63, 126):
            n1 = run_kind(W(baseline), *args, hold=hold, gap_days=0)
            n2 = run_kind(W(d), *args, hold=hold, gap_days=0)
            print(f" h{hold}: random-null {stat(n1)} | "
                  f"all-filings-null {stat(n2)}")
            for name, e in ev.items():
                r = run_kind(W(e), *args, hold=hold, gap_days=63)
                screen = name.startswith(("E4", "E5"))
                if len(r) >= 100 and len(n1):
                    if screen:
                        v = ("CONFIRMED" if r["excess"].mean()
                             <= n1["excess"].mean() - 3 else "fail")
                    else:
                        v = ("PASS" if (r["excess"].mean()
                             >= n1["excess"].mean() + 3
                             and r["excess"].median()
                             > n1["excess"].median()) else "fail")
                else:
                    v = "fail (n)"
                print(f"   {name:<13} {stat(r)}  [{v}]")


if __name__ == "__main__":
    main()

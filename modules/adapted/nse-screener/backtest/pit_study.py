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


"""v21 (India insider market purchases) + v22 (announcement risk screens).
Per PROTOCOL_V21.md. Reuses the events17 engine.

    python -m backtest.pit_study
"""
from pathlib import Path

import pandas as pd
from backtest import features
from backtest.events17 import report as _rep
from backtest.events17 import run_kind
from ingest import etf_list, renames

import config


def load_pit():
    df = pd.concat(map(pd.read_parquet, Path(config.DATA_DIR / "pit").glob("*.parquet")), ignore_index=True)
    df["symbol"] = renames.canonical(df["symbol"].astype(str).str.strip())
    df["an_dt"] = pd.to_datetime(df["date"], format="%d-%b-%Y %H:%M", errors="coerce")
    df["val"] = pd.to_numeric(df["secVal"], errors="coerce")
    return df.dropna(subset=["an_dt", "symbol"])


def load_ann():
    df = pd.concat(map(pd.read_parquet, Path(config.DATA_DIR / "ann_full").glob("*.parquet")), ignore_index=True)
    df["symbol"] = renames.canonical(df["symbol"])
    df["an_dt"] = pd.to_datetime(df["an_dt"], errors="coerce")
    return df.dropna(subset=["an_dt", "symbol"])


def main():
    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)

    pit = load_pit()
    ins = pit["personCategory"].str.contains("Promoter|Director", na=False)
    buy = pit["acqMode"] == "Market Purchase"
    base_v21 = pit[ins & buy & (pit["val"] >= 2.5e6)]
    # cluster: >=2 distinct insiders in 21 days per symbol
    b = base_v21.sort_values("an_dt")
    b["day"] = b["an_dt"].dt.normalize()
    cl = []
    for _sym, g in b.groupby("symbol"):
        for i in range(len(g)):
            w = g[(g["day"] > g["day"].iloc[i] - pd.Timedelta(days=21)) & (g["day"] <= g["day"].iloc[i])]
            if w["acqName"].nunique() >= 2:
                cl.append(g.iloc[i])
    cluster = pd.DataFrame(cl)

    ann = load_ann()
    lowdesc = ann["desc"].str.lower()
    lowsnip = ann["snippet"].astype(str).str.lower()
    downgrade = ann[
        lowsnip.str.contains("downgrad", na=False)
        | (lowdesc.str.contains("credit rating", na=False) & lowsnip.str.contains("downgrad|negative", na=False))
    ]
    aud_resign = ann[
        lowsnip.str.contains(
            r"resignation of.{0,40}auditor|auditor.{0,40}resign"
            r"|resignation of.{0,40}chief financial",
            na=False,
            regex=True,
        )
    ]
    baseline_pool = ann.sample(n=60000, random_state=7)

    for label, lo, hi in (
        ("IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
        ("OUT-OF-SAMPLE 2018-22", "2018-01-01", "2023-01-01"),
    ):
        print(f"=== {label} ===")

        def W(d):
            return d[(d["an_dt"] >= lo) & (d["an_dt"] < hi)]

        nullb = run_kind(W(baseline_pool), *args, gap_days=0)
        nm = nullb["excess"].mean() if len(nullb) else 0.0
        print(
            f"  {'random-announcement null':>28}: n={len(nullb):5d}  "
            f"mean={nm:+6.2f}  median={nullb['excess'].median():+6.2f}"
        )
        allpit = run_kind(W(pit), *args, gap_days=0)
        print(
            f"  {'all-PIT null':>28}: n={len(allpit):5d}  "
            f"mean={allpit['excess'].mean():+6.2f}  "
            f"median={allpit['excess'].median():+6.2f}"
        )
        _rep("v21 baseline 63d", run_kind(W(base_v21), *args, gap_days=63), nm)
        _rep("v21 cluster>=2", run_kind(W(cluster), *args, gap_days=63), nm)
        _rep("v21 value>=1cr", run_kind(W(base_v21[base_v21["val"] >= 1e7]), *args, gap_days=63), nm)
        _rep("v21 hold_21", run_kind(W(base_v21), *args, hold=21, gap_days=63), nm)
        _rep("v21 hold_126", run_kind(W(base_v21), *args, hold=126, gap_days=63), nm)
        _rep(
            "v21 promoters_only",
            run_kind(W(base_v21[base_v21["personCategory"].str.contains("Promoter")]), *args, gap_days=63),
            nm,
        )
        _rep("v22 rating-downgrade", run_kind(W(downgrade), *args, gap_days=63), nm)
        _rep("v22 auditor/CFO-resign", run_kind(W(aud_resign), *args, gap_days=63), nm)


if __name__ == "__main__":
    main()

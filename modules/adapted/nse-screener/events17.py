"""v17: corporate-event studies (PROTOCOL_V17.md).

    python -m backtest.events17

Note: the 'order wins >= crore' grid cell is untestable (attachment text
not retained in the slim store) — disclosed, skipped.
"""
from pathlib import Path

import pandas as pd

import config
from backtest import features
from ingest import etf_list, renames


def load_events() -> pd.DataFrame:
    files = sorted((config.DATA_DIR / "announcements").glob("*.parquet"))
    df = pd.concat(map(pd.read_parquet, files), ignore_index=True)
    df["an_dt"] = pd.to_datetime(df["an_dt"], errors="coerce")
    df = df.dropna(subset=["an_dt", "symbol"])
    df["symbol"] = renames.canonical(df["symbol"].astype(str).str.strip())
    return df


def run_kind(ev, close, open_, bench_c, bench_o, liquid, hold=63,
             gap_days=126):
    dates = close.index
    ev = ev.sort_values("an_dt")
    rows, last = [], {}
    for _, e in ev.iterrows():
        sym = e["symbol"]
        if sym not in close.columns:
            continue
        pos = dates.searchsorted(e["an_dt"], side="right")
        if pos < 1 or pos + hold >= len(dates):
            continue
        if (dates[pos] - last.get(sym, pd.Timestamp("1900-01-01"))).days \
                <= gap_days:
            continue
        if not bool(liquid.iloc[pos - 1].get(sym, False)):
            continue
        p0, p1 = open_.iloc[pos].get(sym), close.iloc[pos + hold].get(sym)
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            continue
        last[sym] = dates[pos]
        b = bench_c.iloc[pos + hold] / bench_o.iloc[pos] - 1
        rows.append({"date": dates[pos], "symbol": sym,
                     "excess": 100 * (p1 / p0 - 1 - b)})
    return pd.DataFrame(rows)


def report(name, df, null_mean):
    if df.empty:
        print(f"  {name:>28}: no events")
        return
    e = df["excess"]
    q = df.assign(q=df["date"].dt.to_period("Q")).groupby("q")["excess"].sum()
    pos = q[q > 0].sum()
    print(f"  {name:>28}: n={len(e):5d}  mean={e.mean():+6.2f}  "
          f"median={e.median():+6.2f}  net={e.mean()-0.5:+6.2f}  "
          f"win={100*(e>0).mean():4.1f}%  vs_baseline={e.mean()-null_mean:+6.2f}  "
          f"maxQtr={round(100*q.max()/pos) if pos>0 else '-'}%")


def main():
    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    bench_c, bench_o = close["NIFTYBEES"], open_["NIFTYBEES"]
    ev = load_events()

    args = (close, open_, bench_c, bench_o, liquid)
    for label, lo, hi in (("IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
                          ("OUT-OF-SAMPLE 2017-22", "2017-01-01", "2023-01-01")):
        print(f"=== {label} ===")
        w = ev[(ev["an_dt"] >= lo) & (ev["an_dt"] < hi)]
        base = run_kind(w[w["kind"] == "baseline"], *args, gap_days=0)
        nm = base["excess"].mean() if len(base) else 0.0
        print(f"  {'ALL-ANNOUNCEMENTS null':>28}: n={len(base):5d}  "
              f"mean={nm:+6.2f}  median={base['excess'].median():+6.2f}")
        for kind in ("buyback", "order_win"):
            report(f"{kind} 63d",
                   run_kind(w[w["kind"] == kind], *args), nm)
            report(f"{kind} hold_21",
                   run_kind(w[w["kind"] == kind], *args, hold=21), nm)
            report(f"{kind} hold_126",
                   run_kind(w[w["kind"] == kind], *args, hold=126), nm)
        strict = w[(w["kind"] == "buyback")
                   & w["desc"].str.lower().str.contains("buyback", na=False)]
        report("buyback strict-category", run_kind(strict, *args), nm)


if __name__ == "__main__":
    main()

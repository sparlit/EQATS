"""v15: PEAD India event study (PROTOCOL_V15.md).

    python -m backtest.pead
"""
import numpy as np
import pandas as pd

import config
from backtest import features
from ingest import etf_list

PARSED = config.DATA_DIR / "fr_xbrl" / "parsed.parquet"


def sue_events(trailing: int = 8) -> pd.DataFrame:
    fr = pd.read_parquet(PARSED).dropna(subset=["net_profit"])
    from ingest import renames
    fr["symbol"] = renames.canonical(fr["symbol"])
    fr = (fr.sort_values("broadcast")
            .drop_duplicates(subset=["symbol", "q_end"], keep="first")
            .sort_values(["symbol", "q_end"]))
    g = fr.groupby("symbol")
    fr["yoy"] = fr["net_profit"] - g["net_profit"].shift(4)
    fr["sue"] = fr.groupby("symbol")["yoy"].transform(
        lambda s: s / s.rolling(trailing, min_periods=6).std())
    fr = fr.dropna(subset=["sue"])
    fr["bdate"] = pd.to_datetime(fr["broadcast"])
    return fr[["symbol", "q_end", "bdate", "sue"]]


def run_events(ev, close, open_, bench_c, bench_o, liquid, hold=63,
               trend=None, rt_cost=0.005):
    dates = close.index
    rows, last = [], {}
    ev = ev.sort_values("bdate")
    for _, e in ev.iterrows():
        sym = e["symbol"]
        if sym not in close.columns:
            continue
        pos = dates.searchsorted(e["bdate"], side="right")  # first session
        if pos + hold >= len(dates) or pos < 1:             # after broadcast
            continue
        if pos - last.get(sym, -10**9) <= hold:
            continue
        t_prev = dates[pos - 1]
        if not bool(liquid.loc[t_prev].get(sym, False)):
            continue
        if trend is not None and not bool(trend.loc[t_prev].get(sym, False)):
            continue
        p0 = open_.iloc[pos].get(sym)
        p1 = close.iloc[pos + hold].get(sym)
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            continue
        last[sym] = pos
        raw = p1 / p0 - 1
        b = bench_c.iloc[pos + hold] / bench_o.iloc[pos] - 1
        rows.append({"date": dates[pos], "symbol": sym, "sue": e["sue"],
                     "excess": 100 * (raw - b)})
    return pd.DataFrame(rows)


def report(name, df, rt_cost=0.5):
    if df.empty:
        print(f"  {name}: no events")
        return
    e = df["excess"]
    q = df.assign(q=df["date"].dt.to_period("Q")).groupby("q")["excess"].sum()
    pos = q[q > 0].sum()
    print(f"  {name:>24}: n={len(e):5d}  mean={e.mean():+6.2f}  "
          f"median={e.median():+6.2f}  win={100*(e>0).mean():4.1f}%  "
          f"net_mean={e.mean()-rt_cost:+6.2f}  "
          f"maxQtr={round(100*q.max()/pos) if pos>0 else '-'}%")


def main():
    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    ma200 = close.rolling(200).mean()
    trend = close > ma200
    bench_c, bench_o = close["NIFTYBEES"], open_["NIFTYBEES"]
    ev = sue_events()
    dec = ev.copy()
    dec["qtr"] = dec["q_end"].dt.to_period("Q")
    dec["decile"] = dec.groupby("qtr")["sue"].transform(
        lambda s: s.rank(pct=True))

    for label, lo, hi in (("IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
                          ("OUT-OF-SAMPLE 2020-22", "2020-01-01", "2023-01-01")):
        print(f"=== {label} ===")
        w = ev[(ev["bdate"] >= lo) & (ev["bdate"] < hi)]
        wd = dec[(dec["bdate"] >= lo) & (dec["bdate"] < hi)]
        report("baseline SUE>=1, 63d",
               run_events(w[w["sue"] >= 1], close, open_, bench_c, bench_o, liquid))
        report("SUE>=2",
               run_events(w[w["sue"] >= 2], close, open_, bench_c, bench_o, liquid))
        report("top-decile SUE",
               run_events(wd[wd["decile"] >= 0.9], close, open_, bench_c, bench_o, liquid))
        report("hold_5", run_events(w[w["sue"] >= 1], close, open_, bench_c,
                                    bench_o, liquid, hold=5))
        report("hold_21", run_events(w[w["sue"] >= 1], close, open_, bench_c,
                                     bench_o, liquid, hold=21))
        report("with_trend", run_events(w[w["sue"] >= 1], close, open_,
                                        bench_c, bench_o, liquid, trend=trend))
        report("NEGATIVE side (info)",
               run_events(w[w["sue"] <= -1], close, open_, bench_c, bench_o, liquid))


if __name__ == "__main__":
    main()

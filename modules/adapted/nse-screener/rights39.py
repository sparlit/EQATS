"""v39 (rights-entitlement discount capture). Per PROTOCOL_V39.md.

DISCLOSED DEVIATION (data-forced, not a criteria change): the protocol
says exit "at the first tradable close after allotment". Allotment and
new-share-listing dates are not in any feed we hold, so the exit is
modelled with FROZEN proxies of 15 / 21 / 30 trading days after the RE
purchase (the typical RE-close → credit → tradable lag). All three are
reported; none is cherry-picked.

    python -m backtest.rights39
"""
import re

import numpy as np
import pandas as pd

import config
from backtest import features
from ingest import renames

RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)")
PREM = re.compile(r"premium\s*(?:of\s*)?rs\.?\s*(\d+(?:\.\d+)?)", re.I)
THRESH = (0.05, 0.10)
EXITS = (15, 21, 30)
COST, STCG, SLAB = 0.0025, 0.20, 0.30


def issue_params():
    ri = pd.read_parquet(config.DATA_DIR / "rights_re" / "issues.parquet")
    rows = []
    for _, r in ri.iterrows():
        s = str(r["subject"])
        m1, m2 = RATIO.search(s), PREM.search(s)
        fv = pd.to_numeric(r.get("faceVal"), errors="coerce")
        if not (m1 and m2) or pd.isna(fv):
            continue                              # 6% unparseable, dropped
        rows.append({"symbol": renames.canonical(pd.Series([str(r["symbol"])]))[0],
                     "record_date": r["record_date"],
                     "issue_px": float(fv) + float(m2.group(1))})
    return pd.DataFrame(rows).drop_duplicates(["symbol", "record_date"])


def main():
    re_tr = pd.read_parquet(config.DATA_DIR / "rights_re" / "re_trades.parquet")
    re_tr["symbol"] = renames.canonical(re_tr["symbol"].astype(str))
    re_tr = re_tr[(re_tr["close"] > 0) & (re_tr["qty"] > 0)]
    ip = issue_params()
    p = features._panel(None, None)
    close = p["close"]
    bees = close["NIFTYBEES"]
    dates = close.index

    rows = []
    for _, e in ip.iterrows():
        sym = e["symbol"]
        if sym not in close.columns:
            continue
        w = re_tr[(re_tr["symbol"] == sym)
                  & (re_tr["date"] >= e["record_date"] - pd.Timedelta(days=5))
                  & (re_tr["date"] <= e["record_date"] + pd.Timedelta(days=45))]
        for _, t in w.iterrows():
            if t["date"] not in dates:
                continue
            und = close.loc[t["date"], sym]
            if pd.isna(und):
                continue
            theo = und - e["issue_px"]
            if theo <= 0:
                continue                          # RE worthless, skip
            rows.append({"symbol": sym, "date": t["date"],
                         "re_close": t["close"], "und": und,
                         "theo": theo, "issue_px": e["issue_px"],
                         "disc": (theo - t["close"]) / theo})
    df = pd.DataFrame(rows)
    if df.empty:
        print("no usable RE observations yet (harvest incomplete?)")
        return
    print(f"RE observations: {len(df)} across {df['symbol'].nunique()} issues "
          f"{df['date'].min().date()} → {df['date'].max().date()}")

    print("\n=== D1 descriptive: discount to theoretical value ===")
    for label, lo, hi in (("ALL", None, None), ("IS 2023-26", "2023-01-01", None),
                          ("OOS 2020-22", "2020-01-01", "2022-12-31")):
        w = df if lo is None else df[(df["date"] >= lo)
                                    & (df["date"] <= (hi or "2099-01-01"))]
        if w.empty:
            continue
        print(f"  {label:<12} n={len(w):5d}  median disc {100*w['disc'].median():+6.1f}%"
              f"  p25 {100*w['disc'].quantile(.25):+6.1f}%"
              f"  p75 {100*w['disc'].quantile(.75):+6.1f}%"
              f"  share >5% disc: {100*(w['disc']>0.05).mean():4.0f}%")

    print("\n=== T1 subscribe-route (buy RE, subscribe, sell shares) ===")
    for thr in THRESH:
        cand = df[df["disc"] >= thr].sort_values("date")
        cand = cand.drop_duplicates(["symbol", "date"])
        for ex in EXITS:
            nets, exs = [], []
            for _, c in cand.iterrows():
                i = dates.searchsorted(c["date"], side="right") - 1
                j = i + ex
                if j >= len(dates):
                    continue
                sell = close.iloc[j].get(c["symbol"])
                if pd.isna(sell):
                    continue
                cost_basis = c["re_close"] + c["issue_px"]
                gross = (sell - cost_basis) / cost_basis
                net = gross - 2 * COST
                net -= STCG * max(net, 0.0)
                b = bees.iloc[j] / bees.iloc[i] - 1
                nets.append(net)
                exs.append(net - b)
            if not nets:
                continue
            n = len(nets)
            print(f"  disc>={100*thr:2.0f}% exit {ex:2d}d: n={n:4d}  "
                  f"net {100*np.mean(nets):+6.2f}%  excess vs index "
                  f"{100*np.mean(exs):+6.2f}pp  "
                  f"[{'PASS' if (n >= 30 and np.mean(nets) > 0 and 100*np.mean(exs) >= 3) else 'fail'}]")

    print("\n=== T2 diagnostic: bare RE flip (slab-taxed) ===")
    flips = []
    for sym, g in df.sort_values("date").groupby("symbol"):
        g = g.reset_index(drop=True)
        for i in range(len(g) - 1):
            if g.loc[i, "disc"] < 0.05:
                continue
            gross = (g.loc[i + 1, "re_close"] - g.loc[i, "re_close"]) \
                / g.loc[i, "re_close"]
            net = gross - 2 * COST
            flips.append(net - SLAB * max(net, 0.0))
    if flips:
        print(f"  n={len(flips)}  mean net {100*np.mean(flips):+6.2f}%  "
              f"median {100*np.median(flips):+6.2f}%")


if __name__ == "__main__":
    main()

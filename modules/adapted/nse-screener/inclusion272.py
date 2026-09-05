"""v27.2 Stage A: robustness gauntlet for the N500 announce→effective
add cell. Per PROTOCOL_V27.2.md — 8 frozen perturbations (fragility
diagnostics, never promotable), lottery check, tax transform.

    python -m backtest.inclusion272
"""
import pandas as pd

import config
from backtest import features
from backtest.inclusion271 import make_nulls
from ingest import etf_list

IS_LO, IS_HI = "2023-01-01", "2027-01-01"


def run2(ev, close, open_, bench_c, bench_o, liquid,
         entry_shift=0, entry_close=False, exit_shift=0):
    dates = close.index
    rows = []
    for _, e in ev.iterrows():
        sym = e["symbol"]
        if sym not in close.columns or pd.isna(e["effective"]):
            continue
        pos = dates.searchsorted(e["an_dt"], side="right") + entry_shift
        xpos = dates.searchsorted(e["effective"], side="right") - 1 \
            + exit_shift
        if pos < 1 or xpos <= pos or xpos >= len(dates):
            continue
        if not bool(liquid.iloc[pos - 1].get(sym, False)):
            continue
        px_in = (close if entry_close else open_).iloc[pos].get(sym)
        px_out = close.iloc[xpos].get(sym)
        if pd.isna(px_in) or pd.isna(px_out) or px_in <= 0:
            continue
        r = px_out / px_in - 1
        b = bench_c.iloc[xpos] / (close if entry_close
                                  else open_)["NIFTYBEES"].iloc[pos] - 1
        r_at = r - 0.20 * max(r, 0.0)            # STCG transform (A3)
        rows.append({"date": dates[pos], "symbol": sym,
                     "excess": 100 * (r - b),
                     "excess_at": 100 * (r_at - b)})
    return pd.DataFrame(rows)


def main():
    ev = pd.read_parquet(config.DATA_DIR / "reconstitution"
                         / "events.parquet")
    adds = ev[(ev["index"] == "nifty 500") & (ev["action"] == "add")].copy()
    adds["an_dt"] = adds["announce"]

    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    med = p["turnover_lacs"].rolling(20).median()
    liq = {250: med >= 250, 500: med >= 500, 1000: med >= 1000}
    mom = close.shift(21) / close.shift(252) - 1
    rnd, mm = make_nulls(adds, close, liq[500], mom)

    def cell(events, lo=IS_LO, hi=IS_HI, lq=500, **kw):
        w = events[(events["an_dt"] >= lo) & (events["an_dt"] < hi)]
        return run2(w, close, open_, close["NIFTYBEES"],
                    open_["NIFTYBEES"], liq[lq], **kw)

    perts = [
        ("declared", {}),
        ("entry announce+2 open", dict(entry_shift=1)),
        ("entry announce+1 close", dict(entry_close=True)),
        ("exit effective-2", dict(exit_shift=-2)),
        ("exit effective+5", dict(exit_shift=5)),
        ("liquidity 2.5cr", dict(lq=250)),
        ("liquidity 10cr", dict(lq=1000)),
        ("half1 2023-24", dict(lo="2023-01-01", hi="2025-01-01")),
        ("half2 2025-26", dict(lo="2025-01-01", hi="2027-01-01")),
    ]
    stable = 0
    declared = None
    print("Stage A1 — plateau (cell mean must stay above BOTH null means):")
    for name, kw in perts:
        a = cell(adds, **kw)
        n1 = cell(rnd, **kw)
        n2 = cell(mm, **kw)
        ok = (len(a) and a["excess"].mean() > n1["excess"].mean()
              and a["excess"].mean() > n2["excess"].mean())
        if name == "declared":
            declared = (a, n1, n2)
        else:
            stable += bool(ok)
        print(f"  {name:<24} n={len(a):3d} cell={a['excess'].mean():+6.2f} "
              f"nulls={n1['excess'].mean():+6.2f}/{n2['excess'].mean():+6.2f}"
              f"  [{'ok' if ok else 'FAIL'}]")
    a1 = stable >= 6
    print(f"A1: {stable}/8 stable → {'PASS' if a1 else 'FAIL'}")

    a, n1, n2 = declared
    q = a.assign(q=a["date"].dt.to_period("Q")).groupby("q")["excess"].sum()
    share = q[q > 0].max() / q[q > 0].sum() if (q > 0).any() else 1.0
    a2 = share < 0.40
    print(f"\nStage A2 — lottery check: best quarter = {share:.0%} of "
          f"positive quarterly excess (<40% required) → "
          f"{'PASS' if a2 else 'FAIL'}")

    a3 = (a["excess_at"].mean() > n1["excess_at"].mean()
          and a["excess_at"].mean() > n2["excess_at"].mean())
    print(f"\nStage A3 — after-tax: cell {a['excess_at'].mean():+.2f} vs "
          f"nulls {n1['excess_at'].mean():+.2f}/{n2['excess_at'].mean():+.2f}"
          f" → {'PASS' if a3 else 'FAIL'}")

    print(f"\nSTAGE A VERDICT: "
          f"{'PASS — Stage B review >= 2027-04-01 stands'
             if a1 and a2 and a3 else
             'FAIL — cell downgraded to DEAD (spike), Stage B cancelled'}")


if __name__ == "__main__":
    main()

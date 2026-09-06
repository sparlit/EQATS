"""v41 (long-horizon reversal, De Bondt & Thaler). Per PROTOCOL_V41.md.

Signal: trailing 36-month (or 60-month) return skipping the last 21
sessions; hold the 20 WORST, equal weight, annual rebalance.

    python -m backtest.reversal41
"""
import numpy as np
import pandas as pd

from backtest import features, monthly

SKIP = 21
LOOKBACKS = {"36m": 756, "60m": 1260}
REBAL = 252                                      # sessions, = annual
LTCG, STCG = 0.125, 0.20


def picks_for(p, ctx, lookback):
    """month-end -> the 20 worst trailing performers among liquid names"""
    close = p["close"]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    rev = close.shift(SKIP) / close.shift(SKIP + lookback) - 1
    picks, counts = {}, []
    for t in close.index:
        r = rev.loc[t]
        ok = liquid.loc[t].reindex(r.index, fill_value=False)
        ok[[s for s in r.index if s not in ctx["stocks"]]] = False
        cand = r[ok].dropna()
        if len(cand):
            counts.append(len(cand))
        if len(cand) >= 20:
            picks[t] = list(cand.nsmallest(20).index)
    return picks, (np.median(counts) if counts else 0)


def sel_fn(picks):
    def sel(t, m):
        return [s for s in picks.get(t, []) if s in m.index]
    return sel


def after_tax(res):
    """annual rebalance => most lots are LTCG; approximate per-period."""
    r = res["eq"]["ret"]
    eq = 1.0
    for v in r:
        eq *= 1 + (v - (LTCG if v > 0 else 0.0) * max(v, 0.0))
    return 100 * (eq - 1)


def concentration(res):
    r = res["eq"]["ret"]
    b = res["bench"].pct_change().reindex(r.index).fillna(0)
    ex = (r - b)
    yr = ex.groupby(ex.index.year).sum()
    pos = yr[yr > 0]
    return float(pos.max() / pos.sum()) if len(pos) and pos.sum() > 0 else 1.0


def main():
    # BUGFIX 2026-08-28 (to MATCH the registered protocol, not to change
    # it): the panel must start ~4y BEFORE the declared window so the
    # 36-60m lookback is available on day one; trading is then confined
    # to the declared window by dropping earlier formations. The first
    # implementation truncated the panel at the window start, so the
    # lookback silently ate the first ~3 years of each window.
    for label, load_from, win_start, end in (
            ("IS 2017-26 (DECISION)", "2012-01-01", "2017-01-01", None),
            ("OOS 2008-16 (single shot)", "2003-01-01", "2008-01-01",
             "2016-12-31")):
        print(f"\n=== {label} ===")
        p = features._panel(load_from, end)
        keep = p["close"].index >= win_start
        ctx = features._context(p)
        for name, lb in LOOKBACKS.items():
            picks, med = picks_for(p, ctx, lb)
            picks = {t: v for t, v in picks.items()
                     if str(t.date()) >= win_start}
            if not picks:
                print(f"  {name}: no formations with 20+ names")
                continue
            res = monthly.simulate(p, ctx, regime_filter=False,
                                   select_fn=sel_fn(picks),
                                   rebalance_every=REBAL)
            tag = "PRIMARY" if name == "36m" else "C2"
            monthly.report(f"{tag} reversal_{name}", res)
            print(f"      qualifying names/formation (median): {med:.0f}"
                  f" | best-year share of positive excess: "
                  f"{100*concentration(res):.0f}%"
                  f" | after-tax total: {after_tax(res):+.1f}%")
        # C3 diagnostic: PRIMARY + breaker
        picks, _ = picks_for(p, ctx, LOOKBACKS["36m"])
        picks = {t: v for t, v in picks.items()
                 if str(t.date()) >= win_start}
        if picks:
            monthly.report("C3 reversal_36m+breaker", monthly.simulate(
                p, ctx, regime_filter=True, select_fn=sel_fn(picks),
                rebalance_every=REBAL))
        # correlation to v4
        r4 = monthly.simulate(p, ctx, regime_filter=True)
        rr = monthly.simulate(p, ctx, regime_filter=False,
                              select_fn=sel_fn(picks), rebalance_every=REBAL)
        j = pd.concat([r4["eq"]["ret"], rr["eq"]["ret"]], axis=1, join="inner")
        print(f"      corr(v4, reversal): {j.corr().iloc[0,1]:.2f}")


if __name__ == "__main__":
    main()

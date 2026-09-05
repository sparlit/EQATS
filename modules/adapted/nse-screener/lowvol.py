"""v13: India low-volatility sleeve (PROTOCOL_V13.md).

    python -m backtest.lowvol
"""
import numpy as np
import pandas as pd

import config
from backtest import features, monthly


def run() -> None:
    for label, start, end in (("IN-SAMPLE 2023-26", "2022-01-01", None),
                              ("OUT-OF-SAMPLE 2017-22", None, "2022-12-31")):
        print(f"\n=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        daily = p["close"].pct_change()

        def lowvol_sel(lookback=252, n=20):
            minp = min(200, int(lookback * 0.8))
            vol = daily.rolling(lookback, min_periods=minp).std()
            def sel(t, m):
                v = vol.loc[t].reindex(m.index).dropna()   # m = liquid stocks
                return list(v.nsmallest(n).index)
            return sel

        ref = monthly.simulate(p, ctx, regime_filter=True)
        monthly.report("v4-regime (for corr)", ref)
        base = monthly.simulate(p, ctx, select_fn=lowvol_sel())
        monthly.report("v13 low-vol 20", base)
        corr = ref["eq"]["ret"].corr(base["eq"]["ret"])
        print(f"   corr(v4, v13) monthly: {corr:.2f}  (sleeve bar: < 0.6)")
        print("   --- grid ---")
        monthly.report("n_10", monthly.simulate(
            p, ctx, select_fn=lowvol_sel(n=10)))
        monthly.report("n_30", monthly.simulate(
            p, ctx, select_fn=lowvol_sel(n=30)))
        monthly.report("look_126", monthly.simulate(
            p, ctx, select_fn=lowvol_sel(lookback=126)))
        monthly.report("floor_10cr", monthly.simulate(
            p, ctx, select_fn=lowvol_sel(), turnover_floor=1000))
        monthly.report("with_regime", monthly.simulate(
            p, ctx, select_fn=lowvol_sel(), regime_filter=True))


if __name__ == "__main__":
    run()

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


"""v13: India low-volatility sleeve (PROTOCOL_V13.md).

    python -m backtest.lowvol
"""
import numpy as np
import pandas as pd
from backtest import features, monthly

import config


def run() -> None:
    for label, start, end in (("IN-SAMPLE 2023-26", "2022-01-01", None), ("OUT-OF-SAMPLE 2017-22", None, "2022-12-31")):
        print(f"\n=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        daily = p["close"].pct_change()

        def lowvol_sel(lookback=252, n=20):
            minp = min(200, int(lookback * 0.8))
            vol = daily.rolling(lookback, min_periods=minp).std()

            def sel(t, m):
                v = vol.loc[t].reindex(m.index).dropna()  # m = liquid stocks
                return list(v.nsmallest(n).index)

            return sel

        ref = monthly.simulate(p, ctx, regime_filter=True)
        monthly.report("v4-regime (for corr)", ref)
        base = monthly.simulate(p, ctx, select_fn=lowvol_sel())
        monthly.report("v13 low-vol 20", base)
        corr = ref["eq"]["ret"].corr(base["eq"]["ret"])
        print(f"   corr(v4, v13) monthly: {corr:.2f}  (sleeve bar: < 0.6)")
        print("   --- grid ---")
        monthly.report("n_10", monthly.simulate(p, ctx, select_fn=lowvol_sel(n=10)))
        monthly.report("n_30", monthly.simulate(p, ctx, select_fn=lowvol_sel(n=30)))
        monthly.report("look_126", monthly.simulate(p, ctx, select_fn=lowvol_sel(lookback=126)))
        monthly.report("floor_10cr", monthly.simulate(p, ctx, select_fn=lowvol_sel(), turnover_floor=1000))
        monthly.report("with_regime", monthly.simulate(p, ctx, select_fn=lowvol_sel(), regime_filter=True))


if __name__ == "__main__":
    run()

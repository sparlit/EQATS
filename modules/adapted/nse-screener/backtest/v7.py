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


"""v7 earnings momentum (PROTOCOL_V7.md).

    python -m backtest.v7            # both windows, all variants + grid

Signal: SUE = (NP_q − NP_{q−4}) / σ(trailing 8 YoY changes, min 6),
using the latest ANNOUNCED quarter at each formation date — numbers are
keyed to broadcast timestamps, so nothing is known before the market
knew it.
"""
import numpy as np
import pandas as pd
from backtest import features, monthly

import config

PARSED = config.DATA_DIR / "fr_xbrl" / "parsed.parquet"


def sue_frame(dates: pd.DatetimeIndex, trailing: int = 8, simple_yoy: bool = False) -> pd.DataFrame:
    """date × symbol frame of the latest-announced SUE as of each date."""
    fr = pd.read_parquet(PARSED).dropna(subset=["net_profit"])
    from ingest import renames

    fr["symbol"] = renames.canonical(fr["symbol"])
    fr = fr.sort_values("broadcast").drop_duplicates(subset=["symbol", "q_end"], keep="first")
    fr = fr.sort_values(["symbol", "q_end"])

    g = fr.groupby("symbol")
    fr["yoy"] = fr["net_profit"] - g["net_profit"].shift(4)
    fr["sig"] = fr.groupby("symbol")["yoy"].transform(lambda s: s / s.rolling(trailing, min_periods=6).std())
    if simple_yoy:  # grid variant: plain % growth vs |base|
        base = g["net_profit"].shift(4)
        fr["sig"] = fr["yoy"] / base.abs().replace(0, np.nan)
    fr["pos_np"] = fr["net_profit"] > 0

    fr = fr.dropna(subset=["sig"])
    # broadcast → value; a filing becomes usable the session AFTER broadcast
    fr["avail"] = pd.to_datetime(fr["broadcast"]).dt.normalize() + pd.Timedelta(days=1)
    fr = fr.sort_values("avail").drop_duplicates(subset=["symbol", "avail"], keep="last")
    sig = fr.pivot_table(index="avail", columns="symbol", values="sig")
    posnp = fr.pivot_table(index="avail", columns="symbol", values="pos_np")
    # forward-fill onto trading dates; stale filings expire after ~2 quarters
    sig = sig.reindex(sig.index.union(dates)).ffill(limit_area=None).reindex(dates)
    posnp = posnp.reindex(posnp.index.union(dates)).ffill().reindex(dates)
    age_ok = sig.notna()
    return sig.where(age_ok), posnp.astype("float64")


def run() -> None:
    # OOS panel starts 2019: momentum warmup consumes it, entries begin
    # 2020-01 — the registered 2020-22 window, same months for ALL variants
    for label, start, end in (
        ("IN-SAMPLE 2023-26", "2022-01-01", None),
        ("OUT-OF-SAMPLE 2020-22", "2019-01-01", "2022-12-31"),
    ):
        print(f"\n=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        dates = p["close"].index
        sue, posnp = sue_frame(dates)
        sue6, _ = sue_frame(dates, trailing=6)
        yoy, _ = sue_frame(dates, simple_yoy=True)

        def overlay(sig, pool=40, need_pos=False):
            def sel(t, m):
                cand = m.nlargest(pool).index
                s = sig.loc[t].reindex(cand).dropna()
                if need_pos:
                    ok = posnp.loc[t].reindex(s.index) > 0
                    s = s[ok.fillna(False)]
                return list(s.nlargest(20).index)

            return sel

        def standalone(sig):
            def sel(t, m):
                s = sig.loc[t].reindex(m.index).dropna()  # m = liquid universe
                s = s[s > 0]
                return list(s.nlargest(20).index)

            return sel

        ref = monthly.simulate(p, ctx, regime_filter=True)
        monthly.report("v4-regime (incumbent)", ref)
        r_ov = monthly.simulate(p, ctx, regime_filter=True, select_fn=overlay(sue))
        monthly.report("v7-overlay (mom40→SUE20)", r_ov)
        r_st = monthly.simulate(p, ctx, regime_filter=True, select_fn=standalone(sue))
        monthly.report("v7-standalone (SUE20)", r_st)
        corr = ref["eq"]["ret"].corr(r_st["eq"]["ret"])
        print(f"   corr(v4, v7-standalone) monthly: {corr:.2f}  (sleeve criterion: < 0.6)")
        print("   --- grid ---")
        monthly.report("pool_60", monthly.simulate(p, ctx, regime_filter=True, select_fn=overlay(sue, pool=60)))
        monthly.report("sue_6q", monthly.simulate(p, ctx, regime_filter=True, select_fn=overlay(sue6)))
        monthly.report("simple_yoy", monthly.simulate(p, ctx, regime_filter=True, select_fn=overlay(yoy)))
        monthly.report(
            "require_pos_np", monthly.simulate(p, ctx, regime_filter=True, select_fn=overlay(sue, need_pos=True))
        )


if __name__ == "__main__":
    run()

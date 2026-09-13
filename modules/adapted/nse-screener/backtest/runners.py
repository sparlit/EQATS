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


"""Reproducibility pass: committed runners for the studies that originally
ran as inline session scripts. Each function reproduces its protocol's
declared variants verbatim.

    python -m backtest.runners v41|v14|v16|v19|v13q
"""
import sys

import pandas as pd
from backtest import features, monthly, v7
from ingest import vix
from ingest.sectors import sector_map

import config

WINDOWS = (("IS 2023-26", "2022-01-01", None), ("OOS 2017-22", None, "2022-12-31"))


def _each(fn):
    for label, start, end in WINDOWS:
        print(f"=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        fn(p, ctx)


def v41():  # PROTOCOL_V4.1: vol-scaling + FIP
    def run(p, ctx):
        monthly.report("v4-regime", monthly.simulate(p, ctx, regime_filter=True))
        monthly.report("v4.1-vol", monthly.simulate(p, ctx, regime_filter=True, vol_target=0.15))
        monthly.report("v4.1-fip", monthly.simulate(p, ctx, regime_filter=True, fip_pool=40))
        monthly.report("v4.1-full", monthly.simulate(p, ctx, regime_filter=True, vol_target=0.15, fip_pool=40))

    _each(run)


def v14():  # PROTOCOL_V14: VIX regimes
    vs = vix.series()

    def run(p, ctx):
        dates = p["close"].index
        bench = ctx["bench"]
        dma = bench >= bench.rolling(200).mean()
        v = vs.reindex(dates).ffill()

        def reg(cond):
            return cond.reindex(dates).fillna(False)

        monthly.report("v4-regime", monthly.simulate(p, ctx, regime_filter=True))
        monthly.report("dma+vix<25", monthly.simulate(p, ctx, regime_series=reg(dma & (v < 25))))
        monthly.report("vix<20", monthly.simulate(p, ctx, regime_series=reg(dma & (v < 20))))
        monthly.report("vix<30", monthly.simulate(p, ctx, regime_series=reg(dma & (v < 30))))
        monthly.report("vix_only<25", monthly.simulate(p, ctx, regime_series=reg(v < 25)))
        pct = v.rolling(756, min_periods=252).rank(pct=True)
        monthly.report("vix_pctile<.8", monthly.simulate(p, ctx, regime_series=reg(dma & (pct < 0.8))))

    _each(run)


def v16():  # PROTOCOL_V16: residual momentum + 52w-high
    def run(p, ctx):
        close = p["close"]
        r = close.pct_change()
        rm = r["NIFTYBEES"]

        def resmom(bw=756, n=20):
            cov = r.rolling(bw, min_periods=500).cov(rm)
            var = rm.rolling(bw, min_periods=500).var()
            resid = r.sub(cov.div(var, axis=0).mul(rm, axis=0))
            score = resid.shift(21).rolling(231).mean() / resid.shift(21).rolling(231).std()

            def sel(t, m):
                s = score.loc[t].reindex(m.index).dropna()
                return list(s.nlargest(n).index)

            return sel

        def high52(n=20):
            prox = close / close.rolling(252, min_periods=210).max()

            def sel(t, m):
                s = prox.loc[t].reindex(m.index).dropna()
                return list(s.nlargest(n).index)

            return sel

        monthly.report("v4-regime", monthly.simulate(p, ctx, regime_filter=True))
        monthly.report("resmom20", monthly.simulate(p, ctx, regime_filter=True, select_fn=resmom()))
        monthly.report("52w-high", monthly.simulate(p, ctx, regime_filter=True, select_fn=high52()))
        monthly.report("beta504", monthly.simulate(p, ctx, regime_filter=True, select_fn=resmom(bw=504)))
        monthly.report("no_regime", monthly.simulate(p, ctx, select_fn=resmom()))
        monthly.report("top30", monthly.simulate(p, ctx, regime_filter=True, select_fn=resmom(n=30)))

    _each(run)


def v19():  # PROTOCOL_V19: sector momentum
    sec = sector_map()

    def run(p, ctx):
        close = p["close"]
        mom = close.shift(21) / close.shift(252) - 1

        def ssel(top=3, n=20, lb=None):
            sig = mom if lb is None else close.shift(1) / close.shift(lb) - 1

            def sel(t, m):
                s = sig.loc[t].reindex(m.index).dropna()
                ind = sec.reindex(s.index)
                best = s.groupby(ind).median().dropna().nlargest(top).index
                return list(s[ind.isin(best)].nlargest(n).index)

            return sel

        monthly.report("v4-regime", monthly.simulate(p, ctx, regime_filter=True))
        monthly.report("top3", monthly.simulate(p, ctx, regime_filter=True, select_fn=ssel()))
        monthly.report("top5", monthly.simulate(p, ctx, regime_filter=True, select_fn=ssel(top=5)))
        monthly.report("sec126", monthly.simulate(p, ctx, regime_filter=True, select_fn=ssel(lb=126)))
        monthly.report("top30stocks", monthly.simulate(p, ctx, regime_filter=True, select_fn=ssel(n=30)))
        monthly.report("no_regime", monthly.simulate(p, ctx, select_fn=ssel()))

    _each(run)


def v13q():  # PROTOCOL_V13 quality variant (needs v7 fundamentals)
    def run(p, ctx):
        daily = p["close"].pct_change()
        dates = p["close"].index
        _, posnp = v7.sue_frame(dates)
        vol = daily.rolling(252, min_periods=200).std()

        def sel(t, m):
            v = vol.loc[t].reindex(m.index).dropna()
            ok = posnp.loc[t].reindex(v.index) > 0
            return list(v[ok.fillna(False)].nsmallest(20).index)

        monthly.report("v13-quality", monthly.simulate(p, ctx, select_fn=sel))

    _each(run)


def v201():  # PROTOCOL_V20.1: pledge-creation events
    from backtest.events17 import report as _rep
    from backtest.events17 import run_kind
    from backtest.pit_study import load_pit
    from ingest import etf_list

    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)
    pit = load_pit()
    prom = pit["personCategory"].str.contains("Promoter", na=False)
    crea = pit[prom & (pit["acqMode"] == "Pledge Creation")]
    revo = pit[prom & pit["acqMode"].str.contains("Revok", na=False)]
    for label, lo, hi in (("IS 2023-26", "2023-01-01", "2027-01-01"), ("OOS 2018-22", "2018-01-01", "2023-01-01")):
        print(f"=== {label} ===")

        def W(d):
            return d[(d["an_dt"] >= lo) & (d["an_dt"] < hi)]

        nullp = run_kind(W(pit), *args, gap_days=0)
        nm = nullp["excess"].mean()
        _rep("pledge CREATION 63d", run_kind(W(crea), *args, gap_days=63), nm)
        _rep("creation hold_21", run_kind(W(crea), *args, hold=21, gap_days=63), nm)
        _rep("creation hold_126", run_kind(W(crea), *args, hold=126, gap_days=63), nm)
        _rep("REVOCATION control", run_kind(W(revo), *args, gap_days=63), nm)


def v24():  # PROTOCOL_V24: NSE-200 winner (hysteresis)
    def run(p, ctx):
        close = p["close"]
        t200 = p["turnover_lacs"].rolling(20).median()

        def mk(lb=252, hyst=True):
            ret = close.shift(1) / close.shift(lb) - 1
            held = []

            def sel(t, m):
                nonlocal held
                uni = t200.loc[t].reindex(m.index).dropna().nlargest(200).index
                r = ret.loc[t].reindex(uni).dropna().sort_values(ascending=False)
                top20, top40 = list(r.index[:20]), set(r.index[:40])
                if hyst:
                    keep = [x for x in held if x in top40]
                    held = (keep + [x for x in top20 if x not in keep])[:20]
                else:
                    held = top20
                return held

            return sel

        monthly.report("v4-regime", monthly.simulate(p, ctx, regime_filter=True))
        monthly.report("v24 12m hyst", monthly.simulate(p, ctx, select_fn=mk()))
        monthly.report("v24 6m", monthly.simulate(p, ctx, select_fn=mk(lb=126)))
        monthly.report("v24 +regime", monthly.simulate(p, ctx, regime_filter=True, select_fn=mk()))
        monthly.report("v24 no-hyst", monthly.simulate(p, ctx, select_fn=mk(hyst=False)))

    _each(run)


if __name__ == "__main__":
    {"v41": v41, "v14": v14, "v16": v16, "v19": v19, "v13q": v13q, "v201": v201, "v24": v24}[sys.argv[1]]()

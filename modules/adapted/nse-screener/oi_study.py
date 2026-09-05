"""v23: futures open-interest signals (PROTOCOL_V23.md).

    python -m backtest.oi_study
"""
from pathlib import Path

import numpy as np
import pandas as pd

import config
from backtest import features, monthly
from ingest import renames


def load_futstk():
    df = pd.concat(map(pd.read_parquet,
                       Path(config.DATA_DIR / "futstk").glob("*.parquet")),
                   ignore_index=True)
    df["symbol"] = renames.canonical(df["symbol"])
    # near-month contract per (date, symbol)
    df = df[df["expiry"] >= df["date"]]
    near = (df.sort_values("expiry").groupby(["date", "symbol"],
                                             as_index=False).first())
    oi = near.pivot_table(index="date", columns="symbol", values="oi")
    fut = near.pivot_table(index="date", columns="symbol", values="close")
    return oi, fut


def run():
    oi_all, fut_all = load_futstk()
    for label, start, end in (("IS 2023-26", "2022-01-01", None),
                              ("OOS 2017-22", None, "2022-12-31")):
        print(f"=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        dates = p["close"].index
        oi = oi_all.reindex(index=dates, columns=p["close"].columns)
        fut = fut_all.reindex(index=dates, columns=p["close"].columns)
        oig = oi / oi.shift(21) - 1
        basis = fut / p["close"] - 1
        bz = (basis - basis.rolling(252, min_periods=126).mean()) \
            / basis.rolling(252, min_periods=126).std()

        def fo_incumbent(t, m):
            u = oi.loc[t].reindex(m.index).dropna().index
            return list(m.reindex(u).dropna().nlargest(20).index)

        def oi_overlay(window=21, contrarian=False):
            g = oi / oi.shift(window) - 1
            def sel(t, m):
                cand = m.nlargest(40).index
                s = g.loc[t].reindex(cand).dropna()
                s = s.nsmallest(20) if contrarian else s.nlargest(20)
                return list(s.index)
            return sel

        def basis_screen(deciles=1):
            def sel(t, m):
                u = oi.loc[t].reindex(m.index).dropna().index
                mm = m.reindex(u).dropna()
                z = bz.loc[t].reindex(mm.index)
                cut = z.quantile(1 - 0.1 * deciles)
                keep = mm[(z < cut) | z.isna()]
                return list(keep.nlargest(20).index)
            return sel

        monthly.report("v4-FO incumbent", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=fo_incumbent))
        monthly.report("A: OI-confirm 21d", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=oi_overlay()))
        monthly.report("A: window 10", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=oi_overlay(10)))
        monthly.report("A: window 42", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=oi_overlay(42)))
        monthly.report("A: contrarian", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=oi_overlay(contrarian=True)))
        monthly.report("B: basis-screen top1dec", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=basis_screen()))
        monthly.report("B: top2dec", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=basis_screen(2)))


if __name__ == "__main__":
    run()

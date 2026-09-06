"""v31 (quality/profitability composite). Per PROTOCOL_V31.md.

    python -m backtest.quality31
"""
import pandas as pd

import config
from backtest import features, monthly
from ingest import renames
from ingest.constituents import implied_shares, raw_close_panel

FLOOR = 5e10                                     # ₹5,000cr, as v29 primary


def quality_frame():
    d = pd.read_parquet(config.DATA_DIR / "fr_xbrl" / "parsed.parquet")
    d = d.dropna(subset=["net_profit", "revenue", "q_end", "broadcast"])
    d = d[d["revenue"] > 0]
    d["symbol"] = renames.canonical(d["symbol"].astype(str))
    d = (d.sort_values("broadcast")
           .drop_duplicates(["symbol", "q_end"], keep="last")
           .sort_values(["symbol", "q_end"]))
    rows = []
    for sym, g in d.groupby("symbol"):
        g = g.reset_index(drop=True)
        for i in range(7, len(g)):
            w8 = g.iloc[i - 7:i + 1]
            if (w8["q_end"].iloc[-1] - w8["q_end"].iloc[0]).days > 800:
                continue
            m = w8["net_profit"] / w8["revenue"]
            ttm_np = w8["net_profit"].iloc[4:].sum()
            ttm_rev = w8["revenue"].iloc[4:].sum()
            streak = 0
            for v in reversed(list(g["net_profit"].iloc[:i + 1])):
                if v > 0: streak += 1
                else: break
            rows.append({"symbol": sym,
                         "avail": w8["broadcast"].iloc[4:].max(),
                         "margin": ttm_np / ttm_rev,
                         "stab": m.std(),
                         "streak": min(streak, 12)})
    return pd.DataFrame(rows).sort_values("avail")


def build_picks():
    f = quality_frame()
    closes = raw_close_panel()
    sh = implied_shares()
    sh_p = (sh.pivot_table(index="broadcast", columns="symbol",
                           values="shares", aggfunc="last").sort_index())
    piv = {c: f.pivot_table(index="avail", columns="symbol", values=c,
                            aggfunc="last").sort_index()
           for c in ("margin", "stab", "streak")}
    picks = {}
    for t in closes.index:
        if not len(piv["margin"].loc[:t]):
            continue
        mg = piv["margin"].loc[:t].ffill().iloc[-1]
        st = piv["stab"].loc[:t].ffill().iloc[-1]
        sk = piv["streak"].loc[:t].ffill().iloc[-1]
        shares = sh_p.loc[:t].ffill().iloc[-1] if len(sh_p.loc[:t]) else None
        if shares is None:
            continue
        mcap = closes.loc[t] * shares
        ok = mcap > FLOOR
        comp = (mg.rank() + (-st).rank() + sk.rank()) / 3
        comp = comp[ok.reindex(comp.index).fillna(False)]
        picks[pd.Timestamp(t.date())] = list(comp.dropna().nlargest(40).index)
    return picks


def sel_fn(picks):
    def sel(t, m):
        return [s for s in picks.get(pd.Timestamp(t.date()), [])
                if s in m.index]
    return sel


def main():
    picks = build_picks()
    for label, start, end in (("IS 2023-26 (DECISION)", "2022-01-01", None),
                              ("OOS 2019H2-22 (single shot)",
                               "2018-07-01", "2022-12-31")):
        print(f"\n=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        rq = monthly.simulate(p, ctx, regime_filter=False,
                              select_fn=sel_fn(picks))
        monthly.report("quality_primary", rq)
        monthly.report("quality_regime", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=sel_fn(picks)))
        r4 = monthly.simulate(p, ctx, regime_filter=True)
        j = pd.concat([r4["eq"]["ret"], rq["eq"]["ret"]], axis=1,
                      join="inner")
        print(f"  corr(v4, quality): {j.corr().iloc[0,1]:.2f}")


if __name__ == "__main__":
    main()

"""v29 India cells (PROTOCOL_V29.md): Lynch-tweet GARP screen.
P/E and mcap use RAW prices + as-reported EPS (adjusted prices would
mismatch as-reported per-share values); returns use the audited
monthly engine on the CA-adjusted panel. Known noise, disclosed: a
split between TTM windows makes EPS growth look negative (drops the
candidate — conservative for a >15% growth filter).

    python -m backtest.garp29
"""
import pandas as pd

import config
from backtest import features, monthly
from ingest import renames
from ingest.constituents import implied_shares, raw_close_panel

PE_MAX, G_MIN, PEG_MAX = 25.0, 0.15, 2.0
MCAP_PRIMARY, MCAP_LITERAL = 5e10, 4.2e11        # ₹5,000cr / ≈$5B
TOP_BY_PEG = 40


def ttm_frame() -> pd.DataFrame:
    """Per symbol: availability timestamp → (ttm, prev_ttm growth)."""
    d = pd.read_parquet(config.DATA_DIR / "fr_xbrl" / "parsed.parquet")
    d = d.dropna(subset=["eps", "q_end", "broadcast"])
    d["symbol"] = renames.canonical(d["symbol"].astype(str))
    d = (d.sort_values("broadcast")
           .drop_duplicates(["symbol", "q_end"], keep="last")
           .sort_values(["symbol", "q_end"]))
    rows = []
    for sym, g in d.groupby("symbol"):
        g = g.reset_index(drop=True)
        for i in range(7, len(g)):
            w8 = g.iloc[i - 7:i + 1]
            # 8 consecutive-ish quarters: span sanity
            if (w8["q_end"].iloc[-1] - w8["q_end"].iloc[0]).days > 800:
                continue
            ttm = w8["eps"].iloc[4:].sum()
            prev = w8["eps"].iloc[:4].sum()
            if ttm <= 0 or prev <= 0:
                continue
            rows.append({"symbol": sym,
                         "avail": w8["broadcast"].iloc[4:].max(),
                         "ttm": ttm, "growth": ttm / prev - 1})
    return pd.DataFrame(rows).sort_values("avail")


def build_picks(mcap_floor: float) -> dict:
    """formation month-end -> list of qualifying symbols (<=40 by PEG)"""
    f = ttm_frame()
    closes = raw_close_panel()                    # month-end raw closes
    sh = implied_shares()
    sh_piv = (sh.pivot_table(index="broadcast", columns="symbol",
                             values="shares", aggfunc="last").sort_index())
    ttm_piv = (f.pivot_table(index="avail", columns="symbol",
                             values="ttm", aggfunc="last").sort_index())
    g_piv = (f.pivot_table(index="avail", columns="symbol",
                           values="growth", aggfunc="last").sort_index())
    picks = {}
    for t in closes.index:
        if not len(ttm_piv.loc[:t]):
            continue
        px = closes.loc[t]
        ttm = ttm_piv.loc[:t].ffill().iloc[-1]
        gr = g_piv.loc[:t].ffill().iloc[-1]
        shares = sh_piv.loc[:t].ffill().iloc[-1] \
            if len(sh_piv.loc[:t]) else None
        if shares is None:
            continue
        pe = px / ttm
        peg = pe / (100 * gr)
        mcap = px * shares
        ok = ((pe > 0) & (pe < PE_MAX) & (gr > G_MIN)
              & (peg > 0) & (peg < PEG_MAX) & (mcap > mcap_floor))
        q = peg[ok.fillna(False)].dropna().nsmallest(TOP_BY_PEG)
        picks[pd.Timestamp(t.date())] = list(q.index)
    return picks


def garp_select(picks):
    def sel(t, m):
        cand = picks.get(pd.Timestamp(t.date()), [])
        return [s for s in cand if s in m.index]
    return sel


def main():
    picks_p = build_picks(MCAP_PRIMARY)
    picks_l = build_picks(MCAP_LITERAL)
    sizes = pd.Series({t: len(v) for t, v in picks_p.items()})
    print(f"primary qualifiers/month: median {sizes.median():.0f} "
          f"min {sizes.min()} max {sizes.max()}")
    for label, start, end in (("IS 2023-26 (DECISION)", "2022-01-01", None),
                              ("OOS 2019H2-22 (single shot)",
                               "2018-07-01", "2022-12-31")):
        print(f"\n=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        monthly.report("garp_primary", monthly.simulate(
            p, ctx, regime_filter=False, select_fn=garp_select(picks_p)))
        monthly.report("garp_regime", monthly.simulate(
            p, ctx, regime_filter=True, select_fn=garp_select(picks_p)))
        monthly.report("garp_literal_5B", monthly.simulate(
            p, ctx, regime_filter=False, select_fn=garp_select(picks_l)))


if __name__ == "__main__":
    main()

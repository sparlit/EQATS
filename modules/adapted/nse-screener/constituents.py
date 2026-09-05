"""Synthetic point-in-time index constituents.

shares_out ≈ net_profit / EPS from our 43k XBRL filings (95.7% usable;
RELIANCE sanity: implied 13.52-13.54bn vs ~13.5bn actual) → market cap =
RAW close × latest point-in-time share count (raw, NOT the CA-adjusted
panel — back-adjusted prices with contemporaneous share counts corrupt
cross-sectional ranks around splits) → month-end ranks → top-N sets.
Free-float variant weights by (1 - promoter%) from the shareholding
masters (Nifty's actual methodology).

    python -m ingest.constituents          # build + calibrate vs Wayback
Writes data/constituents_synth.parquet (month-end, symbol, mcap ranks).
"""
from pathlib import Path

import pandas as pd

import config
from ingest import renames

OUT = config.DATA_DIR / "constituents_synth.parquet"


def implied_shares() -> pd.DataFrame:
    """(symbol, broadcast, shares) — point-in-time implied share count."""
    d = pd.read_parquet(config.DATA_DIR / "fr_xbrl" / "parsed.parquet")
    d = d[d["eps"].notna() & d["net_profit"].notna() & (d["eps"] != 0)]
    d = d.sort_values("broadcast").drop_duplicates(["symbol", "q_end"],
                                                   keep="last")
    d["shares"] = d["net_profit"] / d["eps"]
    d = d[d["shares"] > 0]
    d["symbol"] = renames.canonical(d["symbol"].astype(str))
    return d[["symbol", "broadcast", "shares"]]


def promoter_pct() -> pd.DataFrame:
    """(symbol, bcast, prom) point-in-time promoter % from masters."""
    rows = []
    for f in (config.DATA_DIR / "shareholding").glob("*.parquet"):
        rows.append(pd.read_parquet(f))
    d = pd.concat(rows, ignore_index=True)
    d["bcast"] = pd.to_datetime(d["broadcastDate"],
                                format="%d-%b-%Y %H:%M:%S", errors="coerce")
    d["prom"] = pd.to_numeric(d["pr_and_prgrp"], errors="coerce")
    d = d.dropna(subset=["bcast", "prom"])
    d["symbol"] = renames.canonical(d["symbol"].astype(str))
    return d[["symbol", "bcast", "prom"]].sort_values("bcast")


def raw_close_panel() -> pd.DataFrame:
    """Month-end RAW closes (no CA adjustment, by design)."""
    frames = []
    for f in sorted((config.DATA_DIR / "bhav").glob("*.parquet")):
        d = pd.read_parquet(f)[["symbol", "date", "close"]]
        frames.append(d)
    px = pd.concat(frames, ignore_index=True)
    px["symbol"] = renames.canonical(px["symbol"].astype(str))
    px["date"] = pd.to_datetime(px["date"])
    wide = px.pivot_table(index="date", columns="symbol", values="close")
    month_ends = wide.groupby(wide.index.to_period("M")).tail(1)
    return month_ends


def build() -> pd.DataFrame:
    sh = implied_shares()
    prom = promoter_pct()
    closes = raw_close_panel()
    sh_piv = (sh.pivot_table(index="broadcast", columns="symbol",
                             values="shares", aggfunc="last")
                .sort_index())
    prom_piv = (prom.pivot_table(index="bcast", columns="symbol",
                                 values="prom", aggfunc="last")
                    .sort_index())
    rows = []
    for t in closes.index:
        if t < pd.Timestamp("2018-01-01"):     # EPS coverage thin before
            continue
        shares = sh_piv.loc[:t].ffill().iloc[-1] if len(sh_piv.loc[:t]) \
            else None
        if shares is None:
            continue
        pr = prom_piv.loc[:t].ffill().iloc[-1] if len(prom_piv.loc[:t]) \
            else pd.Series(dtype=float)
        px = closes.loc[t]
        mcap = (px * shares).dropna()
        ff = (mcap * (1 - pr.reindex(mcap.index).fillna(0) / 100)).dropna()
        for name, series in (("mcap", mcap), ("ffmcap", ff)):
            ranked = series.rank(ascending=False)
            for sym, rk in ranked[ranked <= 600].items():
                rows.append({"date": t, "symbol": sym, "kind": name,
                             "rank": int(rk)})
    out = pd.DataFrame(rows)
    out.to_parquet(OUT, index=False)
    print(f"built: {len(out)} rank rows, "
          f"{out['date'].nunique()} month-ends → {OUT.name}")
    return out


def calibrate(out: pd.DataFrame) -> None:
    """Jaccard overlap vs the 13 Wayback snapshots, both mcap variants."""
    print("\ncalibration vs real snapshots (Jaccard / recall):")
    for f in sorted((config.DATA_DIR / "index_members").glob("*.parquet")):
        snap = pd.read_parquet(f)
        idx, asof = snap["index"].iloc[0], str(snap["asof"].iloc[0])
        n = 500 if "500" in idx else 50
        actual = set(renames.canonical(snap["symbol"].astype(str)))
        t = pd.Timestamp(asof)
        dates = out["date"].unique()
        near = max(d for d in dates if d <= t) if (dates <= t).any() else None
        if near is None:
            print(f"  {idx} {asof}: predates synthetic panel — skipped")
            continue
        for kind in ("mcap", "ffmcap"):
            syn = set(out[(out["date"] == near) & (out["kind"] == kind)
                          & (out["rank"] <= n)]["symbol"])
            jac = len(actual & syn) / len(actual | syn)
            rec = len(actual & syn) / len(actual)
            print(f"  {idx} {asof} [{kind:>6}]: jaccard {jac:.2f}  "
                  f"recall {rec:.2f}  (synthetic month-end {near.date()})")


if __name__ == "__main__":
    calibrate(build())

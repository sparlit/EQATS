"""v4 through the crisis era (2006–2015). Per PROTOCOL_CRISIS.md —
single shot, stress test, NOT a gate. Benchmark and regime come from the
NIFTY 50 price index (NIFTYBEES too thin pre-2016; flatters v4 by ~1.5%/yr
of missing dividends — diagnostic D2 corrects for it).

    python -m backtest.crisis
"""
import numpy as np
import pandas as pd

import config
from backtest import features, monthly
from ingest import etf_list

SUBS = (("2006-07 bull", "2006-01-01", "2007-12-31"),
        ("2008 crash", "2008-01-01", "2008-12-31"),
        ("2009 recovery", "2009-01-01", "2009-12-31"),
        ("2010-15 chop", "2010-01-01", "2015-12-31"))


def nifty_close(dates) -> pd.Series:
    df = pd.read_parquet(config.DATA_DIR / "indices" / "NIFTY_50_OHLC.parquet")
    df["date"] = pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y")
    s = (df.sort_values("date").drop_duplicates("date")
           .set_index("date")["EOD_CLOSE_INDEX_VAL"].astype(float))
    return s.reindex(dates).ffill()


def maxdd(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min())


def run(p, ctx, bench, label, **kw):
    r = monthly.simulate(p, ctx, **kw)
    eq = r["eq"]["equity"]
    b = bench.loc[eq.index]
    b = b / b.iloc[0]
    tot, btot = 100 * (eq.iloc[-1] - 1), 100 * (b.iloc[-1] - 1)
    print(f"  {label:<22} total {tot:+8.1f}%  index {btot:+8.1f}%  "
          f"edge {tot - btot:+7.1f}pt  maxDD {100 * maxdd(eq):+6.1f}% "
          f"(index {100 * maxdd(b):+6.1f}%)  delist {r['delist_exits']}")
    for name, lo, hi in SUBS:
        w = eq.loc[lo:hi]
        bw = b.loc[lo:hi]
        if len(w) < 3:
            continue
        print(f"      {name:<14} v4 {100 * (w.iloc[-1] / w.iloc[0] - 1):+7.1f}%"
              f"  index {100 * (bw.iloc[-1] / bw.iloc[0] - 1):+7.1f}%"
              f"  v4 DD {100 * maxdd(w):+6.1f}%")
    return r, eq, b


def main():
    p = features._panel("2005-01-01", "2015-12-31")
    close = p["close"]
    bench = nifty_close(close.index)
    etfs = etf_list.symbols()
    ctx = {"bench": bench,
           "stocks": [c for c in close.columns if c not in etfs]}

    print("=== PRIMARY: v4 verbatim, index regime ===")
    r, eq, b = run(p, ctx, bench, "v4 (200DMA breaker)", regime_filter=True)

    print("\n=== D1: regime OFF (what the breaker contributed) ===")
    run(p, ctx, bench, "v4 no breaker", regime_filter=False)

    print("\n=== D2: dividend-adjusted benchmark (+1.5%/yr) ===")
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    tot = 100 * (eq.iloc[-1] - 1)
    btot_adj = 100 * ((b.iloc[-1]) * (1.015 ** yrs) - 1)
    print(f"  v4 {tot:+.1f}% vs div-adj index {btot_adj:+.1f}%  "
          f"edge {tot - btot_adj:+.1f}pt")

    print("\n=== D3: liquidity floor scaled to era (Nifty-level ratio) ===")
    scale = float(bench.iloc[-1]) / 24000.0     # era Nifty vs ~today's
    run(p, ctx, bench, f"floor x{scale:.2f}", regime_filter=True,
        turnover_floor=500.0 * scale)

    print("\nPASS bars (PROTOCOL_CRISIS): PRIMARY beats index total AND "
          "PRIMARY maxDD <= index maxDD.")


if __name__ == "__main__":
    main()

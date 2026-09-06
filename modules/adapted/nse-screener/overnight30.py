"""v30 (overnight anomaly). Per PROTOCOL_V30.md — decomposition on the
CA-adjusted panel + the costed close→open trade on NIFTYBEES.

    python -m backtest.overnight30
"""
import pandas as pd

from backtest import features
from ingest import etf_list

TIERS = (0.0050, 0.0010, 0.0005, 0.0002)   # round-trip cost tiers


def split(open_, close):
    """(overnight, intraday) daily return series, aligned to exit day"""
    overnight = open_ / close.shift(1) - 1
    intraday = close / open_ - 1
    return overnight, intraday


def cum(r):
    r = r.dropna()
    return float((1 + r).prod() - 1)


def main():
    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    bees_c, bees_o = close["NIFTYBEES"], open_["NIFTYBEES"]
    on, intra = split(bees_o, bees_c)

    etfs = etf_list.symbols()
    stocks = [c for c in close.columns if c not in etfs]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    s_on, s_in = split(open_[stocks], close[stocks])
    lq = liquid[stocks].shift(1).fillna(False)
    ew_on = s_on[lq].mean(axis=1)              # equal-weight liquid panel
    ew_in = s_in[lq].mean(axis=1)

    for label, lo, hi in (("FULL 2016-26", None, None),
                          ("IS 2023-26", "2023-01-01", "2027-01-01"),
                          ("OOS 2016-22", "2016-01-01", "2023-01-01")):
        w = (slice(lo, hi))
        print(f"\n=== {label} ===")
        bh = cum(bees_c.loc[w].pct_change())
        print(f"  C1 NIFTYBEES : overnight {100*cum(on.loc[w]):+9.1f}%   "
              f"intraday {100*cum(intra.loc[w]):+7.1f}%   "
              f"buy&hold {100*bh:+7.1f}%")
        print(f"  C2 EW stocks : overnight {100*cum(ew_on.loc[w]):+9.1f}%   "
              f"intraday {100*cum(ew_in.loc[w]):+7.1f}%")
        if lo is None:
            continue
        print(f"  C3 net close→open trade vs buy&hold {100*bh:+.1f}%:")
        for c in TIERS:
            net = (1 + on.loc[w].dropna()) * (1 - c) - 1
            tot = cum(net)
            tag = "PASS-tier" if (tot > bh and c >= 0.0005) else \
                  ("diag" if tot > bh else "dead")
            print(f"     {100*c:.2f}% RT: {100*tot:+9.1f}%  [{tag}]")


if __name__ == "__main__":
    main()


def index_cells():
    """The honest version of C1/C3: real NIFTY 50 index OHLC
    (data/indices/NIFTY_50_OHLC.parquet, fetched month-by-month — the
    yearly API hits NSE's 70-row JSON cap, a documented trap that
    struck again). Required because bhav ETF OPEN prints are unusable
    (stale first ticks up to ±13% off adjacent trades; NIFTYBEES
    'overnight' compounds to +86e9% on them — pure artifact).
    Index prints are an UPPER bound on tradability (real fills worse).

        python -c "from backtest.overnight30 import index_cells; index_cells()"
    """
    import config
    df = pd.read_parquet(config.DATA_DIR / "indices" / "NIFTY_50_OHLC.parquet")
    df["date"] = pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y")
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    o = df["EOD_OPEN_INDEX_VAL"].astype(float)
    c = df["EOD_CLOSE_INDEX_VAL"].astype(float)
    on, intra = split(o, c)
    for label, lo, hi in (("FULL 2016-26", None, None),
                          ("IS 2023-26", "2023-01-01", None),
                          ("OOS 2016-22", None, "2022-12-31")):
        w = slice(lo, hi)
        bh = cum(c.loc[w].pct_change().dropna())
        print(f"{label}: overnight {100*cum(on.loc[w]):+8.1f}%  "
              f"intraday {100*cum(intra.loc[w]):+7.1f}%  bh {100*bh:+6.1f}%")
        if lo is None and hi is None:
            continue
        for cost in TIERS:
            net = cum((1 + on.loc[w].dropna()) * (1 - cost) - 1)
            print(f"    C3@{100*cost:.2f}%RT: {100*net:+8.1f}%  "
                  f"[{'beats bh' if net > bh else 'dead'}]")

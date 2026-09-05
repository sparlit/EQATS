"""v32 (turn-of-month / SIP-flow seasonality). Per PROTOCOL_V32.md.

    python -m backtest.tom32
"""
import pandas as pd

import config


def main():
    df = pd.read_parquet(config.DATA_DIR / "indices"
                         / "NIFTY_50_OHLC.parquet")
    df["date"] = pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y")
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    c = df["EOD_CLOSE_INDEX_VAL"].astype(float)
    r = c.pct_change().dropna()
    mo = r.index.to_period("M")
    # trading-day position within month (1-based) and from month-end (neg)
    pos = r.groupby(mo).cumcount() + 1
    rev = r.groupby(mo).cumcount(ascending=False) + 1
    in_c1 = (rev <= 2) | (pos.groupby(mo).shift(0) <= 3)
    # C1: from close of 2nd-last day to close of 3rd day next month =
    # returns on last day + first 3 days
    c1_mask = (rev <= 1) | (pos <= 3)
    c2_mask = pos <= 5
    cum = lambda x: float((1 + x).prod() - 1)
    for label, lo, hi in (("IS 2023-26 (DECISION)", "2023-01-01", None),
                          ("OOS 2006-22 (single shot)", "2006-01-01",
                           "2022-12-31")):
        w = slice(lo, hi)
        rw = r.loc[w]
        bh = cum(rw)
        n_months = rw.index.to_period("M").nunique()
        print(f"\n=== {label} ===  buy&hold {100*bh:+8.1f}%  "
              f"({n_months} months)")
        for name, mask in (("C1 TOM (last1+first3)", c1_mask),
                           ("C2 SIP (first5)", c2_mask),
                           ("C3 rest-of-month", ~c1_mask)):
            g = cum(rw[mask.loc[w]])
            share = g / bh if bh else float("nan")
            line = f"  {name:<22} gross {100*g:+8.1f}%"
            if name.startswith("C3"):
                print(line); continue
            for cost in (0.0005, 0.0010):
                net = float((1 + rw[mask.loc[w]]).prod()
                            * (1 - cost) ** n_months - 1)
                line += (f"  | net@{100*cost:.2f}%RT {100*net:+8.1f}% "
                         f"[{'beats' if net > bh else 'dead'}]")
            print(line)
        d_in = int(c1_mask.loc[w].sum())
        print(f"  concentration: C1 days = {d_in}/{len(rw)} "
              f"({100*d_in/len(rw):.0f}% of days)")


if __name__ == "__main__":
    main()

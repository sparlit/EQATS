"""v33 (dual momentum India / GEM). Per PROTOCOL_V33.md.
Close-to-close fills (bhav ETF opens are fake — v30 trap); cash leg 0%
in PRIMARY (LIQUIDBEES yield is bonus units, invisible in prices).

    python -m backtest.dualmom33
"""
import pandas as pd

from backtest import features

ETFS = ("NIFTYBEES", "JUNIORBEES", "GOLDBEES", "LIQUIDBEES")
COST = 0.0025                                    # per side, on switches


def month_ends(close):
    return close.groupby(close.index.to_period("M")).tail(1).index


def run(close, cash_accrual=0.0, use_gold=True):
    me = month_ends(close)
    c = close.loc[me]
    r12 = c / c.shift(12) - 1
    hold, eq, switches = None, 1.0, 0
    curve = {}
    for k in range(12, len(me) - 1):
        t, t1 = me[k], me[k + 1]
        eqw = "NIFTYBEES" if (r12.loc[t, "NIFTYBEES"]
                              >= r12.loc[t, "JUNIORBEES"]) else "JUNIORBEES"
        if r12.loc[t, eqw] > r12.loc[t, "LIQUIDBEES"]:
            tgt = eqw
        elif use_gold and r12.loc[t, "GOLDBEES"] > r12.loc[t, "LIQUIDBEES"]:
            tgt = "GOLDBEES"
        else:
            tgt = "LIQUIDBEES"
        # execute at NEXT close after month-end t: approximate the
        # holding return as close(t)->close(t1) of the target, charging
        # the switch cost (one-day execution lag is symmetric noise at
        # monthly horizon; opens are unusable per the trap)
        ret = close.loc[t1, tgt] / close.loc[t, tgt] - 1
        if tgt == "LIQUIDBEES":
            days = (t1 - t).days
            ret = max(ret, 0.0) + cash_accrual * days / 365
        if tgt != hold:
            ret -= 2 * COST
            switches += 1
            hold = tgt
        eq *= 1 + ret
        curve[t1] = eq
    return pd.Series(curve), switches


def stats(eqs, close, lo, hi):
    w = eqs.loc[lo:hi]
    if len(w) < 2:
        return None
    tot = w.iloc[-1] / w.iloc[0] - 1
    dd = (w / w.cummax() - 1).min()
    b = close.loc[w.index[0]:w.index[-1], "NIFTYBEES"]
    return 100 * tot, 100 * dd, 100 * (b.iloc[-1] / b.iloc[0] - 1), \
        100 * (b / b.cummax() - 1).min()


def main():
    p = features._panel(None, None)
    close = p["close"][list(ETFS)].dropna(how="all")
    close = close.dropna()                        # all four must exist
    print(f"panel: {close.index[0].date()} → {close.index[-1].date()}")
    for name, kw in (("PRIMARY", {}),
                     ("D1 cash+5%/yr", dict(cash_accrual=0.05)),
                     ("D2 no-gold", dict(use_gold=False))):
        eqs, sw = run(close, **kw)
        print(f"\n### {name} (switches: {sw})")
        for label, lo, hi in (("IS 2023-26 (DECISION)", "2023-01-01", None),
                              ("OOS 2008-22 (single shot)", "2008-01-01",
                               "2022-12-31"),
                              ("2008", "2008-01-01", "2008-12-31"),
                              ("2009", "2009-01-01", "2009-12-31"),
                              ("2010-15", "2010-01-01", "2015-12-31"),
                              ("2016-22", "2016-01-01", "2022-12-31")):
            s = stats(eqs, close, lo, hi)
            if s is None:
                continue
            tot, dd, btot, bdd = s
            gate = ""
            if label.startswith(("IS", "OOS")):
                gate = f"  [{'beats' if tot > btot else 'dead'}]"
            print(f"  {label:<26} v33 {tot:+8.1f}% (DD {dd:+6.1f}%)  "
                  f"bees {btot:+8.1f}% (DD {bdd:+6.1f}%){gate}")


if __name__ == "__main__":
    main()

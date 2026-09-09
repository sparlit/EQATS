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


"""v33.1 Stage A: confirmation gauntlet for dual momentum's pass.
Per PROTOCOL_V33.1.md.

    python -m backtest.dualmom331
"""
import pandas as pd
from backtest import features
from backtest.dualmom33 import COST, ETFS, month_ends

STCG, LTCG = 0.20, 0.125


def run_full(close, lookback=12, shift_days=0, cost=COST, cash_accrual=0.0):
    me = list(month_ends(close))
    dates = close.index
    if shift_days:
        me = [dates[min(max(dates.searchsorted(t) + shift_days, 0), len(dates) - 1)] for t in me]
    c = close.loc[me]
    r = c / c.shift(lookback) - 1
    hold, eq = None, 1.0
    curve, lots = {}, []
    entry_t = entry_px = None
    for k in range(lookback, len(me) - 1):
        t, t1 = me[k], me[k + 1]
        eqw = "NIFTYBEES" if (r.loc[t, "NIFTYBEES"] >= r.loc[t, "JUNIORBEES"]) else "JUNIORBEES"
        if r.loc[t, eqw] > r.loc[t, "LIQUIDBEES"]:
            tgt = eqw
        elif r.loc[t, "GOLDBEES"] > r.loc[t, "LIQUIDBEES"]:
            tgt = "GOLDBEES"
        else:
            tgt = "LIQUIDBEES"
        ret = close.loc[t1, tgt] / close.loc[t, tgt] - 1
        if tgt == "LIQUIDBEES":
            ret = max(ret, 0.0) + cash_accrual * (t1 - t).days / 365
        if tgt != hold:
            if hold is not None and entry_t is not None:
                lots.append((entry_t, t, close.loc[t, hold] / entry_px - 1))
            entry_t, entry_px = t, close.loc[t, tgt]
            ret -= 2 * cost
            hold = tgt
        eq *= 1 + ret
        curve[t1] = eq
    if hold is not None and entry_t is not None:
        lots.append((entry_t, me[-1], close.loc[me[-1], hold] / entry_px - 1))
    return pd.Series(curve), lots


def edge(eqs, close, lo, hi):
    w = eqs.loc[lo:hi]
    if len(w) < 2:
        return None
    b = close.loc[w.index[0] : w.index[-1], "NIFTYBEES"]
    return 100 * (w.iloc[-1] / w.iloc[0] - 1) - 100 * (b.iloc[-1] / b.iloc[0] - 1)


def main():
    p = features._panel(None, None)
    close = p["close"][list(ETFS)].dropna()
    WINDOWS = (("IS", "2023-01-01", None), ("OOS", "2008-01-01", "2022-12-31"))
    perts = [
        ("lookback 9m", {"lookback": 9}, "both"),
        ("lookback 15m", {"lookback": 15}, "both"),
        ("formation -3d", {"shift_days": -3}, "both"),
        ("formation +3d", {"shift_days": 3}, "both"),
        ("cost 0.50%/side", {"cost": 0.005}, "both"),
        ("cash +5%/yr", {"cash_accrual": 0.05}, "both"),
        ("OOS half 2008-14", {}, ("2008-01-01", "2014-12-31")),
        ("OOS half 2015-22", {}, ("2015-01-01", "2022-12-31")),
    ]
    ok = 0
    print("Stage A1 — plateau:")
    for name, kw, win in perts:
        eqs, _ = run_full(close, **kw)
        if win == "both":
            es = [edge(eqs, close, lo, hi) for _, lo, hi in WINDOWS]
            good = all(e is not None and e > 0 for e in es)
            print(f"  {name:<18} IS {es[0]:+7.1f}  OOS {es[1]:+7.1f}  [{'ok' if good else 'FAIL'}]")
        else:
            e = edge(eqs, close, win[0], win[1])
            good = e is not None and e > 0
            print(f"  {name:<18} edge {e:+7.1f}  [{'ok' if good else 'FAIL'}]")
        ok += bool(good)
    a1 = ok >= 6
    print(f"A1: {ok}/8 → {'PASS' if a1 else 'FAIL'}")

    eqs, lots = run_full(close)
    bees = close["NIFTYBEES"]
    m = eqs.pct_change().dropna()
    bm = bees.reindex(eqs.index).pct_change().dropna()
    ex = (m - bm).dropna()
    print("\nStage A2 — lottery (per window):")
    a2 = True
    for wname, lo, hi in WINDOWS:
        q = ex.loc[lo:hi].groupby(ex.loc[lo:hi].index.to_period("Q")).sum()
        share = q[q > 0].max() / q[q > 0].sum() if (q > 0).any() else 1.0
        good = share < 0.40
        a2 &= good
        print(f"  {wname}: best quarter = {share:.0%} of positive excess [{'ok' if good else 'FAIL'}]")

    print("\nStage A3 — after-tax:")
    a3 = True
    for wname, lo, hi in WINDOWS:
        wl = [(a, b, r) for a, b, r in lots if str(a.date()) >= lo and (hi is None or str(b.date()) <= hi)]
        eq_at = 1.0
        for a, b, r in wl:
            tax = STCG if (b - a).days <= 365 else LTCG
            eq_at *= 1 + (r - tax * max(r, 0.0) - 2 * COST)
        bwin = bees.loc[lo:hi]
        b_pre = bwin.iloc[-1] / bwin.iloc[0]
        b_at = 1 + (b_pre - 1) * (1 - LTCG) if b_pre > 1 else b_pre
        good = eq_at > b_at
        a3 &= good
        lt = sum(1 for a, b, _ in wl if (b - a).days > 365)
        print(
            f"  {wname}: v33 after-tax {100 * (eq_at - 1):+7.1f}% vs bees "
            f"{100 * (b_at - 1):+7.1f}%  ({lt}/{len(wl)} lots LTCG) "
            f"[{'ok' if good else 'FAIL'}]"
        )

    print(
        f"\nSTAGE A VERDICT: "
        f"{
            'PASS — Stage B paper phase begins next month-end'
            if a1 and a2 and a3
            else 'FAIL — v33 downgraded to DEAD (fragile/lottery), printed'
        }"
    )


if __name__ == "__main__":
    main()

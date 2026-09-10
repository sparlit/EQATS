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


"""v4 after-tax accounting audit. Per PROTOCOL_TAX.md — Indian STCG/LTCG
applied to a lot ledger of the verbatim v4 engine run; no strategy change.

    python -m backtest.tax_audit
"""
import pandas as pd
from backtest import features, monthly
from backtest.runners import WINDOWS

STCG, LTCG = 0.20, 0.125
COST = 0.0025


def lot_ledger(p, ctx):
    """Run verbatim v4 with a recording select_fn; return (eq, bench,
    lots) where lots = [(entry_fill_date, exit_date, unit_return,
    notional_frac_of_equity)] and open positions are excluded (marked,
    untaxed — disclosed)."""
    hist = []  # formation date -> names

    def rec(t, m):
        sel = list(m.nlargest(20).index)
        hist.append((t, sel))
        return sel

    res = monthly.simulate(p, ctx, regime_filter=True, cost=COST, select_fn=rec)
    eq = res["eq"]
    open_, close = p["open"], p["close"]
    dates = close.index

    # align formations with eq rows (hist entries only for invested months)
    rows = []  # (formation, t1, names, equity)
    h = iter(hist)
    for t1, r in eq.iterrows():
        if r["n"] > 0:
            t, names = next(h)
            rows.append((t, t1, names, r["equity"]))
        else:
            rows.append((None, t1, [], r["equity"]))

    lots, live = [], {}  # sym -> (fill_date, fill_px, notional)
    for i, (t, t1, names, equity) in enumerate(rows):
        held = set(live)
        now = set(names)
        # exits: in ledger but not selected this month → sold at this
        # month's formation... engine holds them THROUGH month i-1 only;
        # they were absent from month i's portfolio, so they exit at the
        # PREVIOUS month-end close (last day they were held).
        for s in held - now:
            fd, fpx, notional = live.pop(s)
            exit_date = rows[i - 1][1]  # previous t1
            px = close.loc[:exit_date, s].dropna()
            if px.empty or fpx <= 0:
                continue
            unit = (px.iloc[-1] * (1 - COST)) / fpx - 1
            lots.append((fd, exit_date, unit, notional))
        # entries at this month's fill (next open after formation)
        if names:
            nxt = dates[dates.searchsorted(t, side="right")]
            for s in now - held:
                fpx0 = open_.loc[nxt].get(s)
                if pd.isna(fpx0) or fpx0 <= 0:
                    continue
                live[s] = (nxt, float(fpx0) * (1 + COST), equity / 20)
    return eq, res["bench"], lots


def fy(d):  # Indian fiscal year key
    return d.year if d.month >= 4 else d.year - 1


def taxes_by_fy(lots):
    st, lt = {}, {}
    for fd, xd, unit, notional in lots:
        gain = unit * notional
        pool = lt if (xd - fd).days > 365 else st
        pool[fy(xd)] = pool.get(fy(xd), 0.0) + gain
    out, cf_st, cf_lt = {}, 0.0, 0.0  # carry-forwards (<=0)
    for y in sorted(set(st) | set(lt)):
        s, l = st.get(y, 0.0) + cf_st, lt.get(y, 0.0) + cf_lt
        cf_st = cf_lt = 0.0
        if s < 0:  # STCL offsets LT too
            l += s
            s = 0.0
        if l < 0:
            cf_lt, l = l, 0.0
        if s < 0:  # (unreachable, safety)
            cf_st, s = s, 0.0
        out[y] = STCG * s + LTCG * l
    return out


def main():
    for label, start, end in WINDOWS:
        print(f"=== {label} ===")
        p = features._panel(start, end)
        ctx = features._context(p)
        eq, bench, lots = lot_ledger(p, ctx)

        tax = taxes_by_fy(lots)
        equity = eq["equity"]
        after = equity.copy()
        factor = 1.0
        for y, t_amt in sorted(tax.items()):
            fy_end = pd.Timestamp(y + 1, 3, 31)
            at = (
                equity.index[equity.index.searchsorted(fy_end)]
                if equity.index.searchsorted(fy_end) < len(equity)
                else equity.index[-1]
            )
            scaled = t_amt * factor  # ledger is pre-tax scale
            haircut = 1 - scaled / (equity.loc[at] * factor)
            factor *= haircut
            after.loc[at:] = equity.loc[at:] * factor
        yrs = len(equity) / 12
        b_pre = bench.iloc[-1] / bench.iloc[0]
        b_post = 1 + (b_pre - 1) * (1 - LTCG) if b_pre > 1 else b_pre

        def cagr(x):
            return 100 * (x ** (1 / yrs) - 1)

        s_pre, s_post = equity.iloc[-1], after.iloc[-1]
        print(f"  lots closed: {len(lots)}  ({sum(1 for f, x, _, _ in lots if (x - f).days > 365)} long-term)")
        print(f"  taxes by FY (pre-tax scale): { {y: round(v, 4) for y, v in tax.items()} }")
        print(f"  strategy pre-tax : {100 * (s_pre - 1):+7.1f}%  (CAGR {cagr(s_pre):+.1f}%)")
        print(f"  strategy AFTER-tax: {100 * (s_post - 1):+7.1f}%  (CAGR {cagr(s_post):+.1f}%)")
        print(f"  bench pre-tax    : {100 * (b_pre - 1):+7.1f}%   AFTER-tax: {100 * (b_post - 1):+7.1f}%")
        print(
            f"  EDGE pre-tax {100 * (s_pre - b_pre):+.1f}pt → "
            f"AFTER-tax {100 * (s_post - b_post):+.1f}pt   "
            f"tax drag {cagr(s_pre) - cagr(s_post):.1f}pp/yr"
        )
        print()


if __name__ == "__main__":
    main()

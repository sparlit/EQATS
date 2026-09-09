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


# -*- coding: utf-8 -*-
"""§117c — context-level read of the 6 'comparative-row' XBRLs.

NSE lists the year-ago comparative of a filing as its OWN row (PIIND '30-Jun-2018 con' shares
the Jun-2019 filing's XBRL). For companies that did not file that basis quarterly in FY19, the
comparative column of the NEXT year's filing IS the first-ever publication — there is no earlier
vintage to contaminate from. The value test is still due: read the context whose period IS the
target quarter from that same XBRL and compare with the store.

Report-only. RUN: python3 scripts/vintage117c_ctxread.py
"""
import contextlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

XC = os.path.join(HERE, "_xbrl_cache")
XSCAN = os.path.join(HERE, "_vintage117c_xscan.json")

TAGS = (
    "RevenueFromOperations",
    "ProfitLossForPeriod",
    "ProfitLossForThePeriod",
    "ProfitOrLossAttributableToOwnersOfParent",
    "OtherIncome",
    "FinanceCosts",
    "DepreciationDepletionAndAmortisationExpense",
    "ProfitBeforeExceptionalItemsAndTax",
    "ProfitBeforeTax",
    "BasicEarningsLossPerShare",
    "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
)


def contexts(xml):
    """ctxId -> (startDate, endDate) from the context definitions."""
    out = {}
    for m in re.finditer(
        r'<xbrli:context id="([^"]+)">.*?<xbrli:startDate>([\d-]+)</xbrli:startDate>'
        r"\s*<xbrli:endDate>([\d-]+)</xbrli:endDate>",
        xml,
        re.DOTALL,
    ):
        out[m.group(1)] = (m.group(2), m.group(3))
    if not out:
        for m in re.finditer(
            r'<context id="([^"]+)">.*?<startDate>([\d-]+)</startDate>'
            r"\s*<endDate>([\d-]+)</endDate>",
            xml,
            re.DOTALL,
        ):
            out[m.group(1)] = (m.group(2), m.group(3))
    return out


def facts(xml, tag):
    out = {}
    for m in re.finditer(rf'<in-(?:bse-fin|capmkt):{tag} contextRef="([^"]+)"[^>]*>([^<]+)<', xml):
        with contextlib.suppress(ValueError):
            out[m.group(1)] = float(m.group(2))
    return out


def main():
    xs = json.load(open(XSCAN, encoding="utf-8"))
    for k, v in sorted(xs.items()):
        if v.get("verdict") != "FLAG":
            continue
        sym, qe, _basis = v["sym"], v["qe"], v["basis"]
        seq = (v.get("xbrl") or {}).get("seq")
        fl = (v.get("filings") or [{}])[0]
        print("== {} (earliest filed {}, n_rows={})".format(k, fl.get("filed"), v.get("n_rows")))
        lp = os.path.join(HERE, "_nsearch_cache", "list_{}.json".format(re.sub(r"[^A-Z0-9]", "_", sym)))
        rows = json.load(open(lp, encoding="utf-8"))
        row = next((r for r in rows if str(r.get("seqNumber")) == str(seq)), None)
        if not row or not row.get("xbrl"):
            print(f"   (list row/seq {seq} not found)")
            continue
        fn = re.sub(r"[^A-Za-z0-9_.]", "_", row["xbrl"].rsplit("/", 1)[-1])
        p = os.path.join(XC, fn)
        if not os.path.exists(p):
            print(f"   (xbrl {fn} not cached)")
            continue
        xml = open(p, encoding="utf8", errors="replace").read()
        qiso = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        ctx = contexts(xml)
        q_ctx = [c for c, (s, e) in ctx.items() if e == qiso and 85 <= _days(s, e) <= 95]
        print("   file %s: %d contexts, quarter-contexts %s" % (fn, len(ctx), q_ctx))
        for tag in TAGS:
            fv = facts(xml, tag)
            got = {c: fv[c] for c in q_ctx if c in fv}
            if got:
                print("     %-55s %s" % (tag, {c: round(x / 1e7, 2) for c, x in got.items()}))
        print("   stored: rev {} op {} pat {}".format(v.get("live_rev"), v.get("live_op"), v.get("live_pat")))


def _days(s, e):
    from datetime import date

    ys, ms, ds = map(int, s.split("-"))
    ye, me, de = map(int, e.split("-"))
    return (date(ye, me, de) - date(ys, ms, ds)).days


if __name__ == "__main__":
    main()

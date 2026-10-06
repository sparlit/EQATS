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
"""BSE SME IPO "Every member, ever" table → docs/survivorship/bsesmeipo.json  (runbook §195).

Same file shape and column meanings as scripts/build_index_survivorship.py (index-chart.html renders it unchanged),
built from:
  membership  docs/bse_sme_ipo/stints.json  (scripts/build_bse_sme_ipo_pit.py — notices + Excel lists + rule)
  prices      BSE daily bhavcopies via build_bse_sme_backfill.build_series(codes) — every bar of every member, any
              group (so a scrip's life after it migrated to the main board is priced too). Closes are the ISIN-split-
              adjusted `c`; a one-day fall >30 % with no ISIN change (bonus OR crash, undecidable from prices, §161) is NOT
              adjusted — such rows carry the day in `note` and their returns across it are understated.
  index level docs/bse_sme_ipo.json px (BSE's official closes)
sym = the BSE scrip id (stock.html?sym=<id> serves BSE-only names from their slices). status: in (member on dataEnd) /
out (left, still trading within 30 days of dataEnd) / dead (left, no trade in the last 30 days) / untraced (no series).
Run: python3 scripts/build_bse_sme_ipo_survivorship.py            (prices from scripts/bse_sme_ipo_px.json.gz — CI)
     BSE_BHAV_CACHE=~/stocks-cache/bse_bhav python3 scripts/build_bse_sme_ipo_survivorship.py --cache
"""
import bisect
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_bse_sme_backfill as BB

ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "survivorship", "bsesmeipo.json")
MAX_GAP = 45
COLS = [
    "sym",
    "name",
    "sector",
    "industry",
    "isin",
    "mcap",
    "status",
    "first",
    "fromStart",
    "last",
    "n",
    "days",
    "joinPx",
    "exitPx",
    "lastPx",
    "lastD",
    "retIn",
    "cagrIn",
    "retSince",
    "retAfter",
    "idxIn",
    "relIn",
    "maxDD",
    "upcoming",
    "st",
    "note",
]


def I(iso):
    return int(iso.replace("-", ""))


def S(i):
    s = str(i)
    return s[:4] + "-" + s[4:6] + "-" + s[6:]


def dd(a, b):
    return (datetime.date.fromisoformat(S(b)) - datetime.date.fromisoformat(S(a))).days


def rnd(x, n=2):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x, n)


def main():
    stj = json.load(open(os.path.join(DOCS, "bse_sme_ipo", "stints.json")))
    START = "2020-01-01"  # user scope: data from 1-Jan-2020 (history before it is out of scope)
    stints = [dict(s, join=max(s["join"], START)) for s in stj["stints"] if s["join"]]
    pre = {s["code"] for s in stj["stints"] if s["join"] and s["join"] < START}
    hist = json.load(open(os.path.join(DOCS, "bse_sme_ipo", "history.json")))["BSE SME IPO"]
    lvl = json.load(open(os.path.join(DOCS, "bse_sme_ipo.json")))["px"]
    ld = sorted(I(k) for k in lvl)
    lv = [lvl[S(k)] for k in ld]
    uni = {str(r[0]): r for r in json.load(open(os.path.join(DOCS, "bse_universe.json")))["rows"]}
    codes = {s["code"] for s in stints}
    if "--cache" in sys.argv:  # local: straight from ~/stocks-cache/bse_bhav
        ser, _, _ = BB.build_series(codes)
    else:  # default (CI): the repo's price ledger, refreshed nightly
        import bse_sme_ipo_px as PX

        ser, _ = PX.series(codes)
    data_end = max(max(s["d"]) for s in ser.values())

    def at_or_after(s, k):
        i = bisect.bisect_left(s["d"], k)
        return (
            (s["d"][i], s["c"][i])
            if i < len(s["d"]) and dd(k, s["d"][i]) <= MAX_GAP
            else (None, None)
        )

    def before(s, k):
        i = bisect.bisect_left(s["d"], k) - 1
        return (s["d"][i], s["c"][i]) if i >= 0 and dd(s["d"][i], k) <= MAX_GAP else (None, None)

    def idx_at(k, after=True):
        i = bisect.bisect_left(ld, k) if after else bisect.bisect_left(ld, k) - 1
        if 0 <= i < len(ld) and abs(dd(k, ld[i])) <= MAX_GAP:
            return lv[i]
        return None

    rows = []
    by = {}
    for s in stints:
        by.setdefault(s["code"], []).append(s)
    for code, sts in sorted(by.items()):
        sts.sort(key=lambda x: x["join"])
        s = ser.get(code)
        u = uni.get(code)
        meta = sts[-1]
        sym = meta["id"] or code
        first = sts[0]["join"]
        last_open = sts[-1]["leave"] is None
        last = None if last_open else sts[-1]["leave"]
        days = sum(dd(I(x["join"]), I(x["leave"]) if x["leave"] else data_end) for x in sts)
        if not s:
            rows.append(
                [
                    sym,
                    meta["name"],
                    None,
                    None,
                    meta["isin"],
                    None,
                    "untraced",
                    first,
                    code in pre,
                    last,
                    len(sts),
                    days,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    [[x["join"], x["leave"], None, None, None] for x in sts],
                    "no BSE bhavcopy series",
                ]
            )
            continue
        st_out = []
        comp = 1.0
        icomp = 1.0
        ok = True
        iok = True
        mdd = 0.0
        for x in sts:
            j = I(x["join"])
            l = I(x["leave"]) if x["leave"] else None
            jd, jp = at_or_after(s, j)
            if l:
                ed, ep = before(s, l)
            else:
                _ed, ep = s["d"][-1], s["c"][-1]
            r = (ep / jp - 1) if (jp and ep) else None
            st_out.append(
                [
                    x["join"],
                    x["leave"],
                    rnd(jp),
                    rnd(ep) if l else None,
                    rnd(r * 100, 1) if r is not None else None,
                ]
            )
            if r is None:
                ok = False
            else:
                comp *= 1 + r
            i0 = idx_at(j)
            i1 = idx_at(l, after=False) if l else lv[-1]
            if i0 and i1:
                icomp *= i1 / i0
            else:
                iok = False
            # max drawdown on closes while a member
            peak = None
            for d_, c_ in zip(s["d"], s["c"], strict=False):
                if d_ < j or (l and d_ >= l):
                    continue
                peak = c_ if peak is None or c_ > peak else peak
                mdd = min(mdd, c_ / peak - 1)
        ret_in = comp - 1 if ok else None
        cagr = (
            ((1 + ret_in) ** (365.0 / days) - 1)
            if (ret_in is not None and days >= 365 and ret_in > -1)
            else None
        )
        jp0 = st_out[0][2]
        lastD, lastPx = s["d"][-1], s["c"][-1]
        exitPx = st_out[-1][3]
        status = "in" if last_open else ("dead" if dd(lastD, data_end) > 30 else "out")
        idx_in = icomp - 1 if iok else None
        rel = (
            ((1 + ret_in) / (1 + idx_in) - 1)
            if (ret_in is not None and idx_in is not None)
            else None
        )
        note = ""
        une = [
            S(a) for a, _ in s.get("unexpl", []) if I(first) <= a and (last is None or a < I(last))
        ]
        if une:
            note = "one-day fall >30% on {} (bonus or crash, unconfirmed) — returns across it understated".format(
                ", ".join(une[:3])
            )
        rows.append(
            [
                sym,
                meta["name"],
                None,
                (u[7] if u and len(u) > 7 else None),  # bse_universe carries industry only
                meta["isin"],
                (rnd(u[6], 1) if u else None),
                status,
                first,
                code in pre,
                last,
                len(sts),
                days,
                jp0,
                exitPx,
                rnd(lastPx),
                S(lastD),
                rnd(ret_in * 100 if ret_in is not None else None, 1),
                rnd(cagr * 100 if cagr is not None else None, 1),
                rnd((lastPx / jp0 - 1) * 100 if jp0 else None, 1),
                rnd((lastPx / exitPx - 1) * 100 if exitPx else None, 1) if not last_open else None,
                rnd(idx_in * 100 if idx_in is not None else None, 1),
                rnd(rel * 100 if rel is not None else None, 1),
                rnd(mdd * 100, 1),
                None,
                st_out,
                note,
            ]
        )
    n = {k: sum(1 for r in rows if r[6] == k) for k in ("in", "out", "dead", "untraced")}
    doc = {
        "index": "BSE SME IPO",
        "slug": "bsesmeipo",
        "updated": datetime.date.today().isoformat(),
        "dataEnd": S(data_end),
        "snaps": len(hist),
        "firstSnap": hist[0]["effectiveDate"],
        "lastSnap": hist[-1]["effectiveDate"],
        "rosterAsOf": json.load(open(os.path.join(DOCS, "bse_sme_ipo", "members.json")))["asof"],
        "upcoming": None,
        "nIn": n["in"],
        "nOut": n["out"],
        "nDead": n["dead"],
        "nUntraced": n["untraced"],
        "idxSeries": f"bse_sme_ipo.json official BSE closes {S(ld[0])}..{S(ld[-1])}",
        "source": "membership: BSE Index Services notices 2012-2026 + archived quarterly Excel lists + BSE methodology rule "
        "(scripts/build_bse_sme_ipo_pit.py); prices: BSE daily bhavcopies",
        "memberNote": "Membership: BSE Index Services' own notices (every addition and monthly drop since the Dec-2012 launch), "
        "the archived quarterly Excel lists, and BSE's methodology rule where a notice names no stock (2nd listing day in; "
        "out after 1 year, or on migration to the main board). Checked against BSE's official list and its daily "
        "index turnover. Record starts 1 Jan 2020 (\u201c\u2264\u201d = already a member then).",
        "cols": COLS,
        "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    print(
        "survivorship: %d rows (in %d, out %d, dead %d, untraced %d) data to %s → %s (%d bytes)"
        % (
            len(rows),
            n["in"],
            n["out"],
            n["dead"],
            n["untraced"],
            S(data_end),
            OUT,
            os.path.getsize(OUT),
        )
    )


if __name__ == "__main__":
    main()

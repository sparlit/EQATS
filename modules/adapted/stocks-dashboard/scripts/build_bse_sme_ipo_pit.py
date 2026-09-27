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
"""BSE SME IPO — point-in-time membership 2012→ (every stint of every stock that was ever in the index)  (runbook §195).

SOURCES, in order of authority (every stint records which one decided each end):
  1. BSE Index Services notices  (scripts/parse_bse_sme_ipo_notices.py over ~/stocks-cache/bse_index_notices)
  2. BSE's quarterly Excel drop lists, archived  (scripts/bse_sme_ipo_excel_drops.json)
  3. BSE daily bhavcopies (~/stocks-cache/bse_bhav via build_bse_sme_backfill.build_series): the day a scrip first
     trades in an SME group (listing) and the day it stops (migration to the main board)
  4. the methodology rule (BSE Indices Methodology Sept-2026 p.60 + the 19-Dec-2016 change): join at the open of the
     2nd listing day; leave at the open of the Monday after the 3rd Friday of the first month whose 3rd Friday is on or
     after the anniversary (+1 day) — 3 years before 19-Dec-2016, 1 year after (on 19-Dec-2016 everything past a year
     left). Measured on 2022-11→2025-02: 92/98 notice drops, every archived Excel list and 7/9 count-only months exact.
JOINS without a notice are taken only for the launch composition (SME scrips listed before the 14-Dec-2012 launch) or
when a notice DROPS the scrip later (so it was a member) — an old scrip re-entering the SME groups after a suspension is
never added by rule (measured: ENCASH/CNEL/EFPL/BHANDERI re-entered 2023, no notice, not members).

OUTPUT  docs/bse_sme_ipo/stints.json   {built, sources, stints:[{code,id,isin,name,join,leave,join_src,leave_src,note}]}
        docs/bse_sme_ipo/history.json  {"BSE SME IPO": [{effectiveDate, symbols:[<ID>.BO …]}]}  (indices_history shape)
        docs/bse_sme_ipo/validation.json  the self-checks below
CHECKS  (a) the roster in force on BSE's latest list date == BSE's official list (members.json), code for code
        (b) Σ turnover of the rebuilt members per day vs BSE's official index turnover (docs/bse_sme_ipo.json "to")
Run:    BSE_BHAV_CACHE=~/stocks-cache/bse_bhav python3 scripts/build_bse_sme_ipo_pit.py
"""
import bisect
import collections
import datetime
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_bse_sme_backfill as BB
import parse_bse_sme_ipo_notices as PN

ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
OUTD = os.path.join(DOCS, "bse_sme_ipo")
MASTER = os.path.expanduser("~/stocks-cache/bse_scrip_master.json")
EXCEL = os.path.join(HERE, "bse_sme_ipo_excel_drops.json")
LAUNCH = datetime.date(2012, 12, 14)
BASE = datetime.date(2012, 8, 16)
ONE_YEAR_FROM = datetime.date(2016, 12, 19)  # methodology change 12/19/2016: 3 years -> 1 year
START = datetime.date(2020, 1, 1)  # user scope (2026-09-27): "take data only from January 1, 2020"


def D(k):
    return datetime.date(k // 10000, k // 100 % 100, k % 100)


def K(d):
    return int(d.strftime("%Y%m%d"))


def third_friday(y, m):
    d = datetime.date(y, m, 15)
    while d.weekday() != 4:
        d += datetime.timedelta(1)
    return d


def add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def rebalance_after(a):
    """first Monday-after-3rd-Friday whose 3rd Friday >= a - 1 day (the anniversary may fall on that Saturday)."""
    y, m = a.year, a.month
    while True:
        f = third_friday(y, m)
        if a <= f + datetime.timedelta(1):
            return f + datetime.timedelta(3)
        y, m = (y + (m == 12), m % 12 + 1)


def rule_exit(listing):
    x3 = rebalance_after(add_years(listing, 3))
    if x3 < ONE_YEAR_FROM:
        return x3, "rule-3y"
    return max(ONE_YEAR_FROM, rebalance_after(add_years(listing, 1))), "rule-1y"


def main():
    # ---- bhavcopy series: every scrip ever in an SME group
    ser, ndays, _dropped = BB.build_series()
    cal = sorted({d for s in ser.values() for d in s["d"]})

    def on_or_after(d):
        if K(d) < cal[0]:
            return K(d)  # before the bhavcopy cache: keep the calendar date itself
        i = bisect.bisect_left(cal, K(d))
        return cal[i] if i < len(cal) else None

    def nxt(k):
        return cal[bisect.bisect_right(cal, k)] if bisect.bisect_right(cal, k) < len(cal) else None

    first_day = cal[0]
    # ---- notices
    L = {r["notice_no"]: r for r in json.load(open(os.path.join(PN.CACHE, "list.json")))["all"]}
    events, unparsed = [], []
    for f in sorted(os.listdir(PN.CACHE)):
        if not f.endswith(".pdf"):
            continue
        no = f[:-4]
        r = L.get(no) or {}
        t = PN.text_of(no)
        import re

        if not PN.SME_NAME.search(t) and not re.search(r"(?i)SME\s+platform", t):
            continue
        ev, flags = PN.parse(no, t, r.get("Subject") or "")
        tab = {c: e for a, c, e in ev if a == "add"}
        for c, e in PN.narrative_adds(t):
            if c not in tab:
                ev.append(("add", c, e))
            elif tab[c] != e:
                ev = [x for x in ev if not (x[0] == "add" and x[1] == c)] + [("add", c, e)]
        tabd = {c for a, c, e in ev if a == "drop"}
        for c, e in PN.narrative_drops(t):
            if c not in tabd:
                ev.append(("drop", c, e))
        for a, c, e in ev:
            if e:
                events.append({"code": c, "action": a, "eff": e, "src": "notice " + no})
        unparsed += [
            {"notice": no, "why": fl} for fl in flags if not fl.startswith(("narrative-only", "table/narrative"))
        ]
    # ---- Excel drops
    for eff, blk in json.load(open(EXCEL))["drops"].items():
        for c in blk["codes"]:
            events.append({"code": c, "action": "drop", "eff": eff, "src": "excel " + blk["src"].split(" ")[0]})
    # de-duplicate (same code/action/date from two notices)
    seen = set()
    ev2 = []
    for e in sorted(events, key=lambda e: (e["code"], e["eff"], e["action"])):
        k = (e["code"], e["action"], e["eff"])
        if k not in seen:
            seen.add(k)
            ev2.append(e)
    events = ev2
    by = collections.defaultdict(list)
    for e in events:
        by[e["code"]].append(e)
    # ---- master (code -> id / isin / name / status)
    M = {r["SCRIP_CD"]: r for r in json.load(open(MASTER))["rows"]}

    stints = []
    launch_members = [
        c
        for c, s in ser.items()
        if (c.startswith("5") and s["first_sme"] and s["first_sme"] <= K(LAUNCH) and s["d"][0] == s["first_sme"])
        or (c.startswith("5") and s["first_sme"] == first_day)
    ]
    codes = set(by) | {
        c for c in launch_members if c in ser and ser[c]["first_sme"] and ser[c]["first_sme"] <= K(LAUNCH)
    }
    for c in sorted(codes):
        s = ser.get(c)
        evs = sorted(by.get(c, []), key=lambda e: (e["eff"], 0 if e["action"] == "drop" else 1))
        listing = D(s["first_sme"]) if s and s["first_sme"] else None
        adds = [e for e in evs if e["action"] == "add"]
        if adds and (listing is None or datetime.date.fromisoformat(adds[0]["eff"]) < listing):
            # the first bar on file is AFTER BSE already added it: the scrip listed before the bhavcopy cache starts
            # (an illiquid SME scrip's first 2020 trade can be weeks in — ALSL, added Aug-2013, first 2020 bar 20-Jan)
            # listed before the cache starts (or no SME series at all): the ADD notice dates the listing — the index
            # adds on the 2nd listing day, so listing = the trading day before the add (calendar day before, pre-cache)
            listing = datetime.date.fromisoformat(adds[0]["eff"]) - datetime.timedelta(1)
        cur = None

        def open_stint(day, src):
            return {"join": day, "join_src": src, "leave": None, "leave_src": None}

        runs = []
        for e in evs:
            d = on_or_after(datetime.date.fromisoformat(e["eff"]))
            if d is None:
                d = K(datetime.date.fromisoformat(e["eff"]))
            if e["action"] == "add":
                if cur is None:
                    cur = open_stint(d, e["src"])
                # a second add while open = a re-announcement: keep the first
            else:
                if cur is None:  # drop with no add seen -> joined by rule
                    if listing:
                        j = nxt(K(listing)) if listing > BASE else K(BASE)
                        j = max(j, K(BASE))
                        cur = open_stint(j, "rule-listing+1" if listing > BASE else "base-2012-08-16")
                    else:
                        runs.append({"join": None, "join_src": "unknown", "leave": d, "leave_src": e["src"]})
                        continue
                cur["leave"] = d
                cur["leave_src"] = e["src"]
                runs.append(cur)
                cur = None
        if cur is None and not runs and listing:  # launch member with no events at all
            j = K(BASE) if listing <= BASE else nxt(K(listing))
            cur = open_stint(j, "base-2012-08-16" if listing <= BASE else "launch-listing+1")
        if cur is not None:  # still open: migration, else the rule, else in the index today
            leave = leave_src = None
            if s and s["last_sme"] and s["d"][-1] > s["last_sme"] and s["last_sme"] >= cur["join"]:
                leave, leave_src = nxt(s["last_sme"]), "migration (bhavcopy group left SME)"
            if listing:
                rx, rsrc = rule_exit(listing)
                rk = on_or_after(rx) or K(rx)
                if leave is None or rk < leave:
                    if rk <= cal[-1]:
                        leave, leave_src = rk, rsrc
            cur["leave"], cur["leave_src"] = leave, leave_src
            runs.append(cur)
        m = M.get(c, {})
        for r in runs:
            stints.append(
                {
                    "code": c,
                    "id": m.get("scrip_id") or (s or {}).get("tk"),
                    "isin": m.get("ISIN_NUMBER") or (s or {}).get("isin"),
                    "name": m.get("Scrip_Name") or (s or {}).get("tk"),
                    "status": m.get("Status"),
                    "listing": listing.isoformat() if listing else None,
                    "join": r["join"],
                    "leave": r["leave"],
                    "join_src": r["join_src"],
                    "leave_src": r["leave_src"],
                }
            )

    def iso(k):
        return None if k is None else "%d-%02d-%02d" % (k // 10000, k // 100 % 100, k % 100)

    # BSE's captured official lists outrank the rule: a scrip on the latest official list is a member on that date, so a
    # rule exit on/before it is reopened (L.T. Elevator 544518: anniversary Sat 19-Sep-2026, the rule said 21-Sep, BSE's
    # 28-Sep list still carries it — the Saturday-anniversary case splits 2/2 in BSE's own notices)
    offm0 = json.load(open(os.path.join(OUTD, "members.json")))
    asof0 = K(datetime.date.fromisoformat(offm0["asof"]))
    on_list = {m["code"] for m in offm0["members"]}
    for x in stints:
        if (
            x["code"] in on_list
            and x["leave"]
            and x["leave"] <= asof0
            and (x["leave_src"] or "").startswith("rule")
            and x["join"]
            and x["join"] <= asof0
            and x is max((y for y in stints if y["code"] == x["code"]), key=lambda y: y["join"])
        ):
            x["leave"], x["leave_src"] = (
                None,
                "open (on BSE's official list {}; rule exit {} overruled)".format(offm0["asof"], x["leave"]),
            )
    n_before = len(stints)
    stints = [x for x in stints if x["leave"] is None or x["leave"] > K(START)]
    for x in stints:
        x["from_start"] = bool(x["join"] and x["join"] <= K(START))
    print("scope %s→: %d stints kept, %d ended before" % (START, len(stints), n_before - len(stints)))
    # ---- snapshots on every change date
    change = sorted(
        {max(x["join"], K(START)) for x in stints if x["join"]} | {x["leave"] for x in stints if x["leave"]}
    )
    snaps = []
    for d in change:
        mem = sorted(
            x["id"] + ".BO"
            for x in stints
            if x["join"] and x["join"] <= d and (x["leave"] is None or d < x["leave"]) and x["id"]
        )
        snaps.append({"effectiveDate": iso(d), "symbols": mem})
    # ---- checks
    off = json.load(open(os.path.join(DOCS, "bse_sme_ipo.json")))
    offm = json.load(open(os.path.join(OUTD, "members.json")))
    asof = K(datetime.date.fromisoformat(offm["asof"]))
    ours = {x["code"] for x in stints if x["join"] and x["join"] <= asof and (x["leave"] is None or asof < x["leave"])}
    theirs = {m["code"] for m in offm["members"]}
    chk_a = {
        "asof": offm["asof"],
        "official": len(theirs),
        "rebuilt": len(ours),
        "missing": sorted(theirs - ours),
        "extra": sorted(ours - theirs),
    }
    vol = {c: dict(zip(s["d"], s["v"], strict=False)) for c, s in ser.items()}
    rc = {c: dict(zip(s["d"], s["rc"], strict=False)) for c, s in ser.items()}
    ratios = {}
    for d in cal:
        o = off.get("to", {}).get(iso(d))
        if not o:
            continue
        tot = sum(
            vol.get(x["code"], {}).get(d, 0) * rc.get(x["code"], {}).get(d, 0)
            for x in stints
            if x["join"] and x["join"] <= d and (x["leave"] is None or d < x["leave"])
        )
        ratios[iso(d)] = round(tot / 1e7 / o, 4)
    by_year = collections.defaultdict(list)
    for d, r in ratios.items():
        by_year[d[:4]].append(r)
    chk_b = {
        y: {
            "days": len(v),
            "median": statistics.median(v),
            "p10": sorted(v)[len(v) // 10],
            "p90": sorted(v)[len(v) * 9 // 10],
            "within_2pct": round(sum(abs(x - 1) <= 0.02 for x in v) / len(v), 3),
        }
        for y, v in sorted(by_year.items())
    }
    bad_days = sorted(((d, r) for d, r in ratios.items() if abs(r - 1) > 0.10), key=lambda z: z[0])
    srcs = collections.Counter((x["join_src"].split(" ")[0], (x["leave_src"] or "open").split(" ")[0]) for x in stints)
    os.makedirs(OUTD, exist_ok=True)
    out_st = [{**x, "join": iso(x["join"]), "leave": iso(x["leave"])} for x in stints]
    built = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(
        {"built": built, "bhav_days": ndays, "bhav_first": iso(cal[0]), "bhav_last": iso(cal[-1]), "stints": out_st},
        open(os.path.join(OUTD, "stints.json"), "w"),
        indent=0,
        ensure_ascii=False,
    )
    json.dump({"BSE SME IPO": snaps}, open(os.path.join(OUTD, "history.json"), "w"), separators=(",", ":"))
    json.dump(
        {
            "built": built,
            "roster_vs_official": chk_a,
            "turnover_ratio_by_year": chk_b,
            "turnover_off_by_10pct_days": bad_days[:400],
            "sources": {"{}|{}".format(*k): v for k, v in srcs.items()},
            "unparsed_notice_rows": unparsed,
        },
        open(os.path.join(OUTD, "validation.json"), "w"),
        indent=1,
    )
    print(
        "stints %d (%d scrips), snapshots %d, sources %s"
        % (len(stints), len({x["code"] for x in stints}), len(snaps), dict(srcs))
    )
    print(
        "(a) roster on %s: official %d, rebuilt %d, missing %s, extra %s"
        % (chk_a["asof"], chk_a["official"], chk_a["rebuilt"], chk_a["missing"][:10], chk_a["extra"][:10])
    )
    for y, v in chk_b.items():
        print(
            "(b) %s turnover ratio median %.3f  p10 %.3f  p90 %.3f  within±2%% %.0f%%  (%d days)"
            % (y, v["median"], v["p10"], v["p90"], v["within_2pct"] * 100, v["days"])
        )
    print("days off by >10%%: %d" % len(bad_days))


if __name__ == "__main__":
    main()

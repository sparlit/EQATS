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
"""ISSUER-PREFIX SWEEP — every place the FULL-ISIN auto-merge left ONE company as TWO bin keys.

`build_sf_data.py` merges renamed tickers by comparing the **full** ISIN, so a rename that
coincided with a FACE-VALUE change mints a new security series under the same issuer
(INE294A010**11** -> INE294A010**37**) and the same company ends up as two separate keys in
sf_stock_data.bin — truncating every lookback window and stranding the old history
(DATA_RUNBOOK 93d; BILT->BALLARPUR and SUNCLAYTON->TVSHLTD were fixed by hand there).

`INE` + 3 alphanumerics + 1 alpha identifies the LEGAL ENTITY; the trailing digits are the
security series. So group the bin's keys by `isin[:7]`: every issuer holding more than one key
is a candidate. A candidate is NOT automatically a defect —

  (a) SEQUENTIAL — the keys' bar ranges do NOT overlap and hand off within weeks.  That is the
      rename shape, i.e. the defect.
  (b) OVERLAP — partly-paid shares, DVRs and genuine simultaneous re-issues are *separate
      instruments of the same issuer* trading at the same time.  Merging them would fuse two
      real tapes.  One company cannot trade under two NSE symbols at once (93b), so an overlap
      is decisive evidence AGAINST a rename.

⚠️ THE SWEEP IS ONLY AS WIDE AS ITS ISIN COVERAGE, and the bin's own coverage FAILS on exactly
the two pairs that motivated the hunt: NSE's bhavcopy has carried an ISIN column only since 2011
(measured below), so BILT (last bar 2008-02-28) has none, and a merged key whose survivor was a
day-1 stub lost it too (TVSHLTD carries none). Grouping on bin meta alone re-finds NEITHER known
pair — recall 0/2. So ISINs are enriched from NSE's own dated security lists, under rules that
keep a re-issued symbol (89) from mis-attributing one:

    bin            meta ISIN from the bhavcopy — the company's own row, always safe
    equity_l_live  today's EQUITY_L, applied ONLY to a key still trading at the file's end date
    equity_l_wb_*  a Wayback EQUITY_L capture, applied ONLY to a key whose OWN BARS straddle the
                   capture date, so the symbol provably belonged to that company that day

Nothing here is proof of identity by itself: the grouping is a SCREEN. Every hit still has to be
corroborated against NSE's own dated files (symbolchange.csv, EQUITY_L, and the bhavcopy
PREVCLOSE handoff — a CONFIRMATION test only, its false-positive rate makes it useless for
discovery, 93c).

Run:  python3 scripts/isin_issuer_sweep.py     # needs scripts/_live/ staged (7.0/7.1b) and
                                               # scripts/isin_sources_fetch.py run
Writes scripts/_isin_issuer_sweep.json.
"""
import collections
import csv
import datetime
import glob
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.path.join(HERE, "_live")
OUT = os.path.join(HERE, "_isin_issuer_sweep.json")

# A handoff "within weeks" — BILT->BALLARPUR was 32 days (last bar 2008-02-28 -> first bar
# 2008-03-31), SUNCLAYTON->TVSHLTD 47.  Kept generous and REPORTED rather than used as a filter:
# a long gap is a suspension/relisting, still worth adjudicating by hand.
NEAR_DAYS = 120
# How stale a key's last bar may be and still count as "trading now" for the live-EQUITY_L fill.
LIVE_SLACK_DAYS = 30
# A dead key does not always END where its tape ends. Keys like TATAMOTORS and AGCNET pick up
# isolated bars scattered over the following 13 years, on the SAME dates across unrelated symbols
# (2012-01-07, 2015-02-28, 2020-11-14, 2025-02-01 ...) — every one a Saturday or Sunday.
# ⚠️ Those bars are REAL, not junk: NSE's budget Saturdays, muhurat Sundays and DR-drill Saturdays
# are full sessions, and the 2015-02-28 file (read this session, 1,534 rows) has TATAMOTORS at
# 593.35 on 4.1 m shares and AGCNET at 100.20 on 2,772. What is wrong is WHERE they are filed:
# the weekday bars of those symbols were merged into the successor key while the weekend backfill
# landed under the ERA symbol, so 66 of these sessions sit on a dead key and are MISSING from the
# live one (measured below in isin_seam_measure). That is a separate defect; here they matter only
# because they make a key's raw [first,last] span a decade it never traded, which would fake a
# co-trading overlap with its own successor. So classify on the key's REAL segments: split the
# tape wherever consecutive bars are more than SEG_GAP days apart and keep the segments big enough
# to be a listing. The rest are counted and reported, never silently dropped.
SEG_GAP = 200
# A segment this small over a multi-month span is a run of special sessions, not a listing.
# Measured on the live bin: every stray run is 1-5 bars (TATAMOTORS' ten post-2004 segments are
# 5,2,4,3,1,1,2,1,4,1) while every real segment seen in this sweep is 133 bars or more.
MIN_SEG = 15
# Real co-trading instruments (a DVR beside its ordinary share) share hundreds of sessions.
# One or two shared days would be a stray-session coincidence, so require a real count.
COTRADE_MIN = 5


def ymd_to_date(n):
    s = str(int(n))
    return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def real_segments(d):
    """-> [(first, last, bars)] of the key's real trading life, minus special-session strays.

    Split the tape wherever consecutive bars are more than SEG_GAP days apart, then keep the
    segments with at least MIN_SEG bars. Keeping only the LARGEST segment was wrong: NAGREEKA
    trades 1996-2002 (323 weekly bars) and again 2005-2007 (310 daily bars) with a real 4-year
    hole between, and taking the larger one put its seam 1,977 days from its successor instead of
    the true 89. So the key's life runs from the FIRST real segment's start to the LAST one's
    end, and a multi-year hole inside it stays visible as its own segment."""
    segs, start = [], 0
    for i in range(1, len(d)):
        if (ymd_to_date(d[i]) - ymd_to_date(d[i - 1])).days > SEG_GAP:
            segs.append((start, i))
            start = i
    segs.append((start, len(d)))
    real = [(a, b) for a, b in segs if b - a >= MIN_SEG]
    if not real:  # a genuinely short listing — keep what there is
        real = segs
    return [(d[a], d[b - 1], b - a) for a, b in real]


def read_equity_l(path):
    """-> {SYMBOL: ISIN} from an NSE security list.

    The column NAMES changed: today's file says `ISIN NUMBER`, the 2006 capture says
    `SEC_ISIN_CD` and puts it in a different position. Match on CONTAINS, never on a fixed
    index — a prefix test silently read zero ISINs out of the 2006 file."""
    out = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        rd = csv.reader(fh)
        hdr = [h.strip().upper() for h in next(rd)]
        try:
            iS = hdr.index("SYMBOL")
            iI = next(i for i, h in enumerate(hdr) if "ISIN" in h)
        except (ValueError, StopIteration):
            return out
        for r in rd:
            if len(r) > max(iS, iI) and r[iI].strip().startswith("INE"):
                out[r[iS].strip().upper()] = r[iI].strip()
    return out


def build_isin(data, meta, sf_end):
    """-> ({key: isin}, {key: source}, coverage report). Every fill is date-scoped, see module doc."""
    isin, src = {}, {}
    for k in data:
        v = (meta.get(k) or {}).get("isin") or ""
        if v.startswith("INE"):
            isin[k], src[k] = v, "bin"

    end = datetime.date.fromisoformat(sf_end)
    live_p = os.path.join(LIVE, "equity_l_live.csv")
    filled = collections.Counter()
    if os.path.exists(live_p):
        eq = read_equity_l(live_p)
        for k in data:
            if k in isin or k not in eq:
                continue
            # only a key still trading at the file's own date can be today's owner of the symbol
            if (end - ymd_to_date(data[k]["d"][-1])).days <= LIVE_SLACK_DAYS:
                isin[k], src[k] = eq[k], "equity_l_live"
                filled["equity_l_live"] += 1

    for p in sorted(glob.glob(os.path.join(LIVE, "equity_l_wb_*.csv")), reverse=True):
        tag = os.path.basename(p)[:-4]
        cap = int(tag.split("_")[-1])
        eq = read_equity_l(p)
        for k in data:
            if k in isin or k not in eq:
                continue
            d = data[k]["d"]
            if d[0] <= cap <= d[-1]:  # the symbol was THIS company's on the capture date
                isin[k], src[k] = eq[k], tag
                filled[tag] += 1
    return isin, src, filled


def main():
    p1 = os.path.join(LIVE, "p1_new.bin")
    if not os.path.exists(p1):
        sys.exit("stage the live bin first: python3 scripts/gridmega_fetch_live.py")
    D = json.loads(gzip.decompress(open(p1, "rb").read()))
    data, meta, sf_end = D["data"], D["meta"], D["end"]

    isin, src, _filled = build_isin(data, meta, sf_end)
    missing = sorted(set(data) - set(isin))

    issuer = collections.defaultdict(list)
    for k, v in isin.items():
        issuer[v[:7]].append(k)

    groups = []
    for pre, keys in sorted(issuer.items()):
        if len(keys) < 2:
            continue
        recs = []
        for k in sorted(keys):
            m = meta.get(k) or {}
            d = data[k]["d"]
            segs = real_segments(d)
            n = sum(s[2] for s in segs)
            recs.append(
                {
                    "key": k,
                    "isin": isin[k],
                    "isinSrc": src[k],
                    "name": m.get("name"),
                    "ind": m.get("ind"),
                    "alive": bool(m.get("alive")),
                    "bars": len(d),
                    "rawFirst": d[0],
                    "rawLast": d[-1],
                    "first": segs[0][0],
                    "last": segs[-1][1],
                    "segments": segs,
                    "mainBars": n,
                    "strayBars": len(d) - n,
                }
            )
        recs.sort(key=lambda r: (r["first"], r["last"]))

        def live_days(r):
            return {x for s in r["segments"] for x in data[r["key"]]["d"] if s[0] <= x <= s[1]}

        overlaps = []
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i], recs[j]
                if a["first"] <= b["last"] and b["first"] <= a["last"]:
                    sa, sb = live_days(a), live_days(b)
                    overlaps.append(
                        {
                            "a": a["key"],
                            "b": b["key"],
                            "rangeFrom": max(a["first"], b["first"]),
                            "rangeTo": min(a["last"], b["last"]),
                            "sharedBarDays": len(sa & sb),
                        }
                    )

        seams = []
        for i in range(len(recs) - 1):
            a, b = recs[i], recs[i + 1]
            seams.append(
                {
                    "old": a["key"],
                    "new": b["key"],
                    "oldLast": a["last"],
                    "newFirst": b["first"],
                    "gapDays": (ymd_to_date(b["first"]) - ymd_to_date(a["last"])).days,
                    "sameIsin": a["isin"] == b["isin"],
                }
            )

        cotrade = max([o["sharedBarDays"] for o in overlaps] or [0])
        kind = (
            "cotrade"
            if cotrade >= COTRADE_MIN
            else "sequential"
            if all(0 < s["gapDays"] <= NEAR_DAYS for s in seams)
            else "sequential-far"
        )
        flags = sorted(
            {
                t
                for r in recs
                for t in ("DVR", "PP")
                if (t == "DVR" and "DVR" in r["key"])
                or (t == "PP" and (r["key"].endswith("PP") or "PARTLY" in (r["name"] or "").upper()))
            }
        )
        groups.append({"issuer": pre, "kind": kind, "flags": flags, "keys": recs, "overlaps": overlaps, "seams": seams})

    # what the sweep still cannot see, stated as OUR gap and never as evidence of absence
    blind = collections.Counter()
    for k in missing:
        y = str(data[k]["d"][-1])[:4]
        blind[
            "died <=2010 (no ISIN column in the bhavcopy yet)"
            if y <= "2010"
            else "trading, not in any staged security list"
            if y >= "2026"
            else "died 2011-2025"
        ] += 1

    out = {
        "sfEnd": sf_end,
        "binKeys": len(data),
        "isinResolved": len(isin),
        "isinBySource": dict(collections.Counter(src.values())),
        "isinMissing": len(missing),
        "blindSpot": dict(blind),
        "missingKeys": missing,
        "multiKeyIssuers": len(groups),
        "byKind": dict(collections.Counter(g["kind"] for g in groups)),
        "groups": groups,
    }
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)

    print(
        "live sf end %s | %d bin keys | ISIN resolved for %d (%s) | %d still unresolved %s"
        % (sf_end, len(data), len(isin), out["isinBySource"], len(missing), dict(blind))
    )
    print("issuers holding >1 bin key: %d  %s\n" % (len(groups), out["byKind"]))
    for g in groups:
        print("%-8s %s%s" % (g["issuer"], g["kind"], "  " + ",".join(g["flags"]) if g["flags"] else ""))
        for r in g["keys"]:
            print(
                "   %-14s %-13s %-20s %8d..%-8d %5d bars%s  alive=%-5s  %s"
                % (
                    r["key"],
                    r["isin"],
                    r["isinSrc"],
                    r["first"],
                    r["last"],
                    r["mainBars"],
                    " +%d stray" % r["strayBars"] if r["strayBars"] else "         ",
                    r["alive"],
                    r["name"],
                )
            )
        for s in g["seams"]:
            print(
                "     seam %s -> %s  gap %d d%s"
                % (s["old"], s["new"], s["gapDays"], "  SAME ISIN" if s["sameIsin"] else "")
            )
        for o in g["overlaps"]:
            print(
                "     OVERLAP %s / %s  %d..%d  %d shared bar-days"
                % (o["a"], o["b"], o["rangeFrom"], o["rangeTo"], o["sharedBarDays"])
            )
        print()
    print("wrote " + OUT)


if __name__ == "__main__":
    main()

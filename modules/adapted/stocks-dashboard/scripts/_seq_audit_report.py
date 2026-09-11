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
"""§104b seq-entry audit — PHASE 2: offline adjudication report over the raw-row cache.

Buckets each seq entry by what sits on the STORED date:
  OK-RESULT  — stored-date row is CATEGORYNAME 'Result' or SUBCATNAME 'Financial Results'
               (and no earlier stated-period conflict): one-line print for a fast eye scan.
  SUSPECT    — stored-date row is a non-Result category (Board Meeting / Company Update /...),
               or no row sits on the stored date at all, or ordering conflicts exist:
               full-window print for close reading.

Nothing is auto-corrected: verdicts are written by hand after reading the rows.
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backfill_ann_dates_bse as BB
from fetch_announcements import parse_qe

CACHE = os.path.join(HERE, "_seq_audit_rows.json")
SEQ_SRCS = {"bse:seq", "bse:sweep1:seq", "bse:sweep2:seq", "bse:recon:seq"}


def dint(news_dt):
    d = re.sub(r"[^0-9]", "", (news_dt or ""))[:8]
    return int(d) if len(d) == 8 else 0


def gated(news_dt):
    """PIT gate per runbook §12: post-15:30 or weekend -> next weekday (engine-equivalent)."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", news_dt or "")
    if not m:
        return 0
    d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    hh, mm = int(m.group(4)), int(m.group(5))
    if (hh, mm) > (15, 30):
        d += datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return int(d.strftime("%Y%m%d"))


def fmt(r, qe):
    pq = parse_qe(r[3])
    tag = ""
    if pq == qe:
        tag = " <<pq=TARGET"
    elif pq:
        tag = " <<pq=%d" % pq
    att = "att" if r[4] else "NOATT"
    return "    %s | %-14s | %-22s | %s | %s%s" % (r[0][:16], r[1][:14], r[2][:22], att, r[3][:110], tag)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated keys or symbols")
    ap.add_argument("--full", action="store_true", help="print full window even for OK bucket")
    args = ap.parse_args()

    ledger = BB.jload(BB.LEDGER, {})
    cache = BB.jload(CACHE, {})
    seq = {k: v for k, v in ledger.items() if isinstance(v, dict) and v.get("src") in SEQ_SRCS}

    # neighbour-quarter stored anns from the live fundamentals (double-stamp trap)
    fund = BB.jload(BB.SF, {})
    known = {}
    for sym, arr in fund.items():
        for q in arr:
            if isinstance(q, list) and len(q) >= 5 and isinstance(q[0], int):
                ann = min([a for a in (q[2], q[4]) if isinstance(a, int) and a > 0], default=None)
                if ann:
                    known[(sym, q[0])] = ann

    only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    def gap(k):
        _sym, qe = k.split("|")
        return (BB.qe_date(int(seq[k]["ann"])) - BB.qe_date(int(qe))).days

    keys = sorted((k for k in seq if k in cache), key=gap)
    if only:
        keys = [k for k in keys if k in only or k.split("|")[0] in only]

    n_ok = n_sus = 0
    sus_keys = []
    for k in keys:
        sym, qe_s = k.split("|")
        qe = int(qe_s)
        ent = seq[k]
        A = int(ent["ann"])
        c = cache[k]
        if c.get("err"):
            print("SUSPECT %-24s gap=%3dd ann=%d %s  !! cache err: %s" % (k, gap(k), A, ent["src"], c["err"]))
            n_sus += 1
            sus_keys.append(k)
            continue
        rows = sorted(c["rows"], key=lambda r: r[0])
        on_a = [r for r in rows if dint(r[0]) == A]
        # Result-category rows that are NOT results: RPT disclosures (Reg 23(9)) ride the
        # 'Financial Results' subcategory (MIDHANI Jun-2020 class), newspaper ads trail the
        # real filing. Neither is evidence the stored date is the results date.
        NONRES = re.compile(r"related part|reg[a-z]*\.?\s?23\s?\(9\)|newspaper|advertisement", re.IGNORECASE)
        result_on_a = [
            r
            for r in on_a
            if (r[1].strip() == "Result" or r[2].strip().lower() == "financial results") and not NONRES.search(r[3])
        ]
        stated_target_before = [
            r
            for r in rows
            if parse_qe(r[3]) == qe
            and dint(r[0]) < A
            and (r[1].strip() == "Result" or r[2].strip().lower() == "financial results")
            and not NONRES.search(r[3])
        ]
        # prev-quarter results filed ON/AFTER our stored date = ordering conflict
        prv, _ = BB.q_neighbors(qe)
        prev_after = [
            r
            for r in rows
            if parse_qe(r[3]) == prv
            and dint(r[0]) >= A
            and (r[1].strip() == "Result" or r[2].strip().lower() == "financial results")
            and not NONRES.search(r[3])
        ]

        prv2, nxt2 = BB.q_neighbors(qe)
        twin = [str(nq) for nq in (prv2, nxt2) if known.get((sym, nq)) == A]

        ok = bool(result_on_a) and not stated_target_before and not prev_after and not twin
        if ok:
            n_ok += 1
            cap = result_on_a[0][3][:80]
            print("ok      %-24s gap=%3dd ann=%d %-16s | %s | %s" % (k, gap(k), A, ent["src"], result_on_a[0][1], cap))
            if args.full:
                for r in rows:
                    print(fmt(r, qe))
        else:
            n_sus += 1
            sus_keys.append(k)
            why = []
            if not on_a:
                why.append("NO ROW ON STORED DATE")
            elif not result_on_a:
                why.append("stored-date row NOT Result-category")
            if stated_target_before:
                why.append("target-period row EARLIER than stored")
            if prev_after:
                why.append("prev-quarter results ON/AFTER stored")
            if twin:
                why.append("neighbour qe {} stores the SAME date".format(",".join(twin)))
            print("SUSPECT %-24s gap=%3dd ann=%d %-16s !! %s" % (k, gap(k), A, ent["src"], "; ".join(why)))
            shown = 0
            for r in rows:
                d = dint(r[0])
                interesting = (
                    d == A
                    or r[1].strip() == "Result"
                    or r[2].strip().lower() == "financial results"
                    or parse_qe(r[3]) in (qe, prv)
                )
                if interesting:
                    print(fmt(r, qe))
                    shown += 1
            if shown == 0:
                for r in rows[:40]:
                    print(fmt(r, qe))
    print()
    print("== %d ok, %d SUSPECT of %d cached (of %d seq) ==" % (n_ok, n_sus, len(keys), len(seq)))
    if sus_keys:
        print("suspects:", ",".join(sus_keys))


if __name__ == "__main__":
    main()

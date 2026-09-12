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
"""Pre-2020 con-PAT: classify every open cell against the exchange's own filing record.

NO ASSUMPTIONS (standing user rule): the old "2,926 of 2,979 never filed" measurement is treated
as a hypothesis, not a fact. Every cell is judged individually from the NSE filing index the
harvester cached — one row per (quarter, basis), era symbols chased through the rename chain.

POSITIVE CONTROL (run 2026-08-11, before trusting any std-only reading): TMPV/TATAMOTORS shows
46 pre-2019 consolidated rows back to 2006-06-30 — the index DOES reveal consolidated filings
where they exist, so their absence for a specific quarter is evidence about that quarter.

Per-cell verdicts:
  CON_ROW      the index lists a consolidated filing for that exact quarter -> FILL QUEUE
               (xbrl URL when present, else archive detail link / PDF ladder)
  NEVER_YET    E1 a standalone row exists for that exact quarter (the index covers it), AND
               E2 no consolidated row for it, AND E3 the quarter precedes the company's
               first-ever consolidated row -> documented never-filed candidate
               (pre-FY2020 quarterly con was OPTIONAL, so non-filing was lawful and common)
  POST_GAP     quarter is at/after the first con row but has none itself -> intermittent filer,
               REAL gap -> FILL QUEUE (PDF ladder)
  INDEX_HOLE   no standalone row either -> the index does not cover the quarter; NOTHING can be
               concluded (the MGL 20220630 index-hole lesson) -> PDF ladder

Writes (with --apply): started_filing_con / never_filed_con entries into
scripts/no_con_filing.json (the mechanism built for IOB, per-company evidence string included),
plus scratch queues for the fill phase. Never touches value files.

  python -X utf8 scripts/fill2020_tools/classify_pre2020_patc.py [--apply]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SP = "/private/tmp/claude-501/-Users-dhruvan-stocks-dashboard/792ed9c0-939c-4ae3-9fca-5a27480bf0d9/scratchpad"
LISTS = os.path.join(SCRIPTS, "_nselist")
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}


def iso_qe(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    return (
        None
        if not m or m.group(2).title() not in MON
        else int(m.group(3)) * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))
    )


def main():
    apply_it = "--apply" in sys.argv
    inv = json.load(open(os.path.join(SP, "patc_pre2020.json")))
    verdicts, fillq, ledger_cand, nolist = {}, [], {}, []
    counts = {"CON_ROW": 0, "NEVER_YET": 0, "POST_GAP": 0, "INDEX_HOLE": 0}

    for sym, qes in sorted(inv.items()):
        p = os.path.join(LISTS, re.sub(r"[^A-Z0-9]", "_", sym.upper()) + ".json")
        if not os.path.exists(p):
            nolist.append(sym)
            continue
        rows = json.load(open(p))
        std, con, conx = set(), set(), {}
        for r in rows:
            q = iso_qe(r.get("toDate"))
            if not q:
                continue
            if r.get("consolidated") == "Consolidated":
                con.add(q)
                if r.get("xbrl") and not str(r["xbrl"]).endswith("/-"):
                    conx[q] = r["xbrl"]
            else:
                std.add(q)
        min(con) if con else None
        # ANNUAL-ONLY DETECTION (refinement, 2026-08-11). Many companies filed consolidated
        # ANNUALLY pre-FY2020: the index then shows con rows at Mar quarters only (the audited
        # annual con inside the Q4 filing) while std rows run every quarter. Anchoring the
        # leading-run rule on the first-ever con row mislabels their never-filed Jun/Sep/Dec
        # interims as POST_GAP "real gaps" (first pass: 536 such cells). QUARTERLY-cadence
        # consolidation is what ends the never-filed era, and it is measurable: the first
        # NON-MARCH con row. Mar cells with a con row stay CON_ROW (attempted, never assumed).
        first_qtrly_con = min((q for q in con if q % 10000 != 331), default=None)
        for q in qes:
            if q in con:
                v = "CON_ROW"
                fillq.append({"sym": sym, "qe": q, "xbrl": conx.get(q)})
            elif q not in std:
                v = "INDEX_HOLE"
            elif first_qtrly_con is None or q < first_qtrly_con:
                v = "NEVER_YET"  # before any quarterly-cadence con; annual-Mar rows may exist
            else:
                v = "POST_GAP"
                fillq.append({"sym": sym, "qe": q, "xbrl": None})
            counts[v] += 1
            verdicts["%s|%d" % (sym, q)] = v
        # ledger candidate only when EVERY open cell of the company is NEVER_YET-consistent
        never_cells = [q for q in qes if verdicts["%s|%d" % (sym, q)] == "NEVER_YET"]
        if never_cells:
            n_mar_only = len([q for q in con if q % 10000 == 331 and (first_qtrly_con is None or q < first_qtrly_con)])
            ledger_cand[sym] = {
                "first_con_qe": first_qtrly_con,
                "cells": never_cells,
                "evidence": (
                    "NSE filing index: %d standalone rows, %d consolidated (%d of them "
                    "annual-Mar rows before any quarterly cadence); %s; each never-filed "
                    "cell has a std row for its exact quarter and no con row. Annual-Mar "
                    "con cells themselves stay in the fill queue, not here."
                    % (
                        len(std),
                        len(con),
                        n_mar_only,
                        ("first QUARTERLY-cadence con %d" % first_qtrly_con)
                        if first_qtrly_con
                        else "no quarterly-cadence con row EVER",
                    )
                ),
            }

    print("cells classified: %d  %s" % (sum(counts.values()), counts))
    print("companies with no index cache (harvest failed): %d %s" % (len(nolist), nolist[:8]))
    print("fill queue: %d cells (%d with a real XBRL URL)" % (len(fillq), sum(1 for f in fillq if f["xbrl"])))
    print(
        "ledger candidates: %d companies / %d never-filed cells"
        % (len(ledger_cand), sum(len(v["cells"]) for v in ledger_cand.values()))
    )
    json.dump(verdicts, open(os.path.join(SP, "patc_verdicts.json"), "w"), indent=0)
    json.dump(fillq, open(os.path.join(SP, "patc_fill_queue.json"), "w"), indent=1)
    json.dump(ledger_cand, open(os.path.join(SP, "patc_ledger_cand.json"), "w"), indent=1)

    if not apply_it:
        print("(dry run — queues written to scratchpad, no ledger touched)")
        return
    ncp = os.path.join(SCRIPTS, "no_con_filing.json")
    nc = json.load(open(ncp))
    started = nc.setdefault("started_filing_con", {})
    never = set(nc.get("never_filed_con", []))
    notes = nc.setdefault("_evidence_notes", {})
    n_started = n_never = 0
    for sym, v in sorted(ledger_cand.items()):
        if v["first_con_qe"]:
            if sym not in started or started[sym] > v["first_con_qe"]:
                started[sym] = v["first_con_qe"]
                notes[sym + "__started_filing_con"] = v["evidence"]
                n_started += 1
        elif sym not in never:
            never.add(sym)
            notes[sym + "__never_filed_con"] = v["evidence"]
            n_never += 1
    nc["never_filed_con"] = sorted(never)
    json.dump(nc, open(ncp, "w"), indent=1, sort_keys=True)
    print("APPLIED: %d started_filing_con entries, %d never_filed_con additions" % (n_started, n_never))


if __name__ == "__main__":
    main()

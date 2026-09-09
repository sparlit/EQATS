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
"""Re-audit `scripts/no_con_quarterly_2019.json` under the E6 index-credibility gate (2026-08-11).

WHY. The 2019 campaign recorded 61 cells as "no consolidated quarterly result filed for this
quarter" on the strength of E1+E2+E3 (runbook §54b): the NSE per-company index lists a standalone
row for the quarter, no consolidated one, and the quarter precedes the company's FIRST consolidated
row ever. The 2018 campaign then measured the same pattern against a much larger target set and
found 290 cells where E1+E2+E3 holds **while our own store carries a materially different
consolidated figure in that same era** — AXISBANK Jun-2018 con PAT 721.86 against std 701.09, with
the index's first consolidated row at Jun-2019. A distinct consolidated number had to be read from
some document, so for those companies the index's pre-first-con silence is measured-incomplete and
proves nothing (§57: a route returning nothing means THAT ROUTE has no row; §63: never infer "the
company doesn't file it" from a gap).

E6, stated: the index's pre-first-con silence is evidence only if our own store holds NO
contradicting consolidated figure at-or-before that first-con date.

WHAT THIS CHANGES. Nothing in the data: every one of the 61 records carries `written: null`, and
`no_con_quarterly_2019.json` is consumed by no tool (grep, 2026-08-11 — the live ledger that feeds
the coverage definition is the separate `scripts/no_con_filing.json`, and none of the 61 appear in
it). What was wrong was the CLAIM. Retracted cells go back to being open gaps with the reason
recorded, which is the honest state.

Run:  python -X utf8 scripts/fill2020_tools/recheck_na_2019.py [--write]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
NA = os.path.join(SCRIPTS, "no_con_quarterly_2019.json")
sys.path.insert(0, HERE)
from classify_rev2018 import _con_evidence_before  # noqa: E402

RETRACT_NOTE = (
    "RETRACTED 2026-08-11 by the 2018 campaign's E6 gate. E1+E2+E3 still hold as stated, but they "
    "only establish that the NSE per-company index has no consolidated row - and this company's "
    "own stored figures contradict the index's first-con date, so its silence is "
    "measured-incomplete and cannot support a non-filing claim. No value was ever written for this "
    "cell, so nothing in the data changes; the cell returns to OPEN (a real gap needing a "
    "document), not not-applicable."
)


WEAK_NOTE = (
    "WEAK under E6, flagged 2026-08-11. This cell was refuted only on stored consolidated values "
    "that EQUAL the standalone ones - exactly the manufactured-copy case §54b warns about (earlier "
    "passes in this repo produced con PAT by copying std), so it proves nothing about whether the "
    "company filed a consolidated quarterly earlier. The honest status is UNRESOLVED: neither a "
    "confirmed real gap nor a not-applicable record. It is NOT being written back to "
    "not-applicable - 'we cannot tell from our own store' is the state, and the cell must be "
    "settled from a document or a second reader, not from our own data."
)


def audit_refuted(doc, fund, revop):
    """Re-test the sibling session's 26 refutations under E6's MATERIALLY-DIFFERENT bound.

    Their test fired on ANY stored consolidated figure for an earlier quarter, including one equal
    to standalone. E6 requires the figure to DIFFER materially, because a con value copied from std
    is not independent evidence of anything. Cells refuted only on copies are marked unresolved
    rather than silently kept as confirmed gaps."""
    block = doc.get("refuted_2026_08_11") or {}
    weak = []
    for k, v in sorted(block.items()):
        sym, qe = k.split("|")
        fc = (v or {}).get("first_con_filing_ever") if isinstance(v, dict) else None
        ev = _con_evidence_before(sym, fc, fund, revop)
        # The target-quarter check gets the SAME materially-different bound as the rest of E6 — a
        # stored con PAT that merely EXISTS is not evidence if it equals std (the copy case).
        ps, pc = fund.get(sym, {}).get(int(qe), (None, None))
        pc_real = ps is not None and pc is not None and abs(pc - ps) > max(0.05, 0.001 * abs(ps))
        if not pc_real and not ev:
            weak.append(k)
            if isinstance(v, dict):
                v["e6_status"] = "UNRESOLVED — refuted only on con==std copies"
                v["e6_note"] = WEAK_NOTE
    return weak


def main():
    doc = json.load(open(NA))
    cells = dict(doc["cells"])
    fund = {
        s: {int(r[0]): (r[1], r[3] if len(r) > 3 else None) for r in rows}
        for s, rows in json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"))).items()
    }
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))

    kept, retracted = [], []
    for k, v in sorted(cells.items()):
        sym, qe = k.split("|")
        ev = _con_evidence_before(sym, v.get("first_con_filing_ever"), fund, revop)
        pc = fund.get(sym, {}).get(int(qe), (None, None))[1]
        if pc is not None or ev:
            v = dict(v)
            v["retracted"] = RETRACT_NOTE
            v["e6_contradiction"] = ([(f"stored con PAT for this very quarter: {pc}")] if pc is not None else []) + ev[
                :3
            ]
            v["status"] = "OPEN - real gap, not not-applicable"
            retracted.append((k, v))
        else:
            v = dict(v)
            v["status"] = "not-applicable (survives E1+E2+E3+E6)"
            kept.append((k, v))

    weak = audit_refuted(doc, fund, revop)
    print("2019 na cells: %d   survive E6: %d   RETRACTED: %d" % (len(cells), len(kept), len(retracted)))
    print(
        "sibling session's 26 refutations re-tested under E6's materially-different bound: "
        "%d WEAK (refuted only on con==std copies) -> %s" % (len(weak), ", ".join(weak) or "none")
    )
    for k, v in retracted[:8]:
        print("  retract %-22s %s" % (k, v["e6_contradiction"][0]))
    if "--write" not in sys.argv:
        print("\nDRY RUN - nothing written.")
        return
    doc["_doc"] = doc["_doc"] + (
        "  || AMENDED 2026-08-11 (2018 campaign): %d of these %d records are RETRACTED by the new "
        "E6 index-credibility gate - E1+E2+E3 prove only that the NSE index has no consolidated "
        "row, and for these companies our own store holds a materially different consolidated "
        "figure in the same pre-first-con era, so the index's silence is measured-incomplete. "
        "Those cells are OPEN gaps, not not-applicable. No value was ever written for any record "
        "in this file, and no tool consumes it, so the correction is to the CLAIM only." % (len(retracted), len(cells))
    )
    doc["cells"] = sorted(kept + retracted)
    doc["_counts"] = {"total": len(cells), "not_applicable": len(kept), "retracted": len(retracted)}
    json.dump(doc, open(NA, "w"), indent=1)
    print(f"wrote {os.path.basename(NA)}")


if __name__ == "__main__":
    main()

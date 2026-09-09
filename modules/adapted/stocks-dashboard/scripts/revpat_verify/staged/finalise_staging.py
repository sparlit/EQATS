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
"""Build the FINAL staged GICRE corrections from the two arbitration verdict files.

STAGED, NOT APPLIED. No builder reads the output. Every live ledger in this repo is auto-applied by
CI (con_copy_heals.json by apply_owners_full on every refresh; revop_fundamentals/scale_fix by the
builders), and a heal freeze is in force, so the corrections wait here.

Two ledger shapes, because these are two different defects and the appliers are NOT interchangeable:
  standalone PAT   -> scripts/pat_defects.json   {SYM:{QE:{stored_pat, correct_pat, ...}}}
  consolidated rev -> /tmp/con_copy_reads.json   {"SYM|QE|revC":{value, was, ...}}
                      (apply_con_copy_reads.py only ever writes CON slots -- pointing the standalone
                       fixes at it was a real error, caught by a smoke test)

ONE CELL IS DELIBERATELY HELD. GICRE 2023-09-30 con revenue: the con figure itself is well evidenced
(filing read 13075.11, Screener 13075), but the same filing's STANDALONE read (13059.08) does not
match our stored revS (13224.18, which Screener also reports as 13224). Writing con alone would give
con 13075.11 < std 13224.18, while the filing says con > std -- a PAIR that contradicts the document
even though each half has support. Applying half of an unreconciled pair is how §40b comparisons go
wrong. It is staged in `held`, never in `cells`, so no promote step can pick it up silently.
"""
import json
import os

TREE = "/Users/dhruvan/stocks-wt/revpat-verify"
G = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gicre", "gicre_quarters_verdicts.json")
PRIOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arbitration_verdicts.json")
OUT = os.path.join(TREE, "scripts", "revpat_verify", "staged")
AUTH = (
    "user 2026-08-09: explicitly accepted FILING + 1 SITE for these cells, a deliberate "
    "relaxation of campaign rule 6b (which asks for the filing AND >=2 independent sites). "
    "Recorded per cell so the bar this was taken at is never lost."
)

revop = json.load(open(os.path.join(TREE, "docs/sf_revop.json"), encoding="utf-8"))
fund = json.load(open(os.path.join(TREE, "docs/sf_fundamentals.json"), encoding="utf-8"))
std_now = {r[0]: r[1] for r in fund["GICRE"] if isinstance(r, list) and len(r) >= 5}

gv = json.load(open(G, encoding="utf-8"))
pv = json.load(open(PRIOR, encoding="utf-8"))
prior = pv if isinstance(pv, list) else pv.get("cells", [])


def rec(d):
    return list(d.values()) if isinstance(d, dict) else list(d)


pat, rev, held, dropped = {}, {}, {}, []

# ---- standalone PAT: the two originally arbitrated + Dec-2024 ---------------
for r in prior:
    if r.get("symbol") != "GICRE" or r.get("verdict") != "OURS_WRONG":
        continue
    qe = r["quarter"].replace("-", "")
    pat[qe] = {
        "stored_pat": r["ours"],
        "correct_pat": r["filed_value"],
        "defect": (
            "standalone slot holds the CONSOLIDATED statement's PRE-ASSOCIATE PAT row; "
            "the standalone page's own PAT row is the correct value"
        ),
        "source": r.get("source_url"),
        "unit_declared": r.get("unit_declared"),
        "column_anchor": r.get("column_anchor_evidence"),
        "second_check": r.get("second_check"),
        "confidence": r.get("confidence"),
        "quorum": AUTH,
    }

for r in rec(gv.get("pat_cells", {})):
    if r.get("verdict") != "OURS_WRONG":
        dropped.append("{} patS {}".format(r.get("quarter"), r.get("verdict")))
        continue
    qe = r["quarter"].replace("-", "")
    pat[qe] = {
        "stored_pat": r["ours"],
        "correct_pat": r["filed_standalone_pat"],
        "defect": (
            "standalone slot holds the CONSOLIDATED pre-associate PAT row (con "
            "pre-associate {} == our stored value); true standalone from the "
            "standalone page".format(r.get("con_pre_associate"))
        ),
        "source": r.get("source_url"),
        "unit_declared": r.get("unit_declared"),
        "column_anchor": r.get("column_anchor_evidence"),
        "second_check": r.get("second_check"),
        "confidence": r.get("confidence"),
        "quorum": AUTH,
    }

# ---- consolidated revenue --------------------------------------------------
for r in rec(gv.get("revenue_cells", {})):
    if r.get("verdict") != "OURS_WRONG":
        dropped.append("{} revC {}".format(r.get("quarter"), r.get("verdict")))
        continue
    qe = r["quarter"].replace("-", "")
    was = revop["GICRE"][qe][1]
    entry = {
        "value": r["filed_consolidated_revenue"],
        "was": was,
        "src": r.get("source_url"),
        "unit_declared": r.get("unit_declared"),
        "column_anchor": r.get("column_anchor_evidence"),
        "second_check": r.get("second_check"),
        "confidence": r.get("confidence"),
        "quorum": AUTH,
        "notes": r.get("notes"),
    }
    fstd = r.get("filed_standalone_revenue")
    ours_std = revop["GICRE"][qe][0]
    if fstd is not None and abs(fstd - ours_std) > max(0.5, abs(ours_std) * 0.005):
        entry["HELD_REASON"] = (
            "the filing's STANDALONE read ({}) does not match our stored revS ({}). Writing con "
            "alone yields con {} < std {}, while the filing says con > std -- the resulting PAIR "
            "would contradict the document. Resolve the standalone concept first, then move both "
            "together.".format(fstd, ours_std, r["filed_consolidated_revenue"], ours_std)
        )
        held[f"GICRE|{qe}|revC"] = entry
    else:
        rev[f"GICRE|{qe}|revC"] = entry

os.makedirs(OUT, exist_ok=True)
meta = {
    "STATUS": "STAGED -- NOT APPLIED. No builder reads these files.",
    "authorised": AUTH,
    "tree_read_for_guards": TREE,
    "freeze": "heal freeze in force: SHP nsh reparse not landed and a second session is writing the same PAT stores",
}
json.dump(
    {
        "_meta": {
            **meta,
            "merge_into": "scripts/pat_defects.json",
            "guard": "the applier must still match stored_pat before it writes",
        },
        "GICRE": pat,
    },
    open(os.path.join(OUT, "pat_defects_staged.json"), "w"),
    indent=1,
)
json.dump(
    {
        "_meta": {
            **meta,
            "apply_with": "cp .cells to /tmp/con_copy_reads.json then "
            "scripts/fill2020_tools/apply_con_copy_reads.py [--apply]",
            "held_note": "entries in .held are NOT ready to apply -- see HELD_REASON",
        },
        "cells": rev,
        "held": held,
    },
    open(os.path.join(OUT, "con_copy_reads_staged.json"), "w"),
    indent=1,
)

print("STAGED standalone-PAT (-> pat_defects.json): %d" % len(pat))
for q, v in sorted(pat.items()):
    print("   GICRE %s   %10s -> %-10s  (%s)" % (q, v["stored_pat"], v["correct_pat"], v["confidence"][:28]))
print("STAGED consolidated-revenue (-> con_copy_reads): %d" % len(rev))
for k, v in rev.items():
    print("   %-22s %10s -> %-10s" % (k, v["was"], v["value"]))
print("HELD (not applicable as-is): %d" % len(held))
for k, v in held.items():
    print("   %-22s %10s -> %-10s   HELD" % (k, v["was"], v["value"]))
print("DROPPED (verdict not OURS_WRONG): %d  %s" % (len(dropped), "; ".join(dropped)))
print(f"\nwrote {OUT}/{{pat_defects_staged.json,con_copy_reads_staged.json}}")

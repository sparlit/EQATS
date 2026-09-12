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
"""MGL + PATANJALI junk consolidated cells: the E5 blockers, adjudicated 2026-08-10.

con_nofile_identity.py's E5 gate flagged both companies: stored con cells contradict the
con==std identity in quarters where the NSE filing index lists NO consolidated filing
(MGL first con 20231231, PATANJALI first con 20240630). Provenance bisect: every junk value
below entered in the July-2026 batch commits 4d63e91d / 766599a3 / 0809d274, which predate
the provenance-journal rule — no source document exists for any of them.

THE ADJUDICATION (user approved 2026-08-10, all four recommendations):

MGL — no subsidiary existed in ANY affected quarter: the Unison Enviro acquisition completed
2024-02-01 (SPA Mar-2023, PNGRB approval 2023-12-13). Corroborated in our own data: the real
Dec-23 con filing shows con==std exactly, and Mar-24 revC-revS = 52.4 ~= two months of Unison.
So con==std identity values REPLACE the junk (window convention, runbook §68):
  20210630  opC  320.91 -> 303.99 (=opS)   ebitC 275.64 -> 258.72 (=ebitS)   [unsourced]
  20210930  revC 666.85 -> 907.57 (=revS)  opC 303.99 -> 301.76 (=opS)
            [stored values are EXACTLY Jun-21's std row — prev-quarter column copy]
  20230331  revC  33.64 -> 1771.81 (=revS) [foreign junk, Unison-sized; MGL owned nothing then]
  20230630  revC  38.95 -> 1690.18 (=revS) [same]
  20221231  LEDGER ONLY: revC 18.38 -> null, opC 5.28 -> null (docs already null — the two
            files had diverged; quarter is an identity-tool target and refills from its gates)

MGL 20220630 — junk 20.01 sat in the STANDALONE slot too (and its identity copy in con).
True values derived from the company's own Sep-22 standalone XBRL
(INDAS_868110_6014_14112022121632_WEB.xml): H1-minus-Sep, where the same formula reproduces
stored Sep-22 opS 252.84 / ebitS 197.74 EXACTLY and the derived PAT closes on stored Jun-22
patS 185.20 to the paisa:
  revS 20.01 -> 1593.18   revC 20.01 -> 1593.18 (identity)
  opS  null  -> 285.55    ebitS null -> 231.87  (plain fills, same derivation)
(NB: the NSE index has NO row at all for MGL 20220630 — an index hole, E1 cannot fire — but
the Sep-22 filing's H1 column is itself proof the quarter's standalone filing exists.)

PATANJALI — 20220331 revC 20.21 -> null (conservative: FY22 shell-subsidiary status murky;
not a campaign target, null fully unblocks E5). patC 234.43 (=patS identity copy) stays.

Every touched std-series neighbour was exchange-verified first: Dec-21 XBRL matches all four
stored std cells exactly and its 9M column locks Jun+Sep+Dec-21 within 2 paise.

Writes docs/sf_revop.json + scripts/revop_fundamentals.json (guard-asserted per file, the two
differ at MGL 20221231), journals to scripts/mgl_patanjali_con_heal.json, and registers the
non-null rev corrections in scripts/rev_defects.json for verify_fills_live.py protection.

  python -X utf8 scripts/fill2020_tools/apply_mgl_patanjali_con_2026_08_10.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
JOURNAL = os.path.join(SCRIPTS, "mgl_patanjali_con_heal.json")
DEFECTS = os.path.join(SCRIPTS, "rev_defects.json")

# sf_revop row: [0 revS, 1 revC, 2 opS, 3 opC, 4 patS, 5 patC, 6 fin, 7 ebitS, 8 ebitC]
# (sym, qe, idx, slot, old_docs, old_ledger, new)  — None means null; olds asserted per file
EDITS = [
    ("MGL", "20210630", 3, "opC", 320.91, 320.91, 303.99),
    ("MGL", "20210630", 8, "ebitC", 275.64, 275.64, 258.72),
    ("MGL", "20210930", 1, "revC", 666.85, 666.85, 907.57),
    ("MGL", "20210930", 3, "opC", 303.99, 303.99, 301.76),
    ("MGL", "20220630", 0, "revS", 20.01, 20.01, 1593.18),
    ("MGL", "20220630", 1, "revC", 20.01, 20.01, 1593.18),
    ("MGL", "20220630", 2, "opS", None, None, 285.55),
    ("MGL", "20220630", 7, "ebitS", None, None, 231.87),
    ("MGL", "20221231", 1, "revC", None, 18.38, None),
    ("MGL", "20221231", 3, "opC", None, 5.28, None),
    ("MGL", "20230331", 1, "revC", 33.64, 33.64, 1771.81),
    ("MGL", "20230630", 1, "revC", 38.95, 38.95, 1690.18),
    ("PATANJALI", "20220331", 1, "revC", 20.21, 20.21, None),
]

EVIDENCE = {
    "MGL": "NSE filing index: first consolidated filing ever 20231231; every affected quarter "
    "std-listed with no con row (20220630 = index hole, proven via Sep-22 H1 column). "
    "Unison Enviro control passed 2024-02-01 — no subsidiary in any affected quarter.",
    "PATANJALI": "NSE filing index: first consolidated filing ever 20240630; 20220331 std-listed, "
    "no con row. No source document for the stored 20.21.",
}
SRC_JUN22 = (
    "H1-minus-Sep from own Sep-22 std XBRL "
    "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_868110_6014_14112022121632_WEB.xml; "
    "PAT identity closes on stored 185.20 exactly"
)

# rev-slot NON-NULL corrections registered for the live-clobber detector (nulls are excluded:
# a null entry would false-DRIFT once the identity tool refills the cell)
DEFECT_ROWS = {
    ("MGL", "20210930"): {
        "bad_rev": 666.85,
        "correct_rev": 907.57,
        "basis": "con",
        "defect": "con slot held Jun-21's ENTIRE std row (revC=Jun-21 revS, opC=Jun-21 opS) — "
        "prev-quarter column copy from batch 766599a3; no con filing exists (first con "
        "20231231, no subsidiary before 2024-02-01) so con==std identity",
        "source": "NSE filing index + Unison Enviro completion 2024-02-01; revS 907.57 locked by "
        "Dec-21 XBRL 9M identity (2697.29 vs Jun+Sep+Dec sum, delta 0.02)",
    },
    ("MGL", "20220630"): {
        "bad_rev": 20.01,
        "correct_rev": 1593.18,
        "basis": "std",
        "defect": "foreign junk in BOTH rev slots (batch 4d63e91d created the row); con slot healed "
        "to the same 1593.18 by identity in the same pass",
        "source": SRC_JUN22,
    },
    ("MGL", "20230331"): {
        "bad_rev": 33.64,
        "correct_rev": 1771.81,
        "basis": "con",
        "defect": "Unison-sized foreign junk in con slot (batch 0809d274); no con filing, no "
        "subsidiary until 2024-02-01 — con==std identity",
        "source": "NSE filing index (std-listed, no con row) + Unison completion 2024-02-01",
    },
    ("MGL", "20230630"): {
        "bad_rev": 38.95,
        "correct_rev": 1690.18,
        "basis": "con",
        "defect": "Unison-sized foreign junk in con slot (batch 0809d274); no con filing, no "
        "subsidiary until 2024-02-01 — con==std identity",
        "source": "NSE filing index (std-listed, no con row) + Unison completion 2024-02-01",
    },
}


def close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < 0.005


def main():
    dry = "--apply" not in sys.argv
    files = [(DOCS, 4), (LEDGER, 5)]  # (path, old-value column in EDITS)
    for path, oldcol in files:
        d = json.load(open(path, encoding="utf-8"))
        touched = 0
        for sym, qe, idx, slot, od, ol, new in EDITS:
            old = (od, ol)[oldcol - 4]
            row = (d.get(sym) or {}).get(qe)
            if row is None:
                sys.exit(f"GUARD {sym} {qe} missing in {os.path.basename(path)}")
            if not close(row[idx], old):
                sys.exit(f"GUARD {sym} {qe} {slot} in {os.path.basename(path)}: found {row[idx]!r} expected {old!r}")
            if not close(row[idx], new):
                row[idx] = new
                touched += 1
        print("%s: %d cells %s" % (os.path.basename(path), touched, "would change" if dry else "written"))
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))

    if dry:
        print("(dry run — nothing written; pass --apply)")
        return

    defects = json.load(open(DEFECTS, encoding="utf-8"))
    for (sym, qe), entry in sorted(DEFECT_ROWS.items()):
        defects.setdefault(sym, {})[qe] = entry
    json.dump(defects, open(DEFECTS, "w"), indent=1, sort_keys=True)

    json.dump(
        {
            "generated": "2026-08-10",
            "campaign": "revcon-close: E5-blocker heal (runbook §2b + §68), user approved 2026-08-10",
            "provenance_of_junk": "git bisect of scripts/revop_fundamentals.json: batches 4d63e91d "
            "(2026-07-22), 766599a3 (2026-07-22), 0809d274 (2026-07-28) — all "
            "pre-provenance-rule, no source documents",
            "evidence": EVIDENCE,
            "jun22_derivation": SRC_JUN22,
            "cells": [
                {"sym": s, "qe": q, "slot": slot, "old_docs": od, "old_ledger": ol, "new": n}
                for s, q, i, slot, od, ol, n in EDITS
            ],
        },
        open(JOURNAL, "w"),
        indent=1,
        sort_keys=True,
    )
    print(
        "journal -> %s; %d defect entries -> %s"
        % (os.path.basename(JOURNAL), len(DEFECT_ROWS), os.path.basename(DEFECTS))
    )


if __name__ == "__main__":
    main()

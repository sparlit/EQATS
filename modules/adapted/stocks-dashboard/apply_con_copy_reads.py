# -*- coding: utf-8 -*-
"""Apply the filing-read corrections for cells whose CON slot held a copy of standalone.

Only the direction this evidence supports. read_con_copies.py returned two populations and they are
NOT the same defect:

  CON WAS WRONG (11 cells)   the filing's consolidated figure differs from what we store, and what
                             we store equals our standalone. Fixed here.
  CON WAS RIGHT  (5 cells)   the filing reproduces our con value exactly -- so the copy is in the
                             STANDALONE slot instead (SKFINDIA stores 1256/1213/1283 as standalone
                             where screener's standalone is 559/493/462). That is the mirror defect,
                             runbook §59, and writing "con = con" would silently leave the real
                             error in place. Reported, not touched.

Each value came from a consolidated page of the company's own filing, located by screener's con
figure and CONFIRMED by a second column on the same rows reproducing screener's con figure for a
DIFFERENT quarter at the same scale. Journalled to con_copy_heals.json, reversible.

Run: python -X utf8 scripts/fill2020_tools/apply_con_copy_reads.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
JOURNAL = os.path.join(SCRIPTS, "con_copy_heals.json")
REVIEW = os.path.join(SCRIPTS, "_std_slot_holds_con.json")
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"),
         os.path.join(SCRIPTS, "revop_fundamentals.json"))
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"),
        os.path.join(SCRIPTS, "fundamentals.json"))
REVC, PATC_REVOP, PATC_FUND = 1, 5, 3


def same(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.05, abs(b) * 0.002)


def main():
    dry = "--apply" not in sys.argv
    reads = json.load(open("/tmp/con_copy_reads.json"))
    fix, mirror = {}, {}
    for k, v in reads.items():
        if v.get("value") is None:
            continue
        (mirror if same(v["value"], v["was"]) else fix)[k] = v

    print("CON-slot corrections: %d | STANDALONE-slot mirror defects (reported only): %d\n"
          % (len(fix), len(mirror)))
    journal = {}

    for path in REVOP:
        if not os.path.exists(path):
            continue
        d = json.load(open(path))
        n = 0
        for k, v in fix.items():
            sym, qe, field = k.split("|")
            row = (d.get(sym) or {}).get(qe)
            if not row:
                continue
            while len(row) < 9:
                row.append(None)
            slot = REVC if field == "revC" else PATC_REVOP
            if row[slot] is None or not same(row[slot], v["was"]):
                continue
            row[slot] = v["value"]
            d[sym][qe] = row
            n += 1
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s %d" % (os.path.basename(path), "would set" if dry else "set", n))

    for path in FUND:
        if not os.path.exists(path):
            continue
        d = json.load(open(path))
        n = 0
        for k, v in fix.items():
            sym, qe, field = k.split("|")
            if field != "patC":
                continue
            for r in d.get(sym, []):
                if str(r[0]) != qe or len(r) <= PATC_FUND:
                    continue
                if r[PATC_FUND] is None or not same(r[PATC_FUND], v["was"]):
                    continue
                r[PATC_FUND] = v["value"]
                n += 1
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s %d PAT" % (os.path.basename(path), "would fix" if dry else "fixed", n))

    for k, v in sorted(fix.items()):
        print("   %-26s %10.2f -> %-10.2f  %s" % (k, v["was"], v["value"], v["confirm"][:44]))
        journal[k] = {"was": v["was"], "now": v["value"], "src": v["doc"], "page": v["page"],
                      "row": v["row"], "confirm": v["confirm"], "screener": v["screener"],
                      "reason": "con slot held a copy of standalone; value read from the filing's "
                                "own consolidated page",
                      "applied": "2026-08-09"}
    print("\nMIRROR (standalone slot holds the consolidated value -- runbook §59, NOT touched):")
    for k, v in sorted(mirror.items()):
        print("   %-26s con %s is correct; the STANDALONE cell is the suspect" % (k, v["value"]))

    if dry:
        print("\nDRY RUN -- nothing written.")
        return
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    json.dump(mirror, open(REVIEW, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s | %d mirror cells -> %s"
          % (len(journal), os.path.basename(JOURNAL), len(mirror), os.path.basename(REVIEW)))


if __name__ == "__main__":
    main()

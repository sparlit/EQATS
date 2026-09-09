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
"""STAGE (never apply) filing-proven STANDALONE-REVENUE corrections, in the rev_defects shape.

WHY A SEPARATE FILE AND NOT THE LIVE LEDGER. Every live ledger in this repo is applied by CI --
`con_copy_heals.json` is re-read by `apply_owners_full.py` on every refresh-fundamentals run, and
`revop_fundamentals.json` / `scale_fix.json` by the builders. Writing a correction into one of them
is not "staging", it heals on the next nightly. While a heal freeze is in force the correction lives
here, where no builder reads it.

THE DEFECT THIS STAGES. `screener_prerev.py` accepts a Screener revenue row once that page's NET
PROFIT matches our stored PAT. A PAT-only anchor is blind to WHICH REVENUE ROW was taken, so a
component (e.g. `Interest income`) can land in the revenue slot. Confirmed on AADHARHFC 2023-06 and
2023-12 (533.47 / 579.26 == the filing's Interest income row, exact to the cent).

PROMOTE LATER, once the freeze lifts, EITHER:
  (a) add the `bad_rev` guard to `scripts/rev_defects.json` and let a corrected read refill, OR
  (b) direct-correct per runbook §2b -- guard-edit BOTH `docs/sf_revop.json` AND
      `scripts/revop_fundamentals.json`, asserting the OLD value before writing.
then re-run the nightlies and DIFF (§41 -- journalled is not live), and verify LIVE ~20 min after
the push and again after the next nightly.

GUARDS, each of which REFUSES rather than guesses:
  * verdict must be OURS_WRONG;
  * a filed value with no `source_url` never stages -- never write a value no source asserts;
  * `bad_rev` is read LIVE from the pinned tree so a later applier's guard will match reality; if
    the stored value has moved since arbitration the cell is DROPPED, not forced;
  * filed == stored -> dropped (nothing to correct);
  * a cell whose CONTROL quarter was not confirmed is reported, because a defect finding without a
    passing control is indistinguishable from a broken method.

  python3 -X utf8 scripts/revpat_verify/stage_rev_defects.py --verdicts <f.json> --sym HDBFS \
      --out scripts/revpat_verify/staged/rev_defects_staged_HDBFS.json --authorised "<who/what>"
"""
import argparse
import json
import os

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--sym", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--authorised", default="")
    a = ap.parse_args()

    revop = json.load(open(os.path.join(TREE, "docs/sf_revop.json"), encoding="utf-8"))
    mine = revop.get(a.sym.upper()) or {}

    doc = json.load(open(a.verdicts, encoding="utf-8"))
    cells = doc if isinstance(doc, list) else (doc.get("cells") or doc.get("quarters") or [])
    if isinstance(cells, dict):
        cells = list(cells.values())

    staged, dropped, controls = {}, [], []
    for r in cells:
        q = str(r.get("quarter", "")).replace("-", "")
        verdict = r.get("verdict")
        filed = r.get("filed_total_revenue_from_operations")
        if filed is None:
            filed = r.get("filed_value")
        if verdict == "OURS_CONFIRMED":
            controls.append(q)
            dropped.append({"qe": q, "why": "OURS_CONFIRMED (control or clean quarter)"})
            continue
        if verdict != "OURS_WRONG":
            dropped.append({"qe": q, "why": f"verdict {verdict}"})
            continue
        if filed is None:
            dropped.append({"qe": q, "why": "no filed value asserted"})
            continue
        if not r.get("source_url"):
            dropped.append({"qe": q, "why": "no source_url -- refusing a value with no document"})
            continue
        row = mine.get(q)
        was = row[0] if row else None
        if was is None:
            dropped.append({"qe": q, "why": "nothing stored now -- applier guard could not match"})
            continue
        if abs(float(filed) - float(was)) <= max(0.05, abs(float(was)) * 0.002):
            dropped.append({"qe": q, "why": "filed == stored, nothing to correct"})
            continue
        staged[q] = {
            "bad_rev": round(float(was), 2),
            "correct_rev": round(float(filed), 2),
            "basis": "std",
            "defect": r.get("gap_explained_by")
            or r.get("notes")
            or "stored value is a COMPONENT row, not Total revenue from operations",
            "ours_matches_row": r.get("ours_matches_which_row"),
            "source": r.get("source_url"),
            "unit_declared": r.get("unit_declared"),
            "column_anchor": r.get("column_anchor_evidence"),
            "second_check": r.get("second_check"),
            "confidence": r.get("confidence"),
            "quorum": a.authorised,
        }

    out = {
        "_meta": {
            "STATUS": "STAGED -- NOT APPLIED. No builder reads this file.",
            "shape": "scripts/rev_defects.json is {SYM:{QE:{bad_rev,basis,defect,source}}} -- a guarded "
            "NULL ledger. We also carry correct_rev, since the filing gives the true total.",
            "promote": "(a) add bad_rev to rev_defects.json and let a corrected read refill, or "
            "(b) direct-correct per runbook 2b, guard-editing BOTH docs/sf_revop.json and "
            "scripts/revop_fundamentals.json with an assert on the old value",
            "then": "re-run the nightlies and DIFF (runbook 41), verify LIVE ~20 min after the push",
            "control_quarters_confirmed": controls,
            "authorised": a.authorised,
            "tree_read_for_guards": TREE,
        },
        a.sym.upper(): staged,
        "dropped": dropped,
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)

    print("STAGED %d %s revenue corrections:" % (len(staged), a.sym.upper()))
    for q, e in sorted(staged.items()):
        print(
            "   %s  %10s -> %-10s  (ours == %s)" % (q, e["bad_rev"], e["correct_rev"], str(e["ours_matches_row"])[:60])
        )
    print(
        "CONTROL quarters that came back confirmed: %s"
        % (
            ", ".join(controls)
            if controls
            else "NONE -- a defect finding without a passing control is indistinguishable from a broken method"
        )
    )
    print("DROPPED %d: %s" % (len(dropped), "; ".join("{} {}".format(d["qe"], d["why"]) for d in dropped)))
    print(f"\nwrote {a.out}  (inert)")


if __name__ == "__main__":
    main()

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
"""STAGE (never apply) filing-proven revenue corrections from a MULTI-SYMBOL verdict file.

`stage_rev_defects.py` handles one symbol per run, which suited the single-company packets. Batch
arbitrations cover several companies at once, so this reads any verdict file (list, or dict with a
`cells`/`quarters`/`verdicts` key) and emits the `extra_rev_staged.json` shape that
`apply_staged_heals.py` already consumes:

    {"cells": {"SYM|QE|revS": {"was": <live>, "value": <filed or null>, ...}}}

GUARDS — each REFUSES rather than guesses, and each exists because of something that went wrong:
  * verdict must be OURS_WRONG. OURS_CONFIRMED / AMBIGUOUS_CONCEPT / UNRESOLVED never stage.
  * no `source_url` -> dropped. Never write a value no document asserts.
  * `was` is read LIVE from the tree, so the applier's own guard will match; if the stored value has
    moved since arbitration the cell is dropped, not forced.
  * filed == stored -> dropped, nothing to correct.
  * **CONTROL GATE:** a symbol contributes NOTHING unless at least one of its quarters came back
    OURS_CONFIRMED. A defect finding with no passing control is indistinguishable from a broken
    reading method, and this campaign has relied on controls to license every heal so far.

  python3 -X utf8 scripts/revpat_verify/stage_batch_verdicts.py --verdicts a.json --verdicts b.json \
      --out scripts/revpat_verify/staged/extra_rev_staged.json --authorised "<who/what>"
"""
import argparse
import collections
import json
import os

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rows_of(doc):
    if isinstance(doc, list):
        return doc
    for k in ("cells", "quarters", "verdicts", "results"):
        v = doc.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            return list(v.values())
    return [v for v in doc.values() if isinstance(v, dict) and v.get("quarter")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--verdicts",
        action="append",
        required=True,
        help="verdict file; append ':SYM' for single-company packets whose records "
        "omit a symbol field (e.g. aadharhfc_verdicts.json:AADHARHFC)",
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--authorised", default="")
    ap.add_argument(
        "--accept-inline-control",
        action="store_true",
        help="allow a cell whose SYMBOL has no sibling OURS_CONFIRMED quarter, provided "
        "the record itself carries a second_check (an FY identity, an "
        "adjacent-quarter match, a component sum). Use only when the packet "
        "genuinely proved its method per cell; it is recorded per cell either way.",
    )
    ap.add_argument("--merge", action="store_true", help="merge into an existing staged file instead of replacing it")
    a = ap.parse_args()

    revop = json.load(open(os.path.join(TREE, "docs/sf_revop.json"), encoding="utf-8"))

    recs = []
    for spec in a.verdicts:
        p, _, dsym = spec.partition(":") if not os.path.exists(spec) else (spec, "", "")
        if not os.path.exists(p):
            print(f"  ! missing verdict file: {p}")
            continue
        for r in rows_of(json.load(open(p, encoding="utf-8"))):
            if dsym and not (r.get("symbol") or r.get("sym")):
                r["symbol"] = dsym  # single-company packet: records carry no symbol
            recs.append(r)

    # control gate — which symbols proved their method on a known-good quarter?
    confirmed = {str(r.get("symbol") or r.get("sym", "")).upper() for r in recs if r.get("verdict") == "OURS_CONFIRMED"}

    cells, dropped = {}, []
    for r in recs:
        sym = str(r.get("symbol") or r.get("sym", "")).upper()
        q = str(r.get("quarter") or r.get("qe") or "").replace("-", "")
        verdict = r.get("verdict")
        if verdict != "OURS_WRONG":
            continue
        filed = r.get("recommended_value")
        if filed is None:
            filed = r.get("filed_total_revenue_from_operations") or r.get("filed_value")
        if r.get("ours_now") is None and r.get("ours_revS") is not None:
            r["ours_now"] = r["ours_revS"]
        # Basis detection must not hinge on the substring "con": a verdict file described a cell
        # as "sf_revop.json[GYFTR][20240630][1] (revC) ..." which contains no "con" at all, so it
        # was misread as revS, looked up an empty slot and was dropped as "nothing stored". Right
        # outcome, wrong reason — and it would have been the WRONG SLOT had revS been populated.
        _f = str(r.get("field", "")).lower()
        fld = "revC" if ("revc" in _f or "consolidated" in _f or "[1]" in _f) else "revS"
        idx = 1 if fld == "revC" else 0

        def drop(why):
            dropped.append({"sym": sym, "qe": q, "field": fld, "why": why})

        inline = str(r.get("second_check") or "").strip()
        if sym not in confirmed and not (a.accept_inline_control and inline):
            drop(
                "NO PASSING CONTROL for this symbol — a defect finding without one is "
                "indistinguishable from a broken reading method"
            )
            continue
        if filed is None:
            drop("no filed value asserted")
            continue
        if not r.get("source_url"):
            drop("no source_url — refusing a value with no document behind it")
            continue
        row = (revop.get(sym) or {}).get(q)
        was = row[idx] if row and len(row) > idx else None
        if was is None:
            drop("nothing stored now — the applier's guard could not match")
            continue
        if abs(float(filed) - float(was)) <= max(0.05, abs(float(was)) * 0.002):
            drop("filed == stored, nothing to correct")
            continue

        cells[f"{sym}|{q}|{fld}"] = {
            "was": round(float(was), 2),
            "value": round(float(filed), 2),
            "src": r.get("source_url"),
            "unit_declared": r.get("unit_declared"),
            "why": r.get("ours_matches_which_row") or r.get("notes"),
            "column_anchor": r.get("column_anchor_evidence"),
            "second_check": r.get("second_check"),
            "confidence": r.get("confidence"),
            "quorum": a.authorised,
            "control": (
                "sibling OURS_CONFIRMED quarter"
                if sym in confirmed
                else "INLINE second_check only (no sibling control quarter)"
            ),
        }

    if a.merge and os.path.exists(a.out):
        prev = json.load(open(a.out, encoding="utf-8")).get("cells", {})
        prev.update(cells)
        cells = prev

    out = {
        "_meta": {
            "STATUS": "STAGED — no builder reads this file",
            "authorised": a.authorised,
            "control_gate": "a symbol stages only if one of its quarters came back OURS_CONFIRMED",
            "symbols_with_control": sorted(confirmed),
        },
        "cells": cells,
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)

    bysym = collections.Counter(k.split("|")[0] for k in cells)
    print("STAGED %d cell(s) across %d symbol(s): %s" % (len(cells), len(bysym), dict(bysym)))
    for k, v in sorted(cells.items()):
        print("   %-26s %12s -> %-12s (%s)" % (k, v["was"], v["value"], str(v.get("confidence"))[:18]))
    print("symbols with a passing control: %s" % (", ".join(sorted(confirmed)) or "NONE"))
    print("DROPPED %d:" % len(dropped))
    for d in dropped:
        print("   %-11s %-9s %-5s %s" % (d["sym"], d["qe"], d["field"], d["why"]))
    print(f"\nwrote {a.out} (inert)")


if __name__ == "__main__":
    main()

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
"""Apply gated aggregator fills to the ledgers. FILL-ONLY, fast, and separate from the fetching.

Why it is its own script: several sessions push docs/sf_revop.json and scripts/revop_fundamentals.json
on the same day and both are single-line JSON, so a textual rebase conflict is certain. The write
therefore has to be ~1s -- fetch, gate and adjudicate happen in agg_sweep.py, this only replays the
proposal ledger (CLAUDE.md rule 4 / runbook §38).

Writes:
  docs/sf_revop.json            slot 0 = revS, slot 1 = revC
  scripts/revop_fundamentals.json   the same rows, the ledger the nightly rebuild reads
  scripts/agg_cell_fills.json   TRACKED provenance, one entry per cell: value, precision, the site,
                                the row LABEL it came from, how many of our stored quarters that
                                site's own series reproduced, and the worst anchor error.

An already-populated cell is NEVER overwritten (§6 fill-only) and a row that does not exist for
that quarter is skipped, not created -- a missing row means the quarter is not in the dataset's
frame and inventing one hides that.

  python3 -X utf8 scripts/agg_tools/apply_agg_fills.py --props <proposals.json>          # dry
  python3 -X utf8 scripts/agg_tools/apply_agg_fills.py --props <proposals.json> --apply
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "agg_cell_fills.json")
# sf_revop cell layout: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
SLOT = {"revS": 0, "revC": 1, "opS": 2, "opC": 3, "ebitS": 7, "ebitC": 8}
SITE_NAME = {
    "mc": "moneycontrol",
    "tl": "trendlyne",
    "tt": "tickertape",
    # screener.in comes through screener_opebit.py, which carries its own gate because
    # screener prints CRORE-ROUNDED integers where the other three print two decimals
    "sc": "screener.in",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--props", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--stamp", default=time.strftime("%Y-%m-%d"))
    # Row creation is OFF by default and stays that way: in sf_revop a missing row USUALLY means the
    # quarter is outside the dataset's frame, and silently materialising one there would invent a
    # period. But "usually" is not "always" — POLICYBZR's revenue series starts 2022-03 while we hold
    # its PAT from 2020-06, so Dec-2021 is a HOLE inside its life, not a period beyond it. The caller
    # has to assert that distinction deliberately, per run, rather than have the applier guess.
    ap.add_argument(
        "--create-rows",
        action="store_true",
        help="materialise a sf_revop row for a quarter we do not hold. Only use when the "
        "company demonstrably existed and filed that quarter (e.g. we already hold "
        "its PAT for it) — otherwise the row is an invented period.",
    )
    a = ap.parse_args()

    props = json.load(open(a.props))["proposals"]
    journal, skipped, wrote, created = {}, [], 0, []

    for path in (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        base = os.path.basename(path)
        n = 0
        for key in sorted(props):
            sym, qe, field = key.split("|")
            if field not in SLOT:
                skipped.append(f"{key}: {field} is not a sf_revop field")
                continue
            p = props[key]
            row = (d.get(sym) or {}).get(qe)
            if row is None:
                if not a.create_rows:
                    skipped.append(f"{key}: no {qe} row in {base}")
                    continue
                row = [None] * 9
                d.setdefault(sym, {})[qe] = row
                created.append(f"{key} in {base}")
            while len(row) < 9:
                row.append(None)
            i = SLOT[field]
            if row[i] is not None:
                skipped.append(f"{key}: already = {row[i]} ({base})")
                continue
            row[i] = p["value"]
            d[sym][qe] = row
            n += 1
            ch = p["chosen"]
            # KEYED SYM|QE, not SYM|QE|FIELD: scripts/verify_fills_live.py (the blocking clobber
            # detector, runbook §41/§56b) rsplits a ledger key ONCE, so a three-part key makes it
            # read the FIELD as the quarter and silently check nothing -- a guard that looks wired
            # and guards air. Both fields of the same quarter merge into one entry.
            jkey = f"{sym}|{qe}"
            journal.setdefault(jkey, {})
            # A proposal that carries its OWN evidence sentence (agg_era_gate.py writes one for
            # every GATE-E pass) is journalled with THAT sentence. The template below describes a
            # gate A/A2 pass and nothing else; stamping it on a gate-E cell records a gate that
            # never ran -- the exact mislabelling agg_era_gate._evidence was written to end.
            ent = {
                field: p["value"],
                "state": p["state"],
                "precision": ch["precision"],
                "src": "{} quarterly-results API (runbook §81)".format(SITE_NAME.get(ch["site"], ch["site"])),
                "row_label": ch["row"],
                "evidence": p.get("evidence")
                or (
                    "gate A/A2 passed: that site's own %s series reproduces %d of our stored "
                    "quarters with zero disagreements, worst anchor error %.4f; nearest anchor "
                    "within 4 quarters" % (field, ch["anchors"], ch["worst_anchor"])
                ),
                "corroborated_by": [SITE_NAME.get(s, s) for s in p.get("corroborated_by", [])],
                "site_reach": p.get("sites", {}),
                "fy_check": p.get("fy_check"),
                "applied": f"{a.stamp} aggregator sweep",
            }
            for extra in ("gate", "excused", "our_fy_identity", "resolved_via", "nearest_anchor_q"):
                if p.get(extra) is not None:
                    ent[extra] = p[extra]
            journal[jkey].update(ent)
        if a.apply:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-32s %s %d cells" % (base, "filled" if a.apply else "would fill", n))
        wrote = max(wrote, n)

    for s in skipped[:40]:
        print(f"  skip: {s}")
    if len(skipped) > 40:
        print("  ... %d more skips" % (len(skipped) - 40))

    if a.apply and journal:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        # ★ MERGE PER ENTRY, NEVER REPLACE (2026-09-05). `led.update(journal)` swapped the whole
        # SYM|QE record for the new one, so an opS fill on a quarter that already carried a revS
        # entry silently dropped the revS assertion (and its provenance) from the ledger -- and
        # with it the clobber check on that revS cell. When the record already holds ANOTHER
        # field's value, the new field lands with its provenance nested under `<field>_prov`.
        nested = 0
        for jkey, ent in journal.items():
            cur = led.get(jkey)
            fields_here = [f for f in SLOT if ent.get(f) is not None]
            if cur and any(cur.get(f) is not None for f in SLOT if f not in fields_here):
                for f in fields_here:
                    cur[f] = ent[f]
                    cur[f + "_prov"] = {k: v for k, v in ent.items() if k not in SLOT}
                nested += 1
            else:
                led[jkey] = {**(cur or {}), **ent}
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print(
            "journalled %d -> %s (%d merged into records holding another field)"
            % (len(journal), os.path.basename(LEDGER), nested)
        )
    if created:
        print("  CREATED %d row(s) that did not exist: %s" % (len(created), "; ".join(created[:6])))
    if not a.apply:
        print("DRY RUN -- nothing written.")
    return 0 if wrote or not props else 1


if __name__ == "__main__":
    sys.exit(main())

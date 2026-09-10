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
"""FILL-2020 rev track: consolidated rev/op = standalone where NO CONSOLIDATED RESULT WAS FILED.

THE EVIDENCE, and why it is stronger than the earlier identity passes. scripts/nosub_rev_derive.py
proves "no subsidiary" from OUR OWN stored PAT cells (con PAT == std PAT), which is partly circular:
prior passes manufactured some of those con PAT cells by copying std. This pass instead reads NSE's
per-company filing INDEX -- the exchange's own record of what the company actually filed:

  E1  the index lists a STANDALONE result for that exact quarter  (so the index does cover it --
      absence of a consolidated row is meaningful, not just a hole in the index);
  E2  the index lists NO consolidated result for that quarter;
  E3  the quarter is EARLIER than the company's FIRST consolidated filing (or the company has never
      filed one at all). Once a subsidiary appears it does not un-appear, so the identity is only
      defensible before that date -- this is the leading-run rule from derive_nosub_pat_bulk.py,
      the rule BAJAJELEC exists to enforce;
  E4  our stored con PAT for the quarter already equals std PAT (materially: max(0.05, 0.1%));
  E5  NO quarter at-or-before the gap contradicts the identity -- no stored quarter in which both
      revenue bases, or both PAT bases, are materially different (>1%). This is what disqualified
      ZFCVINDIA (con rev 385.1 against std 440.9 in Dec-2019, before its gap run) and PATANJALI/
      MGL/HATSUN.

Post-Apr-2019 this is decisive rather than suggestive: consolidated quarterly results became
COMPULSORY for any listed company having subsidiaries (runbook §51a), so a company filing only
standalone in the campaign window is asserting it has nothing to consolidate.

BANKS WERE EXCLUDED BY USER DECISION (2026-08-06) AND ARE NOW INCLUDED. Asked again the same day,
when the con-PAT follow-up surfaced the identical question for KTKBANK/SOUTHBANK, the user chose
"include banks everywhere". CUB (79 filings, ZERO consolidated ever) and UCOBANK (first consolidated
2022-03, after its whole gap run) meet every gate above, so they now fill on the same evidence as
the non-banks. IOB is NOT affected: it fails E4 -- its con is null throughout the window, and where
it does report con it DIVERGES from std (551.78 vs 552.38, runbook §51c) -- so an identity there
would be fabrication and it stays null.

Fill-only, campaign window only: revC <- revS, opC <- opS, ebitC <- ebitS, never over a non-null
cell, never for KIRLFER. Writes docs/sf_revop.json + scripts/revop_fundamentals.json and journals
every cell with its evidence to scripts/con_nofile_identity_fills.json (tracked).

Run:  python -X utf8 scripts/fill2020_tools/con_nofile_identity.py [--apply]
"""
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
CAND = os.path.join(HERE, "_con_identity_candidates.json")
LIST_CACHE = os.path.join(SCRIPTS, "_nselist")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
LEDGER_OUT = os.path.join(SCRIPTS, "con_nofile_identity_fills.json")

# sf_revop row: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
TWINS = [(1, 0, "revC"), (3, 2, "opC"), (8, 7, "ebitC")]
CARVE_OUT = {"KIRLFER"}  # mixed-basis con series (runbook §5)
BANKS_NULL = set()  # was {CUB, UCOBANK, KTKBANK, SOUTHBANK}; user reversed it 2026-08-06
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}


def iso_qe(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    return None if not m else int(m.group(3)) * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))


def index_evidence(sym):
    """(n_std_quarters, n_con_quarters, first_con_qe) from the cached NSE filing index."""
    p = os.path.join(LIST_CACHE, re.sub(r"[^A-Z0-9]", "_", sym.upper()) + ".json")
    std, con = set(), set()
    for r in json.load(open(p)):
        qe = iso_qe(r.get("toDate"))
        if qe:
            (con if r.get("consolidated") == "Consolidated" else std).add(qe)
    return len(std), len(con), (min(con) if con else None)


# ---------------------------------------------------------------------------------------------
# CANDIDATE BUILDER — the E1..E5 gates, in code.
# This lived in a session's scratch analysis the first time it ran, which made the route only
# half-reproducible: the tool applied a candidate file it could not itself regenerate. It is here
# now so `--rebuild-candidates` re-derives the list from current data + the cached NSE index.
# ---------------------------------------------------------------------------------------------
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
DROPPED = os.path.join(HERE, "_con_identity_dropped.json")
MAT_ABS, MAT_REL = 0.05, 0.001  # E4: con PAT == std PAT "materially"
CONTRA_REL = 0.01  # E5: >1% apart at-or-before the gap contradicts the identity


def _mat_eq(a, b):
    if a is None or b is None:
        return None
    return abs(a - b) <= max(MAT_ABS, MAT_REL * abs(a))


def rebuild_candidates():
    targets = json.load(open(TARGETS))
    revop = json.load(open(REVOP_DOCS))
    fund = {s: {int(r[0]): (r[1], r[3]) for r in rows if len(r) > 3} for s, rows in json.load(open(FUND)).items()}
    keep, dropped = {}, {}

    for sym, v in sorted(targets.items()):
        if not v.get("revC"):
            continue
        p = os.path.join(LIST_CACHE, re.sub(r"[^A-Z0-9]", "_", sym.upper()) + ".json")
        if not os.path.exists(p):
            dropped[sym] = {"reason": "no cached NSE index (run nse_list_harvest.py)", "cells": v["revC"]}
            continue
        have = {"std": set(), "con": set()}
        for r in json.load(open(p)):
            qe = iso_qe(r.get("toDate"))
            if qe:
                have["con" if r.get("consolidated") == "Consolidated" else "std"].add(qe)
        firstcon = min(have["con"]) if have["con"] else None

        passed, why = [], []
        for qe in sorted(v["revC"]):
            row = (revop.get(sym) or {}).get(str(qe)) or [None] * 9
            ps, pc = fund.get(sym, {}).get(qe, (None, None))
            if sym in CARVE_OUT:
                why.append("carve-out")
            elif qe not in have["std"]:
                why.append("%d: E1 no standalone row in the index for that quarter" % qe)
            elif qe in have["con"]:
                why.append("%d: E2 a consolidated filing EXISTS for that quarter" % qe)
            elif firstcon is not None and qe > firstcon:
                why.append("%d: E3 later than the first consolidated filing (%d)" % (qe, firstcon))
            elif row[0] is None:
                why.append("%d: no standalone revenue to copy" % qe)
            elif pc is None:
                why.append("%d: E4 no stored con PAT" % qe)
            elif _mat_eq(ps, pc) is not True:
                why.append("%d: E4 stored con PAT differs from std (%s vs %s)" % (qe, ps, pc))
            else:
                passed.append(qe)
        if not passed:
            dropped[sym] = {"reason": "; ".join(why[:4]), "cells": v["revC"]}
            continue

        # E5 — a contradiction anywhere AT OR BEFORE the gap run disqualifies the whole company.
        last = max(passed)
        bad = []
        for q, row in (revop.get(sym) or {}).items():
            if int(q) > last:
                continue
            if row[0] is not None and row[1] is not None and abs(row[1] - row[0]) > CONTRA_REL * max(abs(row[0]), 1e-9):
                bad.append(f"rev@{q} {row[0]:.1f} vs {row[1]:.1f}")
        for q, (a, b) in fund.get(sym, {}).items():
            if q > last or a is None or b is None:
                continue
            if abs(b - a) > CONTRA_REL * max(abs(a), 1e-9):
                bad.append("pat@%d %.2f vs %.2f" % (q, a, b))
        if bad:
            dropped[sym] = {"reason": "E5 contradicted at/before the gap: " + "; ".join(bad[:3]), "cells": v["revC"]}
            continue
        keep[sym] = passed

    json.dump(keep, open(CAND, "w"), indent=1, sort_keys=True)
    json.dump(dropped, open(DROPPED, "w"), indent=1, sort_keys=True)
    print(
        "candidates: %d cells / %d companies  (dropped %d companies)"
        % (sum(len(v) for v in keep.values()), len(keep), len(dropped))
    )
    for sym, qes in sorted(keep.items(), key=lambda kv: -len(kv[1])):
        print("    %-13s %2d" % (sym, len(qes)))
    return keep


def main():
    apply_it = "--apply" in sys.argv
    if "--rebuild-candidates" in sys.argv:
        rebuild_candidates()
        if not apply_it:
            return
    cand = json.load(open(CAND))
    revop = json.load(open(REVOP_DOCS))
    ledger = json.load(open(REVOP_LEDGER))

    fills, held = [], defaultdict(list)
    for sym, qes in sorted(cand.items()):
        if sym in CARVE_OUT:
            held["carve-out (mixed-basis con series)"].append(sym)
            continue
        if sym in BANKS_NULL:
            held["bank — user decision, stays null"].extend("%s|%d" % (sym, q) for q in qes)
            continue
        nstd, ncon, firstcon = index_evidence(sym)
        for qe in sorted(qes):
            row = (revop.get(sym) or {}).get(str(qe))
            if not row:
                continue
            for c_i, s_i, name in TWINS:
                if row[c_i] is None and row[s_i] is not None:
                    fills.append((sym, str(qe), c_i, name, row[s_i], nstd, ncon, firstcon))

    by_field = defaultdict(int)
    for f in fills:
        by_field[f[3]] += 1
    cells = len({(f[0], f[1]) for f in fills})
    print("=" * 78)
    print("%s — consolidated identity where NO consolidated result was filed" % ("APPLY" if apply_it else "DRY RUN"))
    print("=" * 78)
    print(
        "companies %d | quarter-cells %d | values %d  (%s)"
        % (len({f[0] for f in fills}), cells, len(fills), ", ".join("%s=%d" % kv for kv in sorted(by_field.items())))
    )
    for why, items in sorted(held.items()):
        print("  HELD NULL: %-38s %d" % (why, len(items)))
    per = defaultdict(int)
    for f in fills:
        per[f[0]] += 1
    for sym, n in sorted(per.items(), key=lambda kv: -kv[1]):
        nstd, ncon, firstcon = index_evidence(sym)
        print(
            "    %-13s %3d values | NSE index: %3d std qtrs, %2d con qtrs, first con %s"
            % (sym, n, nstd, ncon, firstcon or "NEVER")
        )

    if not apply_it:
        print("\n(dry run — nothing written)")
        return

    journal, applied = defaultdict(dict), 0
    for sym, qe_s, idx, name, val, nstd, ncon, firstcon in fills:
        row = revop[sym][qe_s]
        if row[idx] is not None:  # fill-only
            continue
        row[idx] = val
        applied += 1
        journal[sym].setdefault(qe_s, {})[name] = val
        journal[sym][qe_s]["evidence"] = (
            "NSE filing index: %d standalone quarters, %d consolidated, first consolidated %s "
            "— no consolidated result filed for this quarter" % (nstd, ncon, firstcon or "NEVER")
        )
        lrow = ledger.setdefault(sym, {}).get(qe_s)
        if lrow is None:
            ledger[sym][qe_s] = list(row)
        elif lrow[idx] is None:
            lrow[idx] = val

    json.dump(revop, open(REVOP_DOCS, "w"), separators=(",", ":"))
    json.dump(ledger, open(REVOP_LEDGER, "w"), separators=(",", ":"))
    # MERGE, never replace. `fills` only ever contains cells this run actually wrote, so a second
    # run (e.g. the 2026-08-06 bank re-run) would otherwise publish a ledger holding four companies
    # and silently drop the provenance of the 91 values the first run landed.
    prior = {}
    if os.path.exists(LEDGER_OUT):
        try:
            prior = (json.load(open(LEDGER_OUT)) or {}).get("fills") or {}
        except Exception:
            prior = {}
    merged = {s: dict(v) for s, v in prior.items()}
    for sym, qmap in journal.items():
        merged.setdefault(sym, {}).update(qmap)
    json.dump(
        {
            "generated": "2026-08-06",
            "campaign": "FILL-2020 revenue track (scripts/FILL2020_CAMPAIGN.md)",
            "method": "consolidated = standalone where the exchange's filing index shows NO consolidated "
            "result was filed for that quarter (SEBI LODR Reg 33 identity)",
            "evidence_source": "NSE api/corporates-financial-results per-company filing index",
            "gates": [
                "E1 standalone row present for that exact quarter",
                "E2 no consolidated row for that quarter",
                "E3 quarter earlier than the first consolidated filing ever",
                "E4 stored con PAT already equals std PAT (max(0.05, 0.1%))",
                ("E5 no quarter at-or-before the gap where both rev bases or both PAT bases differ by >1%"),
            ],
            "user_gate": "approved 2026-08-06 for the 91 non-bank values; banks approved the same "
            "day when the user chose 'include banks everywhere'",
            "held_null": dict(held.items()),
            "companies": len(merged),
            "values": sum(len([k for k in q if k != "evidence"]) for v in merged.values() for q in v.values()),
            "last_run_values": applied,
            "last_run_companies": len(journal),
            "fills": merged,
        },
        open(LEDGER_OUT, "w"),
        indent=1,
        sort_keys=True,
    )
    print(
        "\nAPPLIED %d values across %d companies (ledger now holds %d companies)" % (applied, len(journal), len(merged))
    )


if __name__ == "__main__":
    main()

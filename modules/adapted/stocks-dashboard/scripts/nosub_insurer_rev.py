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


"""
NO-SUB CONSOLIDATED REVENUE FOR INSURERS  (FILL-2020 campaign, Phase 1b)

Same accounting identity as scripts/nosub_rev_derive.py (SEBI LODR Reg 33: no subsidiaries => the
standalone result IS the consolidated result), but insurers need their OWN evidence gate.

WHY A SEPARATE SCRIPT: nosub_rev_derive.py's decisive gate (P6) reads the company's XBRL filings for
NatureOfReportStandaloneConsolidated. Insurers file the IRDAI format, which carries no XBRL P&L at
all -- they are absent from the XBRL cache by construction, so P6 can never pass and every insurer was
excluded from that pass. Demanding P6 here would mean never filling them.

THE SUBSTITUTE GATE (non-circular by construction):
  earlier passes apply_nosub_constd.py / apply_nosub_constd2.py manufactured con PAT by copying std,
  but ONLY for quarter-ends in COPY_QES (all four 2025 quarters) and only for the symbols they list.
  So this script judges the identity using ONLY quarters those passes could not have touched:

  I1  >= MIN_CLEAN quarters OUTSIDE the copy window store BOTH std and con PAT
  I2  con PAT == std PAT EXACTLY in every one of them
  I3  every sf_revop quarter storing both revenue bases agrees (as P3)
  I4  the symbol is a known insurer (this script is deliberately not general-purpose)

A company with subsidiaries cannot match its standalone PAT to the paisa across 10+ consecutive
genuinely-parsed quarters, so I1+I2 carry the same force as P1/P2 while being immune to the copy.

Measured 2026-08-05 (clean quarters / mismatches): SBILIFE 33/0, ICICIGI 26/0, STARHEALTH 25/0,
GODIGIT 17/0, NIVABUPA 14/0 -> derivable. ICICIPRULI 45 mismatches, HDFCLIFE 33, NIACL 30, GICRE 5,
LICI 12 -> genuinely consolidated, they need extraction per INSURER_EXTRACTION_PLAYBOOK.md, NOT this.

Usage:  python -X utf8 scripts/nosub_insurer_rev.py [--apply]
"""
import json
import sys
from collections import defaultdict

MIN_CLEAN = 10
WINDOW_START = 20191231
COPY_QES = {20250331, 20250630, 20250930, 20251231}  # the only quarters the prior copies touched

# Two groups share this gate because NSE serves NO XBRL for either, so the P6 cache test in
# nosub_rev_derive.py can never pass for them:
#   insurer — IRDAI format carries no XBRL P&L at all
#   noxbrl  — the ~330 NSE-listed names NSE simply never serves an XBRL for (the ABBOTINDIA /
#             BAYERCROP class called out in backfill_revop_gaps.py's header)
# Pick with a positional arg: `python scripts/nosub_insurer_rev.py noxbrl --apply`
GROUPS = {
    "insurer": {
        "SBILIFE",
        "HDFCLIFE",
        "ICICIPRULI",
        "ICICIGI",
        "GICRE",
        "NIACL",
        "LICI",
        "STARHEALTH",
        "NIVABUPA",
        "GODIGIT",
        "MFSL",
    },
    "noxbrl": {
        "GVT&D",
        "ABBOTINDIA",
        "BOSCH-HCIL",
        "BAJAJHFL",
        "BAYERCROP",
        "CANHLIFE",
        "ICICIAMC",
        "ALIVUS",
        "ENRIN",
        "LGEINDIA",
    },
}
GROUP = next((a for a in sys.argv[1:] if a in GROUPS), "insurer")
INSURERS = GROUPS[GROUP]
LEDGER_OUT = f"scripts/nosub_{GROUP}_rev_fills.json"

REV_S, REV_C, OP_S, OP_C, PAT_S, PAT_C, FINFLAG, EBIT_S, EBIT_C = range(9)
TWINS = [(REV_C, REV_S, "revC"), (OP_C, OP_S, "opC"), (EBIT_C, EBIT_S, "ebitC")]
APPLY = "--apply" in sys.argv


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


fund_raw = load("docs/sf_fundamentals.json")
revop = load("docs/sf_revop.json")
ledger = load("scripts/revop_fundamentals.json")
fund = {s: {int(r[0]): (r[1], r[3]) for r in rows if len(r) > 3} for s, rows in fund_raw.items()}

proven, rejected = {}, {}
for sym in sorted(INSURERS):
    if sym not in fund or sym not in revop:
        rejected[sym] = "not in datasets"
        continue
    clean = [(qe, s, c) for qe, (s, c) in fund[sym].items() if s is not None and c is not None and qe not in COPY_QES]
    if len(clean) < MIN_CLEAN:
        rejected[sym] = f"only {len(clean)} copy-free quarters (<{MIN_CLEAN})"
        continue
    bad = [qe for qe, s, c in clean if s != c]
    if bad:
        rejected[sym] = f"con differs from std in {len(bad)}/{len(clean)} copy-free quarters -> real consolidation"
        continue
    conflict = None
    for qe_s, row in revop[sym].items():
        for c_i, s_i in ((REV_C, REV_S), (OP_C, OP_S)):
            if row[c_i] is not None and row[s_i] is not None and row[c_i] != row[s_i]:
                conflict = f"rev/op differ @{qe_s}"
    if conflict:
        rejected[sym] = conflict
        continue
    proven[sym] = {"copy_free_quarters": len(clean), "mismatches": 0}

fills = []
for sym in proven:
    for qe_s, row in revop[sym].items():
        if int(qe_s) < WINDOW_START:
            continue
        for c_i, s_i, name in TWINS:
            if row[c_i] is None and row[s_i] is not None:
                fills.append((sym, qe_s, c_i, name, row[s_i]))

by_field = defaultdict(int)
for _, _, _, n, _ in fills:
    by_field[n] += 1

print("=" * 74)
print("{} — no-sub consolidated derivation (group={})".format("APPLY" if APPLY else "DRY RUN", GROUP))
print("=" * 74)
summary = ", ".join("%s(%dq)" % (s, v["copy_free_quarters"]) for s, v in proven.items())
print("PROVEN : %d  %s" % (len(proven), summary))
for s, why in rejected.items():
    print(f"  reject {s:12s} {why}")
print(f"\ncells to fill: {len(fills)}  " + "  ".join(f"{k}={v}" for k, v in sorted(by_field.items())))

if not APPLY:
    print("\n(dry run — nothing written)")
    sys.exit(0)

journal = defaultdict(dict)
applied = 0
for sym, qe_s, idx, name, val in fills:
    row = revop[sym][qe_s]
    if row[idx] is not None:
        continue
    row[idx] = val
    applied += 1
    journal[sym].setdefault(qe_s, {})[name] = val
    lrow = ledger.setdefault(sym, {}).get(qe_s)
    if lrow is None:
        ledger[sym][qe_s] = list(row)
    elif lrow[idx] is None:
        lrow[idx] = val

with open("docs/sf_revop.json", "w", encoding="utf-8") as f:
    json.dump(revop, f, separators=(",", ":"))
with open("scripts/revop_fundamentals.json", "w", encoding="utf-8") as f:
    json.dump(ledger, f, separators=(",", ":"))
with open(LEDGER_OUT, "w", encoding="utf-8") as f:
    json.dump(
        {
            "generated": "2026-08-05",
            "campaign": "FILL-2020 Phase 1b (scripts/FILL2020_CAMPAIGN.md)",
            "method": "no-sub consolidated identity (SEBI LODR Reg 33)",
            "group": GROUP,
            "evidence_class": "PAT identity over copy-free quarters ONLY — NSE serves no XBRL for these "
            "names, so the XBRL gate used by nosub_rev_derive.py (P6) cannot "
            "apply; quarters touched by apply_nosub_constd*.py are excluded so the test "
            "cannot be satisfied by those copies",
            "copy_quarters_excluded": sorted(COPY_QES),
            "min_clean_quarters": MIN_CLEAN,
            "companies": len(journal),
            "cells": applied,
            "per_company_proof": proven,
            "rejected": rejected,
            "fills": journal,
        },
        f,
        indent=1,
    )

print(f"\nAPPLIED {applied} cells across {len(journal)} insurers.")

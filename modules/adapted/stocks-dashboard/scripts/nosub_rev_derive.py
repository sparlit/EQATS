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
NO-SUB CONSOLIDATED REVENUE DERIVATION  (FILL-2020 campaign, Phase 2)

A company with no subsidiaries has nothing to consolidate: SEBI LODR Reg 33 treats its standalone
result AS its consolidated result. An earlier PAT backfill already applied that identity to
sf_fundamentals (con PAT = std PAT); sf_revop never got the same pass, so consolidated REVENUE/OP/EBIT
sit empty for those same companies.

This script PROVES the identity per company from stored data, then fills con = std, fill-only.

PROOF (all must hold, else the company is excluded and its gap goes to the fetch grind):
  P1  >= MIN_PAT_PAIRS quarters where sf_fundamentals stores BOTH std and con PAT.
  P2  EVERY such quarter has con PAT == std PAT exactly (a real subsidiary shows up as a difference).
  P3  EVERY sf_revop quarter storing BOTH std and con revenue has them equal (independent check on the
      very field we are about to write).
  P4  Same as P3 for operating profit.
  P5  Not on the CARVE_OUT list (known mixed-basis series).
  P6  ★ THE NON-CIRCULAR GATE ★ — the company's own XBRL filings declare
      NatureOfReportStandaloneConsolidated = Standalone and NEVER Consolidated, across >= MIN_XBRL
      filings. P1/P2 alone are CIRCULAR: earlier passes (apply_nosub_constd*.py) manufactured con PAT
      by copying std, so "con == std" can be an artifact of that copy rather than evidence of no-sub.
      P6 reads the filings themselves, which no derivation of ours can contaminate. Verified to
      discriminate: RELIANCE/TCS/HDFCBANK/INFY all report Consolidated; COLPAL/PAGEIND/AUBANK/
      KARURVYSYA/BANDHANBNK report Standalone only. Companies ABSENT from the XBRL cache (insurers
      such as SBILIFE — IRDAI format, no XBRL P&L) have NO evidence and are excluded here; they are
      campaign group B (extraction, not derivation).

Writes (fill-only, never overwrites a non-null cell), in the campaign window only:
  sf_revop / revop_fundamentals  idx1 revC <- idx0 revS,  idx3 opC <- idx2 opS,  idx8 ebitC <- idx7 ebitS

Usage:  python -X utf8 scripts/nosub_rev_derive.py            (dry run — writes nothing)
        python -X utf8 scripts/nosub_rev_derive.py --apply    (writes both json files + ledger)
"""
import json
import sys
from collections import defaultdict

MIN_PAT_PAIRS = 6  # P1: minimum overlap quarters needed to trust the identity
MIN_XBRL = 4  # P6: minimum cached filings needed before "never Consolidated" means anything
WINDOW_START = 20191231  # campaign mandate: 2020 -> date (Dec-2019 quarter is Jan-2020's "current")
CARVE_OUT = {"KIRLFER"}  # mixed-basis con series (runbook §5 pending queue) — never identity-fill

# built by scripts/scan_xbrl_nature.py over scripts/_xbrl_cache (gitignored, ~104k filings)
XBRL_NATURE = "scripts/xbrl_nature.json"

REV_S, REV_C, OP_S, OP_C, PAT_S, PAT_C, FINFLAG, EBIT_S, EBIT_C = range(9)
TWINS = [(REV_C, REV_S, "revC"), (OP_C, OP_S, "opC"), (EBIT_C, EBIT_S, "ebitC")]

APPLY = "--apply" in sys.argv


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


fund_raw = load("docs/sf_fundamentals.json")
revop = load("docs/sf_revop.json")
ledger = load("scripts/revop_fundamentals.json")
idx_hist = load("scripts/indices_history.json")
rename_map = load("scripts/_rename_map.json")
xbrl_nature = load(XBRL_NATURE)

n500 = sorted(idx_hist["Nifty 500"], key=lambda s: s["effectiveDate"])

# sf_fundamentals rows: [qe, std, annStd, con, annCon]
fund = {sym: {int(r[0]): (r[1], r[3]) for r in rows} for sym, rows in fund_raw.items()}


def resolve(sym, tgt):
    cur, seen = sym, set()
    while cur not in tgt:
        if cur in seen or cur not in rename_map:
            return None
        seen.add(cur)
        cur = rename_map[cur]
    return cur


def quarter_ends():
    out, y = [], 2019
    while True:
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            qe = y * 10000 + m * 100 + d
            if qe < WINDOW_START:
                continue
            if (y, m) > (2026, 6):
                return out
            out.append(qe)
        y += 1


QES = quarter_ends()


def members_at(qe):
    ds = f"{qe // 10000:04d}-{(qe // 100) % 100:02d}-{qe % 100:02d}"
    best = None
    for s in n500:
        if s["effectiveDate"] <= ds:
            best = s
        else:
            break
    return [s for s in best["symbols"] if not s.upper().startswith("DUMMY")]


# ---- scope: every point-in-time member that has a con-revenue gap in the window ----
gap_qes = defaultdict(set)  # sym -> {qe with revC missing}
member_qes = defaultdict(set)
for qe in QES:
    for sym in members_at(qe):
        member_qes[sym].add(qe)
        rk = resolve(sym, revop)
        if rk is None:
            continue
        row = revop[rk].get(str(qe))
        if row and row[REV_C] is None and row[REV_S] is not None:
            gap_qes[sym].add(qe)

results = {"proven": {}, "rejected": defaultdict(list)}

for sym in sorted(gap_qes):
    if sym in CARVE_OUT:
        results["rejected"]["carve_out"].append(sym)
        continue

    fk = resolve(sym, fund)
    if fk is None:
        results["rejected"]["no_pat_series"].append(sym)
        continue

    # P1 + P2 — PAT identity across the WHOLE stored series (strongest available evidence)
    pairs = [(qe, s, c) for qe, (s, c) in fund[fk].items() if s is not None and c is not None]
    if len(pairs) < MIN_PAT_PAIRS:
        results["rejected"]["too_few_pat_pairs"].append(f"{sym}({len(pairs)})")
        continue
    mismatched = [qe for qe, s, c in pairs if s != c]
    if mismatched:
        results["rejected"]["pat_differs"].append(f"{sym}({len(mismatched)}/{len(pairs)})")
        continue

    # P3 + P4 — independent check on rev/op wherever both bases are already stored
    rk = resolve(sym, revop)
    rev_pairs = op_pairs = 0
    conflict = None
    for qe_s, row in revop[rk].items():
        for c_i, s_i, name in ((REV_C, REV_S, "rev"), (OP_C, OP_S, "op")):
            if row[c_i] is not None and row[s_i] is not None:
                if name == "rev":
                    rev_pairs += 1
                else:
                    op_pairs += 1
                if row[c_i] != row[s_i]:
                    conflict = f"{sym}({name}@{qe_s}: {row[s_i]} vs {row[c_i]})"
    if conflict:
        results["rejected"]["rev_or_op_differs"].append(conflict)
        continue

    # P6 — the non-circular gate: what do the company's OWN filings declare?
    ev = xbrl_nature.get(sym) or xbrl_nature.get(fk) or xbrl_nature.get(resolve(sym, xbrl_nature) or "")
    if not ev or ev["filings"] < MIN_XBRL:
        results["rejected"]["no_xbrl_evidence"].append(f"{sym}({ev['filings'] if ev else 0} filings)")
        continue
    if "Consolidated" in ev["nat"]:
        results["rejected"]["files_consolidated"].append(sym)
        continue
    if "Standalone" not in ev["nat"]:
        results["rejected"]["no_nature_tag"].append(sym)
        continue

    results["proven"][sym] = {
        "xbrl_filings": ev["filings"],
        "xbrl_natures": ev["nat"],
        "pat_pairs": len(pairs),
        "rev_pairs_checked": rev_pairs,
        "op_pairs_checked": op_pairs,
        "gap_quarters": sorted(gap_qes[sym]),
    }

# ---- build the fill set ----
fills = []  # (sym, revop_key, qe_str, idx, field, value)
for sym, info in results["proven"].items():
    rk = resolve(sym, revop)
    for qe in sorted(member_qes[sym]):
        row = revop[rk].get(str(qe))
        if not row:
            continue
        for c_i, s_i, name in TWINS:
            if row[c_i] is None and row[s_i] is not None:
                fills.append((sym, rk, str(qe), c_i, name, row[s_i]))

by_field = defaultdict(int)
for _, _, _, _, name, _ in fills:
    by_field[name] += 1

print("=" * 78)
print(f"{'APPLY' if APPLY else 'DRY RUN'} — no-sub consolidated derivation, window {WINDOW_START}..20260630")
print("=" * 78)
print(f"companies with a con-rev gap in window : {len(gap_qes)}")
print(f"PROVEN no-sub (identity holds)         : {len(results['proven'])}")
print(f"rejected                               : {sum(len(v) for v in results['rejected'].values())}")
for reason, syms in sorted(results["rejected"].items()):
    print(f"    {reason:22s} {len(syms):4d}  e.g. {', '.join(syms[:4])}")
print(f"\ncells to fill: {len(fills)}   " + "  ".join(f"{k}={v}" for k, v in sorted(by_field.items())))

top = sorted(results["proven"].items(), key=lambda kv: -len(kv[1]["gap_quarters"]))[:12]
print("\nsample proven companies (gap qtrs | PAT pairs proving identity | rev pairs cross-checked):")
for sym, info in top:
    print(
        f"    {sym:14s} {len(info['gap_quarters']):3d} qtrs | {info['pat_pairs']:3d} PAT pairs all equal"
        f" | {info['rev_pairs_checked']:3d} rev pairs equal"
    )

if not APPLY:
    print("\n(dry run — nothing written. Re-run with --apply)")
    sys.exit(0)

# ---- apply, fill-only, to BOTH files ----
journal = defaultdict(dict)
applied = skipped = 0
for sym, rk, qe_s, idx, name, val in fills:
    row = revop[rk][qe_s]
    if row[idx] is not None:
        skipped += 1
        continue
    row[idx] = val
    applied += 1
    journal[sym].setdefault(qe_s, {})[name] = val

    lrow = ledger.setdefault(rk, {}).get(qe_s)
    if lrow is None:
        ledger[rk][qe_s] = list(row)
    elif lrow[idx] is None:
        lrow[idx] = val

with open("docs/sf_revop.json", "w", encoding="utf-8") as f:
    json.dump(revop, f, separators=(",", ":"))
with open("scripts/revop_fundamentals.json", "w", encoding="utf-8") as f:
    json.dump(ledger, f, separators=(",", ":"))

prov = {
    "generated": "2026-08-05",
    "campaign": "FILL-2020 Phase 2 (scripts/FILL2020_CAMPAIGN.md)",
    "method": "no-sub consolidated identity (SEBI LODR Reg 33): con = std for companies with no subsidiaries",
    "proof": {
        "P1": f">= {MIN_PAT_PAIRS} quarters storing BOTH std and con PAT",
        "P2": "con PAT == std PAT EXACTLY in every such quarter (whole stored series)",
        "P3": "every sf_revop quarter storing both revenue bases has them equal",
        "P4": "same for operating profit",
        "P5": f"not carved out ({sorted(CARVE_OUT)})",
    },
    "source": "derived from the company's own stored standalone series — no external fetch",
    "window": [WINDOW_START, 20260630],
    "companies": len(journal),
    "cells": applied,
    "per_company_proof": {s: results["proven"][s] for s in journal},
    "fills": dict(journal.items()),
}
with open("scripts/nosub_rev_fills.json", "w", encoding="utf-8") as f:
    json.dump(prov, f, indent=1)

print(f"\nAPPLIED {applied} cells across {len(journal)} companies (skipped {skipped} already-filled).")
print("wrote docs/sf_revop.json, scripts/revop_fundamentals.json, scripts/nosub_rev_fills.json")

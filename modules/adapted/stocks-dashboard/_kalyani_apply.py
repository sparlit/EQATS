# -*- coding: utf-8 -*-
"""Close out the KALYANI wrong-company cleanup (runbook §73, the 4th TRU/CCL/SHK ticker-identity trap).

Context. Our KALYANI is **Kalyani Commercials Ltd, ISIN INE610E01010 (NSE-only)**. `bse_scrips.json`
by_id mapped KALYANI -> BSE 544023, which is **Kalyani Cast-Tech Ltd, ISIN INE0N6U01018** — a
different company whose scrip_id happens to be the string "KALYANI". The 2026-08-10 std-PAT
adjudication healed the three poisoned PAT cells (Mar-24/Dec-24/Mar-25) and nulled their con twins.
This finishes the series, every value re-read from Kalyani Commercials' OWN filings this session:

  FILL  Jun-2024  std 0.62  ann 20240812   rev 57.85    (INDAS_111487_1221613_12082024)
  FILL  Sep-2024  std 0.74  ann 20241113   rev 89.66    (INDAS_115573_1308357_13112024)
  FILL  Mar-2024  rev 62.47                             (INDAS_108110_1146809_30052024)
  FILL  Dec-2024  rev 136.90                            (INDAS_119375_1376564_10022025)
  ANN   Dec-2024  0 -> 20250210            (was the date-unknown sentinel)
  ANN   Mar-2024  20240527 -> 20240530     (20240527 was the WRONG COMPANY's date)
  HEAL  Sep-2025  std 0.24 -> 0.12         (filer printed PAT==PBT with a BLANK tax cell)

Anchors (all read from primary documents this session, none taken from prior notes):
 * H1 FY25 chain: Q1 0.6171 + Q2 0.7363 == 1.3534 == the Sep-24 filing's own printed H1. Revenue
   57.8483 + 89.6564 == 147.5047 == its printed H1 revenue. Both EXACT.
 * 9M FY25 chain: +Q3 0.2553 == 1.6087 == the Dec-24 filing's printed 9M; revenue sums to
   284.4052 == its printed 9M revenue. Both EXACT.
 * FY25 close, from an INDEPENDENT later document (the Q4-FY26 statement filed 2026-05-28, which
   prints FY25 as its comparative): 0.6171+0.7363+0.2553+0.7237 == 2.3324 == printed 233.24 lakh;
   revenue 387.3046 == printed 38,730.46 lakh. Both EXACT.
 * Sep-2025 (§2b correction, 4 independent locks): the printed statement's current-tax cell for the
   quarter is BLANK, so its Net Profit row just repeats PBT (24.10 lakh). Its OWN Basic EPS for that
   column reads 1.24 -> 12.40 lakh on 1,000,000 shares (paid-up 1.0cr / FV 10, confirmed by Q1 EPS
   6.3 == 63.01 lakh and H1 EPS 7.54 == 75.39 lakh). H1 75.39 - Q1 63.01 == 12.38. 9M 138.61 -
   Q1 63.01 - Q3 63.22 == 12.38. -> 0.1238 cr -> 0.12.
 * con stays NULL everywhere: the NSE filing index lists EVERY row Non-Consolidated from Jun-2022
   onward (§51/§54 index-as-evidence). The company last filed consolidated for Mar-2022.

NOT healed, deliberately (journalled as an open flag): Mar-2026 std 1.24. The FY26 identity misses
by 0.0417 (FY 2.6718 - 9M 1.3861 = 1.2857 vs the filed 1.2440) because the Q4 column's current-tax
cell repeats the 9M tax figure byte-for-byte (49.52 lakh; the true Q4 tax is 96.03-49.52-1.16 =
45.35). Revenue and PBT chains both close EXACTLY, so this is a tax-line error, not a restatement.
But 1.2857 is a SUBTRACTION no document asserts, while 1.2440 is printed AND tagged -> §45 says
refuse when neither side reconciles, and the standing rule is never to write a value no source
asserts. Reported, not written.

Dry-run by default; --apply to write. Safety per §2b / the §73 applier:
  * guard: every cell's CURRENT value must equal the recorded `was` or the run aborts;
  * blast radius: each of the four twins is diffed against its original and the run aborts unless
    the ONLY changes are the intended cells;
  * idempotent: a cell already at `now` is reported and skipped.
"""
import json, os, sys, copy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SYM = "KALYANI"
TOL = 0.011
FUND_TWINS = ("docs/sf_fundamentals.json", "scripts/fundamentals.json")
REVOP_TWINS = ("docs/sf_revop.json", "scripts/revop_fundamentals.json")

SRC = {
    "20240331": "own std XBRL INDAS_108110_1146809_30052024 (NameOfTheCompany='Kalyani Commercials Limited', Symbol=KALYANI, OneD 2024-01-01..2024-03-31): rev 62.4657, PAT 0.3189. Announce date = NSE broadCastDate 30-May-2024 (board meeting 2024-05-29); the stored 20240527 came from BSE 544023 (Kalyani Cast-Tech), the wrong company.",
    "20240630": "own std XBRL INDAS_111487_1221613_12082024 (name+symbol verified in-document, OneD 2024-04-01..2024-06-30): rev 57.8483, PAT 0.6171. Locked by the Sep-24 filing's printed H1 (PAT 1.3534 == 0.6171+0.7363, rev 147.5047 == 57.8483+89.6564, both EXACT) and by the Q4-FY26 statement's FY25 comparative (233.24 lakh == the four quarters).",
    "20240930": "own std XBRL INDAS_115573_1308357_13112024 (name+symbol verified, OneD 2024-07-01..2024-09-30): rev 89.6564, PAT 0.7363. Same H1/9M/FY25 chains; the Sep-2025 statement re-prints this quarter as its year-ago column (rev 8,965.64 lakh, PAT 73.63 lakh) — an independent second document.",
    "20241231": "own std XBRL INDAS_119375_1376564_10022025 (name+symbol verified, OneD 2024-10-01..2024-12-31): rev 136.9005, PAT 0.2553, printed 9M rev 284.4052 == Q1+Q2+Q3 EXACT. Announce date = NSE broadCastDate 10-Feb-2025 (board meeting 2025-02-10); ann was the 0 date-unknown sentinel.",
    "20250930": "own integrated-filing XBRL INTEGRATED_FILING_INDAS_1573530_13112025 + its printed statement. The quarter's current-tax cell is BLANK so Net Profit was printed equal to PBT (24.10 lakh). The filing's OWN Basic EPS for that column is 1.24 -> 12.40 lakh on 1,000,000 shares. H1 75.39-63.01 == 12.38; 9M 138.61-63.01-63.22 == 12.38 (Dec-25 filing). -> 0.1238 cr.",
}

# fund row = [qe, npStd, annStd, npCon, annCon]
FUND_NEW = {                       # rows that must be CREATED (quarter absent entirely)
    "20240630": {"pat": 0.62, "ann": 20240812},
    "20240930": {"pat": 0.74, "ann": 20241113},
}
FUND_ANN = {                       # announce-date corrections on existing rows
    "20241231": {"pat_is": 0.26, "was": 0, "now": 20250210},
    "20240331": {"pat_is": 0.32, "was": 20240527, "now": 20240530},
}
FUND_PAT = {                       # §2b value corrections on existing rows
    "20250930": {"was": 0.24, "now": 0.12, "ann_is": 20251113},
}
REV_FILL = {                       # sf_revop idx0 (revStd) fills — all were None
    "20240331": 62.47,
    "20240630": 57.85,
    "20240930": 89.66,
    "20241231": 136.9,
}
MIRROR = {                         # sf_revop idx4 (patStd) — mirror of npStd (§70)
    "20240630": {"was": None, "now": 0.62},
    "20240930": {"was": None, "now": 0.74},
    "20250930": {"was": 0.24, "now": 0.12},
}


def load(rel):
    return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))


def dump(rel, obj):
    p = os.path.join(ROOT, rel)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, p)


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= TOL


problems, skipped, plan = [], [], []
orig = {rel: load(rel) for rel in FUND_TWINS + REVOP_TWINS}
work = {rel: copy.deepcopy(orig[rel]) for rel in orig}
expect = {rel: set() for rel in orig}


def frow(d, qe):
    return next((r for r in d.get(SYM, []) if isinstance(r, list) and r and r[0] == int(qe)), None)


# ---- fund twins -------------------------------------------------------------
for rel in FUND_TWINS:
    d = work[rel]
    rows = d.get(SYM)
    if not rows:
        problems.append("%s: no %s rows at all" % (rel, SYM)); continue

    for qe, e in sorted(FUND_NEW.items()):
        if frow(d, qe) is not None:
            skipped.append("%s %s row already exists" % (rel, qe)); continue
        rows.append([int(qe), e["pat"], e["ann"], None, None])
        plan.append((rel, qe, "NEW ROW", None, "%s ann=%s" % (e["pat"], e["ann"])))
        expect[rel].add(str(qe))

    for qe, e in sorted(FUND_ANN.items()):
        r = frow(d, qe)
        if r is None:
            problems.append("%s %s: row missing (ann fix)" % (rel, qe)); continue
        if not close(r[1], e["pat_is"]):
            problems.append("%s %s: ANN-FIX PAT GUARD FAILED npStd=%s expected %s"
                            % (rel, qe, r[1], e["pat_is"])); continue
        if r[2] == e["now"]:
            skipped.append("%s %s ann already %s" % (rel, qe, e["now"])); continue
        if r[2] != e["was"]:
            problems.append("%s %s: ANN GUARD FAILED ann=%s expected %s"
                            % (rel, qe, r[2], e["was"])); continue
        r[2] = e["now"]
        plan.append((rel, qe, "annStd", e["was"], e["now"]))
        expect[rel].add(str(qe))

    for qe, e in sorted(FUND_PAT.items()):
        r = frow(d, qe)
        if r is None:
            problems.append("%s %s: row missing (pat fix)" % (rel, qe)); continue
        if close(r[1], e["now"]):
            skipped.append("%s %s npStd already %s" % (rel, qe, e["now"])); continue
        if not close(r[1], e["was"]):
            problems.append("%s %s: PAT GUARD FAILED npStd=%s expected %s"
                            % (rel, qe, r[1], e["was"])); continue
        if r[2] != e["ann_is"]:
            problems.append("%s %s: PAT-FIX ANN GUARD FAILED ann=%s expected %s"
                            % (rel, qe, r[2], e["ann_is"])); continue
        r[1] = e["now"]
        plan.append((rel, qe, "npStd", e["was"], e["now"]))
        expect[rel].add(str(qe))

    rows.sort(key=lambda r: r[0])

# ---- revop twins ------------------------------------------------------------
def rcell(d, rel, qe, create):
    c = (d.get(SYM) or {}).get(qe)
    if c is None and create:
        c = [None, None, None, None, None, None, 0, None, None]
        d.setdefault(SYM, {})[qe] = c
    if c is not None and len(c) < 9:
        c += [None] * (9 - len(c))
    return c

for rel in REVOP_TWINS:
    d = work[rel]
    for qe, val in sorted(REV_FILL.items()):
        c = rcell(d, rel, qe, create=True)
        if close(c[0], val):
            skipped.append("%s %s revS already %s" % (rel, qe, val)); continue
        if c[0] is not None:
            problems.append("%s %s: REV GUARD FAILED revS=%s (fill-only, expected None)"
                            % (rel, qe, c[0])); continue
        c[0] = val
        plan.append((rel, qe, "revS", None, val))
        expect[rel].add(qe)
    for qe, e in sorted(MIRROR.items()):
        c = rcell(d, rel, qe, create=True)
        if close(c[4], e["now"]):
            skipped.append("%s %s patS already %s" % (rel, qe, e["now"])); continue
        if c[4] is not None and not close(c[4], e["was"]):
            problems.append("%s %s: MIRROR GUARD FAILED patS=%s expected %s"
                            % (rel, qe, c[4], e["was"])); continue
        prev = c[4]
        c[4] = e["now"]
        plan.append((rel, qe, "patS", prev, e["now"]))
        expect[rel].add(qe)

# ---- blast radius -----------------------------------------------------------
for rel in orig:
    b, a = orig[rel], work[rel]
    diffs = set()
    for sym in set(b) | set(a):
        x, y = b.get(sym), a.get(sym)
        if x == y:
            continue
        if sym != SYM:
            diffs.add((sym, "OTHER-SYMBOL")); continue
        if isinstance(x, dict) and isinstance(y, dict):
            for q in set(x) | set(y):
                if x.get(q) != y.get(q):
                    diffs.add((sym, q))
        elif isinstance(x, list) and isinstance(y, list):
            xb = {r[0]: r for r in x}
            yb = {r[0]: r for r in y}
            for q in set(xb) | set(yb):
                if xb.get(q) != yb.get(q):
                    diffs.add((sym, str(q)))
        else:
            diffs.add((sym, "WHOLE"))
    stray = {d for d in diffs if d[1] not in expect[rel]}
    if stray:
        problems.append("%s: BLAST RADIUS stray diffs %s" % (rel, sorted(stray)[:8]))

print("planned edits: %d   skipped(already-correct): %d   problems: %d"
      % (len(plan), len(skipped), len(problems)))
for p in plan:
    print("  EDIT", p)
for s in skipped:
    print("  SKIP", s)
for p in problems:
    print("  PROBLEM", p)
if problems:
    sys.exit(1)
if "--apply" not in sys.argv:
    print("DRY RUN - nothing written"); sys.exit(0)

for rel in orig:
    dump(rel, work[rel])

# ---- journals ---------------------------------------------------------------
pd = load("scripts/pat_defects.json")
for qe, e in FUND_NEW.items():
    ent = pd.setdefault(SYM, {}).setdefault(qe, {})
    ent.update({"stored_pat": None, "correct_pat": e["pat"],
                "defect": "wrong-company series gap (KALYANI->BSE 544023 Kalyani Cast-Tech); quarter was absent",
                "source": SRC[qe]})
for qe, e in FUND_PAT.items():
    ent = pd.setdefault(SYM, {}).setdefault(qe, {})
    ent.update({"stored_pat": e["was"], "correct_pat": e["now"],
                "defect": "filer printed PAT==PBT (blank quarter tax cell); own EPS + H1/9M chains arbitrate",
                "source": SRC[qe]})
for qe, e in FUND_ANN.items():
    ent = pd.setdefault(SYM, {}).setdefault(qe, {})
    ent.setdefault("correct_pat", e["pat_is"])
    ent.setdefault("stored_pat", e["pat_is"])
    ent["ann_was"], ent["ann_now"] = e["was"], e["now"]
    ent["ann_source"] = SRC[qe]
dump("scripts/pat_defects.json", pd)

rd = load("scripts/rev_defects.json")
for qe, val in REV_FILL.items():
    ent = rd.setdefault(SYM, {}).setdefault(qe, {})
    ent.update({"stored_rev": None, "correct_rev": val, "basis": "std",
                "defect": "revenue slot empty while the wrong company (BSE 544023) supplied the PAT",
                "source": SRC[qe]})
dump("scripts/rev_defects.json", rd)

mh_path = os.path.join(HERE, "stdpat_mirror_heals.json")
mh = json.load(open(mh_path, encoding="utf-8"))
for qe, e in MIRROR.items():
    mh["%s|%s" % (SYM, qe)] = {"patS": e["now"], "was_mirror": e["was"],
                               "verdict": "kalyani_series_closeout"}
json.dump(mh, open(mh_path, "w", encoding="utf-8"), indent=1, sort_keys=True)

al = load("scripts/ann_date_fills.json")
al["%s|%s" % (SYM, "20241231")] = {"ann": 20250210, "src": "nse:own-filing broadCastDate 10-Feb-2025 (KALYANI wrong-company closeout)"}
dump("scripts/ann_date_fills.json", al)

print("APPLIED %d edits + journals" % len(plan))

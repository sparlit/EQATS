# -*- coding: utf-8 -*-
"""VERIFY THE WHOLE STORED REVENUE SERIES against Moneycontrol  (user's idea, 2026-08-11)

§72's verify campaign was throttled by REACH: the external sites it could use covered only ~10 of
our 95 quarters, so most of the store had no second opinion at all. Moneycontrol changes that —
`appfeeds.moneycontrol.com/jsonapi/stocks/quarterly_results_responsive` returns **60 quarters per
company per basis at filing precision** (see mc_quarterly_fetch.py for the endpoint and the §49
symbol-resolution trap). That is deep enough to audit essentially the entire revenue store.

WHAT THIS IS AND IS NOT. It is a DETECTOR that produces adjudication candidates. It is NOT an
auto-healer, and a disagreement never means "we are wrong" on its own — §71's lesson is that the
source you reach for as truth can be the corrupted one. Three things produce a disagreement:
  1. a defect in OUR cell,
  2. a defect in MONEYCONTROL's cell,
  3. neither — a different ENTITY or BASIS (demerger, restatement, holdco vs opco), which shows up
     as the series disagreeing broadly rather than at isolated points.

★ THE DISCRIMINATOR — series identity first, then isolated points.
Per (symbol, basis) we first ask whether Moneycontrol is even describing the same series: how many
of our stored quarters it reproduces, and how many it contradicts.

    agree >= MIN_AGREE and disagree == 0            -> CLEAN. Series confirmed end to end.
    agree >= MIN_AGREE and disagree small (<=3)     -> ★ SUSPECT CELLS. The series identity is
                                                       proven by the agreeing quarters, so the few
                                                       disagreeing ones are strong defect
                                                       candidates on one side or the other.
    agree < MIN_AGREE                               -> DIFFERENT SERIES. Report as unusable for
                                                       this company; do NOT mine it for cells.
                                                       (screener's TMPV failure mode, §60c.)

That middle bucket is the whole point: it is what caught SWANCORP for screener, where 11 of 12
quarters matched and the single disagreement turned out to be OUR bad cell.

Output: scripts/fill2020_tools/_mc_verify.json — per company/basis verdict plus every disagreeing
quarter with both values and the relative gap. Nothing is written to the dataset.

Run: python -X utf8 scripts/fill2020_tools/mc_verify_store.py [--limit N] [--only SYM,SYM]
     [--members] (restrict to point-in-time N500 members, the audited universe)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)

import mc_quarterly_fetch as MC                                   # noqa: E402

REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
OUT = os.path.join(HERE, "_mc_verify.json")

MIN_AGREE = 6            # below this we cannot claim the series is the same one
MAX_SUSPECT = 3          # more isolated disagreements than this = probably a different series
TOL_ABS, TOL_REL = 0.05, 0.002


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    members_only = "--members" in argv

    revop = json.load(open(REVOP))
    syms = sorted(revop)
    if members_only:
        idx = json.load(open(os.path.join(SCRIPTS, "indices_history.json")))
        mem = set()
        for snap in idx["Nifty 500"]:
            mem.update(s for s in snap["symbols"] if not s.upper().startswith("DUMMY"))
        syms = [s for s in syms if s in mem]
    if only:
        syms = [s for s in syms if s in only]
    if limit:
        syms = syms[:limit]

    codes = json.load(open(MC.CODES)) if os.path.exists(MC.CODES) else {}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    print("verifying %d symbols x 2 bases against moneycontrol" % len(syms), flush=True)

    tot = {"clean": 0, "suspect": 0, "different": 0, "nodata": 0}
    suspects = []
    for n, sym in enumerate(syms, 1):
        for basis in ("std", "con"):
            key = "%s|%s" % (sym, basis)
            if key in out:
                tot[out[key]["verdict"]] = tot.get(out[key]["verdict"], 0) + 1
                continue
            ours = {int(q): r[MC.SLOT[basis]] for q, r in (revop.get(sym) or {}).items()
                    if len(r) > MC.SLOT[basis] and r[MC.SLOT[basis]] is not None}
            if len(ours) < MIN_AGREE:
                continue
            pre = sym in codes
            code = MC.resolve_code(sym, codes)
            if not pre:
                MC._jitter(0.4, 0.9)
            if not code:
                out[key] = {"verdict": "nodata", "why": "no verified moneycontrol code"}
                tot["nodata"] += 1
                continue
            mc = MC.series(code, basis)
            MC._jitter()
            if not mc:
                out[key] = {"verdict": "nodata", "why": "empty series"}
                tot["nodata"] += 1
                continue
            agree, dis = [], []
            for qe, v in sorted(ours.items()):
                if qe not in mc:
                    continue
                m = mc[qe]
                if abs(m - v) <= max(TOL_ABS, TOL_REL * max(abs(v), abs(m))):
                    agree.append(qe)
                else:
                    dis.append({"qe": qe, "ours": round(v, 2), "mc": round(m, 2),
                                "gap_pct": round(100.0 * (m - v) / max(abs(v), 1e-9), 2)})
            if len(agree) < MIN_AGREE:
                verdict = "different"
            elif not dis:
                verdict = "clean"
            elif len(dis) <= MAX_SUSPECT:
                verdict = "suspect"
            else:
                verdict = "different"
            out[key] = {"verdict": verdict, "sc_id": code, "agree": len(agree),
                        "overlap": len(agree) + len(dis), "disagreements": dis[:12]}
            tot[verdict] = tot.get(verdict, 0) + 1
            if verdict == "suspect":
                for d in dis:
                    suspects.append((sym, basis, d))
                print("SUSPECT %-12s %-3s  agree %-3d  %s" % (
                    sym, basis, len(agree),
                    "; ".join("%d ours %.2f vs mc %.2f (%+.1f%%)"
                              % (d["qe"], d["ours"], d["mc"], d["gap_pct"]) for d in dis[:3])),
                    flush=True)
        if n % 15 == 0:
            json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
            json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
            print("  [%d/%d] %s" % (n, len(syms), tot), flush=True)

    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
    print("\nVERDICTS: %s" % tot)
    print("suspect cells (candidates for adjudication, NOT auto-heals): %d" % len(suspects))


if __name__ == "__main__":
    main()

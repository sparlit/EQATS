# -*- coding: utf-8 -*-
"""Test the NOT-APPLICABLE classification against screener. Does the company really not file con?

User, 2026-08-07: *"check na ones once again. dont assume"*. Right to push, because the rule has a
circularity in it.

THE SUSPECT LOGIC. audit_coverage marks a consolidated cell not-applicable when the company shows
no DIVERGENCE between stored con and std PAT in the trailing four quarters. Divergence is read from
sf_fundamentals -- so a company whose con PAT is simply MISSING produces no divergence signal and is
classified as "does not file consolidated". That is circular: we conclude the data does not exist
because we do not hold it. Pre-2020 is exactly where con PAT is thinnest, and exactly where the n/a
counts are largest (~190-220 companies per quarter before Jun-2018).

THE TEST. screener's ANNUAL P&L goes back to FY2015 on both bases. For a company that genuinely
files no consolidated accounts, screener's consolidated page either does not exist or simply mirrors
the standalone figures. So for each n/a cell:

    screener con annual for that FY  vs  screener std annual for the same FY
      differs materially  -> the company DOES report consolidated -> our n/a is WRONG
      identical / absent  -> consistent with not filing consolidated -> n/a stands

This is an independent source deciding it, not our own stored data deciding it about itself.

  python -X utf8 scripts/fill2020_tools/verify_na_classification.py [--limit N] [--year 2017]
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF                                       # noqa: E402

LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}
OUT = "/tmp/na_verify.json"


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def back4(qe):
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    s = set()
    for k in range(4):
        yy, r = divmod(i - k, 4)
        mm = [3, 6, 9, 12][r]
        s.add(yy * 10000 + mm * 100 + LAST_DAY[mm])
    return s


def fy_of(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return y + 1 if m > 3 else y


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 250
    idx = load("scripts/indices_history.json")
    rmap = load("scripts/_rename_map.json")
    revop = load("docs/sf_revop.json")
    fund_raw = load("docs/sf_fundamentals.json")
    nc = load("scripts/no_con_filing.json")
    never = set(nc.get("never_filed_con", []))
    stopped = nc.get("stopped_filing_con", {})

    divq = {}
    for s, rows in fund_raw.items():
        d = [r[0] for r in rows if len(r) > 3 and r[1] is not None and r[3] is not None
             and abs(r[3] - r[1]) > max(0.05, abs(r[1]) * 0.001)]
        if d:
            divq[s] = set(d)

    def resolve(sym):
        cur, seen = sym, set()
        while cur not in revop:
            if cur in seen or cur not in rmap:
                return None
            seen.add(cur)
            cur = rmap[cur]
        return cur

    snaps = sorted(idx["Nifty 500"], key=lambda s: s["effectiveDate"])

    def members_at(qe):
        ds = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        best = None
        for s in snaps:
            if s["effectiveDate"] <= ds:
                best = s
            else:
                break
        return [x for x in (best or snaps[0])["symbols"] if not x.upper().startswith("DUMMY")]

    # collect n/a consolidated-revenue cells in 2015-2019, one per company/FY to keep it cheap
    quarters = []
    for y in range(2015, 2020):
        for m in (3, 6, 9, 12):
            quarters.append(y * 10000 + m * 100 + LAST_DAY[m])
    seen_pair, cells = set(), []
    for qe in quarters:
        for sym in members_at(qe):
            k = resolve(sym)
            if not k:
                continue
            row = (revop.get(k) or {}).get(str(qe))
            if not row or len(row) < 2 or row[1] is not None:
                continue                      # only cells that are EMPTY on the con side
            # reproduce the audit's n/a decision
            na = False
            reason = ""
            if k in never:
                na, reason = True, "ledger: never_filed_con"
            elif stopped.get(k) and qe >= stopped[k]:
                na, reason = True, "ledger: stopped_filing_con"
            elif not (divq.get(k, set()) & back4(qe)):
                na, reason = True, "no con/std divergence in trailing 4 quarters"
            if not na:
                continue
            pair = (k, fy_of(qe))
            if pair in seen_pair:
                continue
            seen_pair.add(pair)
            cells.append((k, qe, fy_of(qe), reason))

    print("n/a consolidated-revenue cells 2015-2019: %d company/FY pairs to test\n" % len(cells))
    res, cache = {}, {}
    wrong, stands, nodata = [], 0, 0
    for k, qe, fy, reason in cells[:limit]:
        if k not in cache:
            try:
                cache[k] = (SF.annuals(k, con=True), SF.annuals(k, con=False))
            except Exception:
                cache[k] = ({}, {})
        acon, astd = cache[k]
        dk = "%d-03-31" % fy
        lab_c = next((L for L in ("Sales", "Revenue") if any(L in r for r in acon.values())), None) if acon else None
        lab_s = next((L for L in ("Sales", "Revenue") if any(L in r for r in astd.values())), None) if astd else None
        vc = (acon.get(dk) or {}).get(lab_c) if lab_c else None
        vs = (astd.get(dk) or {}).get(lab_s) if lab_s else None
        if vc is None or vs is None:
            nodata += 1
            res["%s|%d" % (k, fy)] = {"verdict": "NO-SCREENER-ANNUAL", "reason": reason}
            continue
        if abs(vc - vs) > max(1.0, abs(vs) * 0.01):
            wrong.append((k, fy, qe, vs, vc, reason))
            res["%s|%d" % (k, fy)] = {"verdict": "NA-IS-WRONG", "std_annual": vs,
                                      "con_annual": vc, "reason": reason}
        else:
            stands += 1
            res["%s|%d" % (k, fy)] = {"verdict": "NA-STANDS", "std_annual": vs,
                                      "con_annual": vc, "reason": reason}
    json.dump(res, open(OUT, "w"), indent=1)

    tested = len(wrong) + stands
    print("tested %d company/FY pairs (screener has both annuals)" % tested)
    print("  NA-IS-WRONG : %d  screener's consolidated annual DIFFERS from standalone"
          % len(wrong))
    print("  NA-STANDS   : %d  consolidated == standalone, or no consolidated page" % stands)
    print("  no screener annual for that FY: %d" % nodata)
    if tested:
        print("\n  => %.0f%% of the n/a classification is WRONG on this sample"
              % (100.0 * len(wrong) / tested))
    print("\nworst offenders (company DOES report consolidated, we marked it n/a):")
    for k, fy, qe, vs, vc, reason in sorted(wrong, key=lambda w: -abs(w[4] - w[3]))[:25]:
        print("   %-12s FY%d  std annual %-12.1f con annual %-12.1f  (%s)" % (k, fy, vs, vc, reason))
    print("\n-> %s" % OUT)


if __name__ == "__main__":
    main()

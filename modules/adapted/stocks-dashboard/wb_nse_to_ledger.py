# -*- coding: utf-8 -*-
"""Turn wb_nse_results.py proposals into the campaign's own pre2015 ledger shape.

Gate letter is **E**: the proof that carries the value is the page's own EPS identity, which is
exactly PRE2015_CAMPAIGN.md's GATE E ("EPS x (Equity Capital / Face Value) - PAT"). G1-G4 are
preconditions on WHICH page and WHICH period, not an extra proof, so calling this anything else
would overstate it. The full G1-G5 detail rides in `src`.

ann: LANDING RULES 6 -- no source in this era carries a filing date, so quarter-end + 45 days with
`ann_approx: true`, then the §99 pre-listing floor at the symbol's first traded bar, EXCEPT where
the symbol's own earlier stored rows already carry real announce dates before that bar (a tape /
rename seam, not a listing -- the BBOX case, see apply_agg_pat_fills.ann_for).
"""
import argparse, datetime, json, os, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--props", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    props = json.load(open(a.props))["proposals"]
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    fb = json.load(open(os.path.join(HERE, "agg_tools", "_first_bar.json")))["first_bar"]
    fb = {s: int(v.replace("-", "")) for s, v in fb.items()}

    out, floored, seam = collections.defaultdict(dict), [], []
    for key, p in sorted(props.items()):
        sym, qe, _ = key.split("|")
        qe = int(qe)
        d = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100) + datetime.timedelta(days=45)
        ann = d.year * 10000 + d.month * 100 + d.day
        note, bar = None, fb.get(sym)
        if bar and bar > ann:
            earlier = [r for r in fund.get(sym, []) if r[0] < qe and r[2] and 0 < r[2] < bar]
            if earlier:
                note = ("first bar %d is after qe+45d, but %d earlier stored rows carry REAL announce "
                        "dates before it -> tape/rename seam, §99 floor NOT applied" % (bar, len(earlier)))
                seam.append("%s %d" % (sym, qe))
            else:
                note = "qe+45d %d FLOORED UP to the first traded bar %d (pre-listing, §99)" % (ann, bar)
                ann = bar
                floored.append("%s %d -> %d" % (sym, qe, bar))
        out[sym][str(qe)] = {
            "pat": p["value"], "rev": None, "op": None, "basis": "std",
            "fin": 1 if p.get("bank") else 0, "derived": None, "gate": "E",
            "ann": ann, "ann_approx": True, "ann_floor": note,
            "capture": p.get("capture"), "stepw_class": p.get("stepw_class"),
            "src": p["evidence"],
        }
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    n = sum(len(v) for v in out.values())
    print("ledger: %d symbols / %d cells -> %s" % (len(out), n, a.out))
    print("  banking-schema cells: %d" % sum(1 for v in out.values() for c in v.values() if c["fin"]))
    print("  ann floored to first bar: %d %s" % (len(floored), floored[:6]))
    print("  floor skipped as a tape seam: %d %s" % (len(seam), seam[:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

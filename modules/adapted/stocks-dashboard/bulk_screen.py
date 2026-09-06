# -*- coding: utf-8 -*-
"""P4 phase A — ZERO-NETWORK screens over the WHOLE store, to aim the crawl.

The site sweep is the expensive half of P4 (~4 hours at a polite 2s). These detectors cost nothing,
run over all ~3,600 symbols in seconds, and say WHERE to spend it. Each one is a shape this campaign
has already PROVEN produces real defects, so none of them is speculative:

  S1 CON-COPY        con == std exactly, in revenue or PAT, for a company independently evidenced to
                     FILE consolidated. Proven on GICRE revenue (Jun-2024 filed 12886.47 against a
                     stored 12822.55 copied from standalone).
                     ⚠️ Deliberately has NO materiality floor. `detect_con_copy.py` requires the
                     site's own con/std gap to exceed 2% before it will flag, and BOTH confirmed
                     GICRE revenue defects sat UNDER that bar (149 and 63 against thresholds of 264
                     and 256). The 2% floor is why they were never caught.
  S2 STORE-SPLIT     sf_fundamentals (authoritative) vs the sf_revop PAT mirror disagree. Proven to
                     contain real defects in BOTH directions -- for GICRE Jun/Sep-2025 the MIRROR
                     held the correct value and the authoritative file was wrong.
  S3 SCALE           a cell 10x/100x off the running median of the SAME series. Never the median of
                     the whole series -- a median is not a scale reference for a trending series
                     (runbook 22g: that rule ran 99.3% false positives on holder counts).
  S4 YTD-AS-QUARTER  a quarter that equals the sum of the preceding quarters of its fiscal year --
                     the §45/T-D trap where a year-to-date column is stored as the quarter.
  S5 REPEAT          a value identical to the SAME quarter one year earlier, to the paisa -- the
                     comparative-column year-shift fingerprint (§45). `yshift_genuine.json` holds
                     the proven-innocent pairs and is subtracted.

Output ranks SYMBOLS, not cells, because the crawl is per-symbol: one page fetch tests every
quarter that symbol has.

  python3 -X utf8 scripts/revpat_verify/bulk_screen.py --out bulk_candidates.json
"""
import os, json, csv, argparse, collections, statistics

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def jload(rel, default=None):
    p = os.path.join(TREE, rel)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def fy_of(qe):
    """Indian fiscal year label for a YYYYMMDD quarter-end (Apr-Mar)."""
    y, m = qe // 10000, (qe // 100) % 100
    return y + 1 if m > 3 else y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bulk_candidates.json")
    ap.add_argument("--csv", default="")
    a = ap.parse_args()

    revop = jload("docs/sf_revop.json", {})
    fund = jload("docs/sf_fundamentals.json", {})
    ev = jload("scripts/con_filer_evidence.json", {}) or {}
    genuine = jload("scripts/yshift_genuine.json", {}) or {}
    IH = jload("scripts/indices_history.json", {}) or {}
    RMAP = jload("scripts/_rename_map.json", {}) or {}

    con_filers = {s for s, v in ev.items() if isinstance(v, dict) and v.get("files_con")}

    def norm(s):
        s = str(s).strip().upper(); seen = set()
        while s in RMAP and s not in seen and RMAP[s] != s:
            seen.add(s); s = RMAP[s]
        return s

    snaps = sorted(IH.get("Nifty 500", []), key=lambda x: x["effectiveDate"])
    current_n500 = {norm(x) for x in snaps[-1]["symbols"]} if snaps else set()

    patf = collections.defaultdict(dict)
    for s, rows in fund.items():
        for r in rows:
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int):
                patf[s][r[0]] = (r[1], r[3])

    gset = set()
    if isinstance(genuine, dict):
        for k, v in genuine.items():
            gset.add(k if "|" in str(k) else "%s|%s" % (k, v))

    hits = collections.defaultdict(lambda: collections.defaultdict(list))

    for sym, d in revop.items():
        qs = sorted(int(q) for q in d)
        series = {"revS": {}, "revC": {}, "patS": {}, "patC": {}}
        for q in qs:
            row = d[str(q)]
            series["revS"][q], series["revC"][q] = row[0], row[1]
            ps, pc = patf.get(sym, {}).get(q, (None, None))
            series["patS"][q], series["patC"][q] = ps, pc

            # S1 -- con == std exactly, for an evidenced consolidated filer. NO materiality floor.
            if sym in con_filers:
                for a_, b_, lbl in ((row[0], row[1], "rev"), (ps, pc, "pat")):
                    if a_ is not None and b_ is not None and abs(a_) > 1 and abs(a_ - b_) <= 0.005:
                        hits[sym]["S1_con_copy"].append("%d:%s" % (q, lbl))

            # S2 -- the two stores disagree about the same quantity
            for idx, pi, lbl in ((4, 0, "std"), (5, 1, "con")):
                mirror = row[idx]
                auth = (patf.get(sym, {}).get(q) or (None, None))[pi]
                if mirror is not None and auth is not None and \
                        abs(mirror - auth) > max(0.5, abs(auth) * 0.005):
                    hits[sym]["S2_store_split"].append("%d:%s" % (q, lbl))

        for fld, ser in series.items():
            vals = [(q, v) for q, v in sorted(ser.items()) if v is not None]
            if len(vals) < 6:
                continue
            # S3 -- power-of-ten against the running median of EARLIER values only
            for i, (q, v) in enumerate(vals):
                if i < 4 or abs(v) < 1:
                    continue
                prior = [abs(x) for _, x in vals[max(0, i - 8):i] if abs(x) > 1]
                if len(prior) < 4:
                    continue
                med = statistics.median(prior)
                if med > 1:
                    r = abs(v) / med
                    if r > 8 or r < 0.125:
                        hits[sym]["S3_scale"].append("%d:%s:x%.0f" % (q, fld, r if r > 1 else -1 / r))
            # S4 -- a quarter equal to the sum of its fiscal year's earlier quarters (YTD stored as Q)
            byfy = collections.defaultdict(list)
            for q, v in vals:
                byfy[fy_of(q)].append((q, v))
            for fy, qv in byfy.items():
                if len(qv) < 3:
                    continue
                qv.sort()
                for i in range(2, len(qv)):
                    prev = sum(x for _, x in qv[:i])
                    cur = qv[i][1]
                    if abs(prev) > 5 and abs(cur - prev) <= max(0.5, abs(prev) * 0.002):
                        hits[sym]["S4_ytd_as_quarter"].append("%d:%s" % (qv[i][0], fld))
            # S5 -- identical to the same quarter one year earlier
            m = dict(vals)
            for q, v in vals:
                if abs(v) > 0.5 and (q - 10000) in m and abs(m[q - 10000] - v) <= 0.005:
                    if "%s|%d" % (sym, q) not in gset and "%s|%d" % (sym, q - 10000) not in gset:
                        hits[sym]["S5_repeat_yoy"].append("%d:%s" % (q, fld))

    W = {"S1_con_copy": 3, "S2_store_split": 5, "S3_scale": 4,
         "S4_ytd_as_quarter": 4, "S5_repeat_yoy": 2}
    ranked = []
    for sym, h in hits.items():
        score = sum(W[k] * min(len(v), 12) for k, v in h.items())
        if sym in current_n500:
            score = int(score * 1.5)                     # importance, not suspicion
        ranked.append({"sym": sym, "score": score, "in_n500": sym in current_n500,
                       "counts": {k: len(v) for k, v in h.items()},
                       "examples": {k: v[:6] for k, v in h.items()}})
    ranked.sort(key=lambda r: (-r["score"], r["sym"]))

    tot = collections.Counter()
    for r in ranked:
        for k, n in r["counts"].items():
            tot[k] += n

    doc = {"_meta": {"universe": len(revop), "symbols_flagged": len(ranked),
                     "cells_by_screen": dict(tot), "weights": W,
                     "note": "a flag is a place to LOOK, never a defect -- every screen in this "
                             "campaign has produced false positives as well as real defects"},
           "candidates": ranked}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["rank", "sym", "score", "in_n500"] + sorted(W))
            for i, r in enumerate(ranked, 1):
                w.writerow([i, r["sym"], r["score"], r["in_n500"]] +
                           [r["counts"].get(k, 0) for k in sorted(W)])

    print("universe: %d symbols | flagged: %d" % (len(revop), len(ranked)))
    print("cells by screen: %s" % dict(tot))
    print("\ntop 25 candidates:")
    print("  %-13s %6s %6s  %s" % ("sym", "score", "n500", "screens"))
    for r in ranked[:25]:
        print("  %-13s %6d %6s  %s" % (r["sym"], r["score"], "Y" if r["in_n500"] else "",
                                       ", ".join("%s=%d" % (k.split("_", 1)[1], v)
                                                 for k, v in sorted(r["counts"].items()))))
    print("\nwrote %s" % a.out)


if __name__ == "__main__":
    main()

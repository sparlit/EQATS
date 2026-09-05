# -*- coding: utf-8 -*-
"""Draw a stratified sample of suspect cells for the std-slot-holds-con audit.

Strata: era (4 bands) x size (revenue quartile of the company in that era).
Size proxy = median quarterly standalone revenue from sf_revop over the 8 quarters around the
cell (falls back to the company's whole series, then to |PAT| when revenue is absent).
Fixed seed so the draw is reproducible.
"""
import json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FUND = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
REVOP = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
SCREEN = json.load(open(os.path.join(HERE, "_screen.json")))
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40


def qshift(qe, k):
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m] + k
    y2, mi = divmod(i, 4)
    m2 = [3, 6, 9, 12][mi]
    return y2 * 10000 + m2 * 100 + [31, 30, 30, 31][mi]


def size_of(sym, qe):
    rv = REVOP.get(sym) or {}
    near = [rv[str(qshift(qe, k))][0] for k in range(-4, 5)
            if str(qshift(qe, k)) in rv and rv[str(qshift(qe, k))][0] is not None]
    if not near:
        near = [v[0] for v in rv.values() if v and v[0] is not None]
    if near:
        return statistics.median(near)
    pats = [abs(r[1]) for r in FUND.get(sym, []) if r[1] is not None]
    return statistics.median(pats) * 4 if pats else 0.0


def era_band(qe):
    y = qe // 10000
    if y <= 2018:
        return "pre2019"
    if y <= 2021:
        return "2019-21"
    if y <= 2023:
        return "2022-23"
    return "2024-26"


def main():
    cells = []
    for sym, v in SCREEN.items():
        for qe in v["cells"]:
            cells.append({"sym": sym, "qe": qe, "size": round(size_of(sym, qe), 2),
                          "era": era_band(qe)})
    sizes = sorted(c["size"] for c in cells)
    qs = [sizes[int(len(sizes) * f)] for f in (0.25, 0.5, 0.75)]
    for c in cells:
        c["sz"] = ("micro" if c["size"] <= qs[0] else "small" if c["size"] <= qs[1]
                   else "mid" if c["size"] <= qs[2] else "large")
    print("population %d cells; revenue quartile cuts (cr/qtr): %s" %
          (len(cells), [round(q, 1) for q in qs]))
    strata = {}
    for c in cells:
        strata.setdefault((c["era"], c["sz"]), []).append(c)
    rnd = random.Random(20260806)
    # proportional-ish but with a floor of 2 per non-empty stratum so thin cells still get looked at
    order = sorted(strata, key=lambda k: -len(strata[k]))
    pick, remaining = [], N
    floor = {k: min(2, len(strata[k])) for k in order}
    remaining -= sum(floor.values())
    tot = sum(len(strata[k]) for k in order)
    for k in order:
        n = floor[k] + int(round(remaining * len(strata[k]) / tot))
        n = min(n, len(strata[k]))
        pick += rnd.sample(strata[k], n)
    pick = pick[:N]
    pick.sort(key=lambda c: (c["era"], c["sz"], c["sym"]))
    for k in order:
        print("  %-9s %-6s pop %4d  drawn %d" % (k[0], k[1], len(strata[k]),
              sum(1 for c in pick if (c["era"], c["sz"]) == k)))
    json.dump(pick, open(os.path.join(HERE, "_sample.json"), "w"), indent=1)
    print("\ndrawn %d cells -> _sample.json" % len(pick))
    for c in pick:
        print("  %-12s %d  %-7s %-5s rev~%.0f" % (c["sym"], c["qe"], c["era"], c["sz"], c["size"]))


main()

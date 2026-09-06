# -*- coding: utf-8 -*-
"""What the issuer-sweep landing actually BUYS — measured, not counted.

93e's rule: an alias that makes us "know what company this is" is a better diagnosis, not better
coverage. The number that matters is how many quarters the alias makes reachable DURING the old
key's own trading life, because that is the only era a screen would ever ask about it.

Reports three things:
  1. fundamentals reach — per newly-aliased old key, the target's dated quarters that fall inside
     the old key's bar range (announce date, the same gate postDrift uses);
  2. stranded price bars — the bars still sitting under a dead key that the price series has not
     merged, i.e. what a build_sf_data issuer-prefix merge path would recover;
  3. lookback truncation — for each confirmed pair, how much history the SURVIVING key is missing
     today (this is the harm: every 52w/RSI/return window on the new key starts at the seam).

Run:  python3 scripts/isin_seam_measure.py
"""
import gzip, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.path.join(HERE, "_live")


def ann_dates(rows):
    """Every announce date on a row that carries a profit — con (3,4) or std (1,2), as 93 does."""
    out = []
    for r in rows:
        for ni, ai in ((3, 4), (1, 2)):
            if r[ni] is not None and r[ai] and r[ai] > 0:
                out.append(r[ai])
                break
    return sorted(out)


def main():
    D = json.loads(gzip.decompress(open(os.path.join(LIVE, "p1_new.bin"), "rb").read()))
    data = D["data"]
    FUND = json.load(open(os.path.join(LIVE, "fund_live.json")))
    ALIAS = json.loads(re.search(r"^const FUND_ALIAS = (\{.*?\});$",
                                 open(os.path.join(ROOT, "docs", "backtest-engine.js"),
                                      encoding="utf-8").read(), re.M).group(1))
    V = json.load(open(os.path.join(HERE, "_isin_seam_verdicts.json")))
    S = json.load(open(os.path.join(HERE, "_isin_issuer_sweep.json")))
    keyrec = {(g["issuer"], k["key"]): k for g in S["groups"] for k in g["keys"]}

    seams = [s for s in V["seams"] if s["verdict"] in ("CONFIRMED", "SINGLE-LEG")]
    olds = sorted({s["old"] for s in seams})

    print("=== 1. fundamentals reach inside the OLD key's own trading life")
    hit = miss = noalias = 0
    rows_in_era = 0
    detail = []
    for o in olds:
        t = ALIAS.get(o)
        if not t:
            noalias += 1
            continue
        rec = next((k for (i, kk), k in keyrec.items() if kk == o), None)
        if not rec:
            continue
        lo, hi = rec["first"], rec["last"]
        ann = ann_dates(FUND.get(t, []))
        inside = [a for a in ann if lo <= a <= hi]
        rows_in_era += len(inside)
        if inside:
            hit += 1
            detail.append((o, t, lo, hi, len(inside), inside[0], inside[-1]))
        else:
            miss += 1
    print("  %d aliased old keys: %d have target quarters inside their era, %d have none, "
          "%d not aliased (reused-ticker refusal)" % (len(olds), hit, miss, noalias))
    print("  quarters made reachable in-era: %d" % rows_in_era)
    for d in sorted(detail, key=lambda x: -x[4]):
        print("    %-12s -> %-12s era %d..%d  %3d quarters (%d..%d)" % d)

    print("\n=== 2. price bars still stranded under a dead key (what a merge path would recover)")
    tot_bars = tot_keys = 0
    per = []
    for o in olds:
        rec = next((k for (i, kk), k in keyrec.items() if kk == o), None)
        if rec:
            tot_keys += 1
            tot_bars += rec["mainBars"]
            per.append((rec["mainBars"], o, rec["first"], rec["last"]))
    print("  %d dead keys, %d bars" % (tot_keys, tot_bars))
    for n, o, a, b in sorted(per, reverse=True)[:12]:
        print("    %-12s %5d bars  %d..%d" % (o, n, a, b))

    print("\n=== 3. lookback truncation on the SURVIVING key today")
    trunc = []
    for s in seams:
        nrec = keyrec.get((s["issuer"], s["new"]))
        orec = keyrec.get((s["issuer"], s["old"]))
        if not (nrec and orec):
            continue
        yrs = (nrec["first"] // 10000) - (orec["first"] // 10000)
        trunc.append((yrs, s["new"], nrec["first"], orec["first"], orec["mainBars"]))
    trunc.sort(reverse=True)
    print("  %d surviving keys start later than their own history by a median of %d years"
          % (len(trunc), sorted(y for y, *_ in trunc)[len(trunc) // 2]))
    for y, k, nf, of_, n in trunc[:12]:
        print("    %-12s starts %d, its own tape starts %d (%d yr, %d bars behind)"
              % (k, nf, of_, y, n))


if __name__ == "__main__":
    main()

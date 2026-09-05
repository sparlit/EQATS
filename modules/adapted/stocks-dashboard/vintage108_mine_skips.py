# -*- coding: utf-8 -*-
"""§108 detection signature (1), mined for free: a REFUSED fill IS a finding.

Runbook §108: SYNGENE's two defective cells sat in `_nsearch_skips.json` as
"pat-anchor 58.8 vs stored 66.7" / "66.5 vs 79.1" for a month — the NSE archive's AS-FILED page
disagreeing with the store is the same evidence the detres sweep goes and fetches, already on disk.

This collects every such refusal whose quarter falls in the FY16-FY17 window, across every skips
ledger in scripts/, so the detres sweep has an INDEPENDENT second reader to be corroborated by
(§108 signature 2 is "detres + a second source agreeing against the store"). Unlike the sweep it
also covers the CON basis, which detres cannot serve at all (§42).

OUT: scripts/_vintage108_anchor_refusals.json
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
QS = (20150630, 20150930, 20151231, 20160331, 20160630, 20160930, 20161231, 20170331)
PAT = re.compile(r"pat[- ]anchor\s+(-?[\d.]+)\s+vs\s+stored\s+(-?[\d.]+)", re.I)
KEY = re.compile(r"^([A-Z0-9&._-]+)\|(\d{8})\|(std|con)$", re.I)


def main():
    out = {}
    for path in sorted(glob.glob(os.path.join(HERE, "_*skips*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            km = KEY.match(str(k))
            if not km or int(km.group(2)) not in QS:
                continue
            m = PAT.search(json.dumps(v))
            if not m:
                continue
            anchor, stored = float(m.group(1)), float(m.group(2))
            out["%s|%s|%s" % (km.group(1).upper(), km.group(2), km.group(3).lower())] = {
                "ledger": os.path.basename(path), "as_filed_anchor": anchor, "stored": stored,
                "diff": round(anchor - stored, 4), "reason": v}
    json.dump({"_doc": __doc__.strip().splitlines()[0],
               "_window": list(QS), "refusals": out},
              open(os.path.join(HERE, "_vintage108_anchor_refusals.json"), "w"), indent=1)
    print("%d anchor refusals in the FY16-FY17 window (%d symbols, %d std / %d con)"
          % (len(out), len({k.split("|")[0] for k in out}),
             sum(1 for k in out if k.endswith("std")), sum(1 for k in out if k.endswith("con"))))


if __name__ == "__main__":
    main()

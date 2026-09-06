# -*- coding: utf-8 -*-
"""Close the §108 sweep's scrip-code REACH GAP — ISIN-gated, never by name or ticker coincidence.

bse_scrips.json's by_id is built from BSE's ACTIVE-equity scrape, so every symbol that has since
delisted or merged is simply absent (the survivorship gap, bse_scrips_delisted.json's own _doc).
Measured on this sweep: 148 of 1,082 candidate symbols (663 stored cells, 11% of the window) had
no code and were being recorded as an unmeasured gap.

THE GATE (§76, the KALYANI trap): a BSE `scrip_id` equal to our NSE ticker is a COINCIDENCE TO BE
DISPROVED. Resolution here is by ISIN only:
  * our side  — sf_stock_data.bin `meta[sym].isin` (the bhavcopy ISIN column);
  * BSE side  — _bse_master_all.json ISIN_NUMBER over all 10,786 scrips, delisted included.
  exact  : ISIN_NUMBER == our ISIN                              -> accepted
  prefix : same issuer (INE + 6), different security suffix     -> accepted ONLY when it is the
           issuer's single equity scrip, and recorded as the weaker gate (§95: a face-value
           change re-issues the ISIN for the SAME company; a different suffix on a DIFFERENT
           issuer prefix is a different company and is never accepted).
  Anything ambiguous (2+ candidate scrips) is left unresolved and reported, not guessed.

OUT: scripts/_vintage108_scrips_extra.json  {SYM: {scrip, isin, bse_isin, name, gate}}
"""
import json
import gzip
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bse_resolve  # noqa: E402

OUT = os.path.join(HERE, "_vintage108_scrips_extra.json")


def main():
    scan = json.load(open(os.path.join(HERE, "_vintage108_scan.json"), encoding="utf-8"))
    want = sorted(scan.get("no_scrip", {}))
    meta = json.loads(gzip.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"),
                                           "rb").read())).get("meta", {})
    master = json.load(open(os.path.join(HERE, "_bse_master_all.json"), encoding="utf-8"))

    by_isin, by_prefix = defaultdict(list), defaultdict(list)
    for r in master:
        if (r.get("Segment") or "").strip() != "Equity":
            continue
        isin = (r.get("ISIN_NUMBER") or "").strip().upper()
        if len(isin) != 12:
            continue
        by_isin[isin].append(r)
        by_prefix[isin[:9]].append(r)

    out, stats = {}, defaultdict(int)
    for sym in want:
        if bse_resolve.blocked(sym):
            stats["blocked-conflict"] += 1
            continue
        isin = (meta.get(sym, {}).get("isin") or "").strip().upper()
        if len(isin) != 12:
            stats["no-isin-our-side"] += 1
            continue
        hits = by_isin.get(isin) or []
        gate = "isin-exact"
        if not hits:
            hits = by_prefix.get(isin[:9]) or []
            gate = "isin-issuer-prefix"
        if not hits:
            stats["not-on-bse"] += 1
            continue
        codes = sorted({r["SCRIP_CD"] for r in hits})
        if len(codes) != 1:
            stats["ambiguous"] += 1
            print("  AMBIGUOUS %-12s %s -> %s" % (sym, isin, codes))
            continue
        out[sym] = {"scrip": codes[0], "isin": isin,
                    "bse_isin": (hits[0].get("ISIN_NUMBER") or "").strip(),
                    "name": hits[0].get("Scrip_Name"), "scrip_id": hits[0].get("scrip_id"),
                    "status": hits[0].get("Status"), "gate": gate}
        stats[gate] += 1

    json.dump({"_doc": __doc__.strip().splitlines()[0],
               "_gate": "ISIN-only (runbook 76); prefix tier per runbook 95",
               "resolved": out}, open(OUT, "w"), indent=1)
    print("resolved %d of %d unreachable symbols" % (len(out), len(want)))
    for k, v in sorted(stats.items()):
        print("   %-22s %d" % (k, v))


if __name__ == "__main__":
    main()

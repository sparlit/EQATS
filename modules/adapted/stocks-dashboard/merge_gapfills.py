# -*- coding: utf-8 -*-
"""Merge validated BSE gap-fills (_gapfill/<lo>_<hi>.json) into docs/sf_fundamentals.json.
Each fill = [qe, std, con, ann]; inserted as [qe, std, ann, con, ann], keeping each stock's
series sorted, only for quarters not already present. Idempotent.
Run: python -X utf8 merge_gapfills.py
"""
import json, os, glob, re
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
F = os.path.join(ROOT, "docs", "sf_fundamentals.json")

def main():
    d = json.load(open(F))
    added = 0; stocks = set()
    for fp in glob.glob(os.path.join(HERE, "_gapfill", "*.json")):
        if re.search(r"\b0_12\.json$", fp): continue          # skip the small test batch
        for sym, v in json.load(open(fp)).items():
            arr = d.get(sym)
            if arr is None or not v.get("fills"): continue
            have = {r[0] for r in arr}
            for qe, std, con, ann in v["fills"]:
                if qe in have: continue
                arr.append([qe, std, ann, con, ann]); have.add(qe)
                added += 1; stocks.add(sym)
            arr.sort(key=lambda r: r[0])
    tmp = F + ".tmp"; json.dump(d, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, F)
    print("Merged %d gap-fills across %d stocks into sf_fundamentals.json" % (added, len(stocks)))

if __name__ == "__main__":
    main()

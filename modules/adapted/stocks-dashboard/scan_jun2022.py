"""Find cached XBRL filings covering the Jun-2022 quarter for the symbols missing revenue.

Question this answers: is the Jun-2022 revenue hole a MISSING-SOURCE problem (no filing in the cache)
or a PARSE problem (filing is right there but build_revop never extracted rev/op from it)?
"""
import os
import re
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

CACHE = r"C:\Users\dhruv\stocks-dashboard\scripts\_xbrl_cache"
SC = r"C:\Users\dhruv\AppData\Local\Temp\claude\C--Users-dhruv-stocks-dashboard\8837b89a-2ae1-4996-8411-cb2acccadc4c\scratchpad"

SYM_RE = re.compile(r'NSESymbol">([^<]+)<')
NAT_RE = re.compile(r'NatureOfReportStandaloneConsolidated[^>]*>([^<]+)<')
END_RE = re.compile(r'(?:DateOfEndOfReportingPeriod|xbrli:endDate)[^>]*>([\d-]+)<')
# revenue tags used by build_revop
REV_RE = re.compile(r'(RevenueFromOperations|IncomeFromOperations|Income\b|InterestEarned)')

with open(f"{SC}/jun2022_missing.json", encoding="utf-8") as f:
    TARGETS = set(json.load(f)["missS"]) | set(json.load(open(f"{SC}/jun2022_missing.json", encoding="utf-8"))["missC"])


def scan(fn):
    p = os.path.join(CACHE, fn)
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            txt = f.read(200000)
    except Exception:
        return None
    m = SYM_RE.search(txt)
    if not m:
        return None
    sym = m.group(1).strip().upper()
    if sym not in TARGETS:
        return None
    ends = set(END_RE.findall(txt))
    if not any(e.startswith("2022-06-30") for e in ends):
        return None
    nats = sorted(set(n.strip().title() for n in NAT_RE.findall(txt) if n.strip()))
    has_rev = bool(REV_RE.search(txt))
    return sym, fn, nats, has_rev


def main():
    files = os.listdir(CACHE)
    found = defaultdict(list)
    with ProcessPoolExecutor(max_workers=8) as ex:
        for res in ex.map(scan, files, chunksize=200):
            if res:
                sym, fn, nats, has_rev = res
                found[sym].append({"file": fn, "nat": nats, "rev_tag": has_rev})
    with open(f"{SC}/jun2022_cache_hits.json", "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1)
    print("targets:", len(TARGETS))
    print("targets WITH a cached Jun-2022 filing:", len(found))
    print("targets with NO cached filing:", len(TARGETS - set(found)))
    withrev = [s for s, v in found.items() if any(x["rev_tag"] for x in v)]
    print("of those, filings carrying a revenue-ish tag:", len(withrev))
    print("\nsample hits:")
    for s in sorted(found)[:12]:
        v = found[s]
        print(f"  {s:12s} {len(v)} filing(s) nat={v[0]['nat']} rev_tag={v[0]['rev_tag']}")
    print("\nno cached filing:", sorted(TARGETS - set(found))[:40])


if __name__ == "__main__":
    main()

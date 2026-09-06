"""Scan the XBRL cache for (NSE symbol -> set of report natures filed).

Non-circular evidence for the no-sub identity: a company that has NEVER filed a Consolidated XBRL
is a standalone-only filer, so con == std by SEBI LODR Reg 33. This reads the filings themselves,
not our derived series, so it cannot be contaminated by any earlier con=std copy.
"""
import os
import re
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

CACHE = r"C:\Users\dhruv\stocks-dashboard\scripts\_xbrl_cache"
OUT = r"C:\Users\dhruv\AppData\Local\Temp\claude\C--Users-dhruv-stocks-dashboard\8837b89a-2ae1-4996-8411-cb2acccadc4c\scratchpad\xbrl_nature.json"

SYM_RE = re.compile(r'NSESymbol">([^<]+)<')
NAT_RE = re.compile(r'NatureOfReportStandaloneConsolidated[^>]*>([^<]+)<')
QE_RE = re.compile(r'DateOfEndOfReportingPeriod[^>]*>([\d-]+)<')


def scan(fn):
    p = os.path.join(CACHE, fn)
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            txt = f.read(60000)
    except Exception:
        return None
    m = SYM_RE.search(txt)
    if not m:
        return None
    sym = m.group(1).strip().upper()
    nats = set(n.strip().title() for n in NAT_RE.findall(txt))
    qes = set(QE_RE.findall(txt))
    return sym, nats, qes


def main():
    files = os.listdir(CACHE)
    print("files:", len(files))
    out = defaultdict(lambda: {"nat": set(), "con_qes": set(), "n": 0})
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, res in enumerate(ex.map(scan, files, chunksize=200)):
            if i % 20000 == 0:
                print(" ", i, flush=True)
            if not res:
                continue
            sym, nats, qes = res
            e = out[sym]
            e["n"] += 1
            e["nat"] |= nats
            if "Consolidated" in nats:
                e["con_qes"] |= qes
    ser = {s: {"nat": sorted(v["nat"]), "filings": v["n"],
               "con_qes": sorted(v["con_qes"])[:400]} for s, v in out.items()}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(ser, f)
    print("symbols:", len(ser))


if __name__ == "__main__":
    main()

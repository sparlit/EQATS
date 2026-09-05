#!/usr/bin/env python3
"""RETIRED 2026-08-12 — DO NOT RUN. Kept only so the history of the decision is readable.

This used to be a MANDATORY post-rebuild step (old runbook 8). It is now a DEFECT generator.

Measured over all 31,655 (snapshot x symbol) cells of the F&O history:
    point-in-time labels  99.99% priceable
    current-name labels   98.4%  priceable   <- what this script produces
Running it breaks ~355 pre-2015 cells and 66 post-2015 ones, silently dropping those stocks from
the F&O universe in exactly the eras they WERE members.

Why: sf price data is PARTITIONED BY TICKER ERA. The current-name series carries a hole exactly
where the old-name series lives, and the old name fills it (TATACONSUM has a gap 2010-07-19 ->
2020-02-27; TATAGLOBAL covers 2010-07-21 -> 2020-02-26). The engine matches membership against each
series' own key, so only the ticker that actually traded on date D resolves on date D.

The original rationale -- "old-name series are split/truncated, e.g. TATAMOTORS ends 2003-12" --
was true when this was written and is no longer: TATAMOTORS now runs 1996 -> 2025-10 (3085 bars).
The true-daily-bars rebuild repaired the partitioning this was working around.

Fundamentals (the other reason current names were wanted) are handled the designed way instead:
FUND_ALIAS + fundFor() bridge the point-in-time name to sf_fundamentals -- see runbook 8 and
scripts/check_fund_alias.py.
"""
import json, gzip, sys
from pathlib import Path

if "--i-know-this-is-retired" not in sys.argv:
    sys.exit(__doc__ + "\nRefusing to run. See DATA_RUNBOOK 8.\n")
ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "scripts" / "fno_history.json"
BIN = ROOT / "docs" / "stock_data.bin"
ALIAS = {"ADANITRANS":"ADANIENSOL","AEGISCHEM":"AEGISLOG","AKZOINDIA":"JSWDULUX","ALSTOMT&D":"GVT&D","AMARAJABAT":"ARE&M","BAJAJCORP":"BAJAJCON","BHUSANSTL":"TATASTLBSL","CADILAHC":"ZYDUSLIFE","CENTURYTEX":"ABREL","CLNINDIA":"SUDARCOLOR","CROMPGREAV":"CGPOWER","ESSELPACK":"EPL","FCEL":"FCONSUMER","FINANTECH":"63MOONS","FRL":"FEL","GATI":"ACLGATI","GEPIL":"GVPIL","GET&D":"GVT&D","GLS":"ALIVUS","GMRINFRA":"GMRAIRPORT","GUJFLUORO":"GFLLIMITED","HOTELEELA":"HLVLTD","HSIL":"AGI","IBREALEST":"EMBDL","IBULHSGFIN":"SAMMAANCAP","IBULISL":"IBULLSLTD","IDFCBANK":"IDFCFIRSTB","IIFLWAM":"360ONE","INEOSSTYRO":"STYRENIX","INFIBEAM":"CCAVENUE","INFRATEL":"INDUSTOWER","IPAPPM":"ANDHRAPAP","ITDCEM":"CEMPRO","JCHAC":"BOSCH-HCIL","JUBILANT":"JUBLPHARMA","KALPATPOWR":"KPIL","KPIT":"BSOFT","KSBPUMPS":"KSB","L&TFH":"LTF","LAXMIMACH":"LMW","LTI":"LTM","LTIM":"LTM","MAGMA":"POONAWALLA","MAHINDCIE":"CIEINDIA","MAX":"MFSL","MCDOWELL-N":"UNITDSPR","MINDAIND":"UNOMINDA","MOTHERSUMI":"MOTHERSON","NBVENTURES":"NAVA","NIITTECH":"COFORGE","PIPAVAVDOC":"RNAVAL","PRISMCEM":"PRSMJOHNSN","PVR":"PVRINOX","RDEL":"RNAVAL","SEINV":"PAISALO","SEQUENT":"VIYASH","SKSMICRO":"BHARATFIN","SMLISUZU":"SMLMAH","SRTRANSFIN":"SHRIRAMFIN","SSLT":"VEDL","STRTECH":"STLTECH","SUNCLAYLTD":"TVSHLTD","SUVENPHAR":"COHANCE","SWANENERGY":"SWANCORP","TATAGLOBAL":"TATACONSUM","TATAMOTORS":"TMPV","TATASPONGE":"TATASTLLP","TIDEWATER":"VEEDOL","WABCOINDIA":"ZFCVINDIA","WELSPUNIND":"WELSPUNLIV","ZOMATO":"ETERNAL"}

H = json.loads(HIST.read_text())
renamed = set()
for snap in H:
    for s in snap['symbols']:
        if s in ALIAS: renamed.add(s)
    snap['symbols'] = sorted(set(ALIAS.get(s, s) for s in snap['symbols']))
# dedupe consecutive identical membership
ded = []
for snap in H:
    if ded and set(snap['symbols']) == set(ded[-1]['symbols']): continue
    ded.append(snap)
HIST.write_text(json.dumps(ded, separators=(',', ':')))
D = json.loads(gzip.decompress(BIN.read_bytes()))
D['fnoHistory'] = ded
BIN.write_bytes(gzip.compress(json.dumps(D, separators=(',', ':')).encode(), 6))

def snap_at(date):
    cur = None
    for s in ded:
        if s['effectiveDate'] <= date: cur = s
    return set(cur['symbols']) if cur else set()
print(f"renamed old tickers found & normalized: {len(renamed)} -> {sorted(renamed)}")
print(f"snapshots: {len(H)} -> {len(ded)} (after dedupe)")
j = snap_at('2024-01-31')
print(f"Jan-2024 universe: {len(j)} stocks | TMPV={'TMPV' in j} TATAMOTORS={'TATAMOTORS' in j} IDFC={'IDFC' in j} GVT&D={'GVT&D' in j}")
print(f"latest snap {ded[-1]['effectiveDate']}: TMPV={'TMPV' in set(ded[-1]['symbols'])} GVT&D={'GVT&D' in set(ded[-1]['symbols'])} ({len(ded[-1]['symbols'])} stocks)")

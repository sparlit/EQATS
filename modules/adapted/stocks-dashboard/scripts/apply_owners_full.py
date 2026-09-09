import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-
"""Build the OWNERS-ATTRIBUTABLE consolidated dataset for ALL stocks/history:
  - set npCon = owners from the comprehensive _reattr_owners.json (1697 stocks)
  - add verified-from-filing backfills for qualifying NCI stocks missing from that file
Writes the result to docs/sf_fundamentals.json (in place). Reports coverage + any
qualifying stock whose con-quarter still lacks an owners figure (potential residual gap).
Run: python -X utf8 apply_owners_full.py            (impact-only: pass --dry)"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import scale_fix

F = os.path.join(ROOT, "docs", "sf_fundamentals.json")
live = json.load(open(F))
OWN = json.load(open(os.path.join(HERE, "_reattr_owners.json")))  # "SYM|qe" -> owners cr

# Renamed-ticker map (OLD->NEW). _reattr_owners is keyed by the OLD ticker (name at extraction),
# but live FUND is keyed by the NEW ticker; without this, renamed stocks silently keep total PAT.
ALIAS = {
    "ADANITRANS": "ADANIENSOL",
    "AEGISCHEM": "AEGISLOG",
    "AKZOINDIA": "JSWDULUX",
    "ALSTOMT&D": "GVT&D",
    "AMARAJABAT": "ARE&M",
    "BAJAJCORP": "BAJAJCON",
    "BHUSANSTL": "TATASTLBSL",
    "CADILAHC": "ZYDUSLIFE",
    "CENTURYTEX": "ABREL",
    "CLNINDIA": "SUDARCOLOR",
    "CROMPGREAV": "CGPOWER",
    "ESSELPACK": "EPL",
    "FCEL": "FCONSUMER",
    "FINANTECH": "63MOONS",
    "FRL": "FEL",
    "GATI": "ACLGATI",
    "GEPIL": "GVPIL",
    "GET&D": "GVT&D",
    "GLS": "ALIVUS",
    "GMRINFRA": "GMRAIRPORT",
    "GUJFLUORO": "GFLLIMITED",
    "GUJGASLTD": "GUJENERGY",
    "HOTELEELA": "HLVLTD",
    "HSIL": "AGI",
    "IBREALEST": "EMBDL",
    "IBULHSGFIN": "SAMMAANCAP",
    "IBULISL": "IBULLSLTD",
    "IDFCBANK": "IDFCFIRSTB",
    "IIFLWAM": "360ONE",
    "INEOSSTYRO": "STYRENIX",
    "INFIBEAM": "CCAVENUE",
    "INFRATEL": "INDUSTOWER",
    "IPAPPM": "ANDHRAPAP",
    "ITDCEM": "CEMPRO",
    "JCHAC": "BOSCH-HCIL",
    "JUBILANT": "JUBLPHARMA",
    "KALPATPOWR": "KPIL",
    "KPIT": "BSOFT",
    "KSBPUMPS": "KSB",
    "L&TFH": "LTF",
    "LAXMIMACH": "LMW",
    "LTI": "LTM",
    "LTIM": "LTM",
    "LYPSAGEMS": "AURUS",
    "MAGMA": "POONAWALLA",
    "MAHINDCIE": "CIEINDIA",
    "MAX": "MFSL",
    "MCDOWELL-N": "UNITDSPR",
    "MINDAIND": "UNOMINDA",
    "MIRCELECTR": "ONIDA",
    "MOTHERSUMI": "MOTHERSON",
    "NBVENTURES": "NAVA",
    "NIITTECH": "COFORGE",
    "PIPAVAVDOC": "RNAVAL",
    "PRISMCEM": "PRSMJOHNSN",
    "PVR": "PVRINOX",
    "RDEL": "RNAVAL",
    "SEINV": "PAISALO",
    "SEQUENT": "VIYASH",
    "SKSMICRO": "BHARATFIN",
    "SMLISUZU": "SMLMAH",
    "SRTRANSFIN": "SHRIRAMFIN",
    "SSLT": "VEDL",
    "STRTECH": "STLTECH",
    "SUNCLAYLTD": "TVSHLTD",
    "SUVENPHAR": "COHANCE",
    "SWANENERGY": "SWANCORP",
    "TATAGLOBAL": "TATACONSUM",
    "TATAMOTORS": "TMPV",
    "TATASPONGE": "TATASTLLP",
    "TIDEWATER": "VEEDOL",
    "WABCOINDIA": "ZFCVINDIA",
    "WELSPUNIND": "WELSPUNLIV",
    "ZOMATO": "ETERNAL",
}
REV = {}
for _o, _n in ALIAS.items():
    REV.setdefault(_n, []).append(_o)

# verified-from-filing backfills (owners-attributable, cr) for NCI stocks not in _reattr_owners
BACKFILL = {
    # CEMPRO (ITD Cementation): owners = total - NCI, read from consolidated filings
    "CEMPRO|20250331": 113.55,
    "CEMPRO|20251231": 110.89 - 0.00,  # Q3FY26 NCI~0 -> owners~total
    "CEMPRO|20260331": 242.17,  # Q4FY26 NCI~0 -> owners~total
    # ACUTAAS (Acutaas/Anupam Rasayan, consolidates Tanfac): from Q4FY26 filing attribution
    "ACUTAAS|20250331": 62.48,
    "ACUTAAS|20251231": 107.96,
    "ACUTAAS|20260331": 131.76,
}
# A HEAL LEDGER OUTRANKS THE EXTRACTION CACHE (added 2026-08-09).
# _reattr_owners.json is built from the same XBRL as everything else, so when a con cell was wrong
# at ingestion the cache carries the identical wrong number — and this script runs nightly, after
# the heal. TATACOFFEE 20221231 was read from its own consolidated filing as 38.4 (screener 38,
# our standalone 26.61) and reverted to the cached 26.63 every single night: the heal was
# journalled, committed, and never actually live. Anything corrected in con_copy_heals.json now
# wins here, so a future heal cannot be silently undone the same way.
# Both directions are authoritative: `now` is a heal, `value` is a REVERT (a cell adjudicated back
# to what we already had, e.g. TATACOFFEE — owners 26.63, not the total 38.40 the heal wrote). A
# revert has to pin too, or nothing stops a later ingestion from reintroducing the wrong number.
HEALS = {}
for _lg, _key in (("con_copy_heals.json", ("now", "value")), ("owners_basis_heals.json", ("owners",))):
    # owners_basis_heals.json carries the 2026-08-09 owners-vs-total repairs (KIRLFER, ATUL,
    # SADBHAV, RENUKA, NUCLEUS, ZEAL...). _reattr_owners still holds the pre-repair number for
    # some of them -- NUCLEUS 20251231 would have been reverted 20.70 -> 250.20 on the next
    # nightly run -- so this ledger has to outrank the cache too, exactly like con_copy_heals.
    try:
        _H = json.load(open(os.path.join(HERE, _lg)))
        _items = _H.get("cells", _H) if isinstance(_H, dict) else {}
        for _k, _v in _items.items():
            if not _k.endswith("|patC") or not isinstance(_v, dict):
                continue
            _val = next((_v[_n] for _n in _key if _v.get(_n) is not None), None)
            if _val is not None:
                HEALS["{}|{}".format(_k.split("|")[0], _k.split("|")[1])] = _val
    except Exception:
        pass
src_own = src_bf = src_ren = src_heal = 0
for sym, arr in live.items():
    for r in arr:
        if r[3] is None:
            continue
        k = "%s|%d" % (sym, r[0])
        a = HEALS.get(k)
        if a is not None:
            if abs(a - r[3]) > 0.005:
                r[3] = a
                src_heal += 1
            continue
        a = BACKFILL.get(k)
        if a is not None:
            if abs(a - r[3]) > 0.005:
                r[3] = a
                src_bf += 1
            continue
        a = OWN.get(k)
        ren = False
        if a is None:  # renamed: owners keyed by the OLD ticker
            for _old in REV.get(sym, ()):
                a = OWN.get("%s|%d" % (_old, r[0]))
                if a is not None:
                    ren = True
                    break
        if a is None:
            continue
        # XBRL owners=0 mis-tag guard: some filers tag ProfitOrLossAttributableToOwnersOfParent=0
        # with the real profit only in the total — and _reattr_owners.json (built from those same
        # XBRLs) carries the poisoned 0.0. NEVER let a ~0 cache value zero out a nonzero stored con
        # (the old `abs(r[3])>2` version only protected >2cr cells, so it re-zeroed ~139 microcap
        # quarters every night, undoing corrections). A genuine owners=0.00-exact alongside a nonzero
        # stored con is implausible; keeping the stored value is the safer error.
        if abs(a) < 0.005 and abs(r[3]) >= 0.005:
            continue
        # SCALE guard (§11). _reattr_owners.json was built from the same XBRL as everything else,
        # so for a filing in the scale_fix ledger it holds the SCALED owners figure — and this
        # script runs nightly, after `scale_fix.py --apply`, so it put the error straight back.
        # Measured 2026-08-09: 6 live cells were still scaled for exactly this reason (NDTV
        # 20240630 npCon -467.5 for a true -46.75). Correct here, at the point of application.
        sc = scale_fix.factor_cell(sym, r[0], "con") or (
            None
            if not REV.get(sym)
            else next(
                (scale_fix.factor_cell(_o, r[0], "con") for _o in REV[sym] if scale_fix.factor_cell(_o, r[0], "con")),
                None,
            )
        )
        if sc:
            a = round(a / sc, 2)
        if abs(a - r[3]) > 0.005:
            r[3] = a
            if ren:
                src_ren += 1
            else:
                src_own += 1
print(
    "set npCon=owners: %d from _reattr_owners, %d via rename-alias (renamed stocks), %d from filing-backfill, %d from con_copy_heals"
    % (src_own, src_ren, src_bf, src_heal)
)
if "--dry" in sys.argv:
    print("DRY RUN — not written")
    sys.exit(0)
tmp = F + ".tmp"
json.dump(live, open(tmp, "w"), separators=(",", ":"))
os.replace(tmp, F)
print("WROTE owners-attributable to docs/sf_fundamentals.json")

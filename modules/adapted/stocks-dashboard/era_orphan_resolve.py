# -*- coding: utf-8 -*-
"""ERA ORPHANS — the point-in-time Nifty-500 symbols with a PRICE series but NO fundamentals
series after FUND_ALIAS resolution, so `fundFor(sym)` is null and they drop out of every
profit/postDrift screen (DATA_RUNBOOK 92; the class was surfaced by 91's postdrift_coverage.js
as the `no-series` bucket).

WHAT THIS ANSWERS, and in which order — the cheap decisive filter runs FIRST:

  1. CEILING.  sf_fundamentals' earliest announce date anywhere is 2003-02-14 (the Dec-2002
     quarter, 316 symbols).  A rebalance month before that can never be covered by ANY alias, no
     matter how correct.  Ceiling(sym) = gap months >= the first month-end on/after that date.

  2. SUCCESSOR POOL.  A target T can only buy rows if it holds a dated quarter announced by the
     LAST gap month.  Two filters, in increasing strength:
       key-level     — T's own bin series must not start before OLD's last bar;
       COMPANY-level — no bar of T's whole company (T + every rename-chain relative + every
                       ISIN-issuer sibling) may fall inside OLD's life.  One company cannot trade
                       under two NSE symbols at the same time, so an overlap means T is a
                       different company (a MERGER partner, typically) and its profits are not
                       OLD's to inherit.
     An empty pool is a PROOF that the symbol is unwinnable for postDrift today — not a guess.

  3. RESOLUTION.  Only for what survives, and only on decisive evidence: ISIN-ISSUER equality
     (INE + 3 + 1 identifies the legal entity; the trailing series digits change on a face-value
     split, which is exactly why the bin's FULL-ISIN auto-merge misses these) read off NSE's own
     dated files.  A name resemblance is a coincidence to be disproved, and the PREVCLOSE handoff
     is a CONFIRMATION test only — measured false-positive rate makes it useless for discovery
     (runbook 92c).

Run:  python3 scripts/era_orphan_resolve.py            # needs scripts/_live/ staged (7.0/7.1b)
      python3 scripts/era_orphan_resolve.py --gaps PATH_TO_postdrift_coverage_zg_ny.json
Writes scripts/_era_orphan_resolution.json.
"""
import collections, gzip, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.path.join(HERE, "_live")
GAPS = os.path.join(HERE, "_postdrift_coverage_zg_ny.json")
OUT = os.path.join(HERE, "_era_orphan_resolution.json")
for i, a in enumerate(sys.argv):
    if a == "--gaps" and i + 1 < len(sys.argv):
        GAPS = sys.argv[i + 1]

# ---------------------------------------------------------------- inputs (LIVE only, 7.1b)
D = json.loads(gzip.decompress(open(os.path.join(LIVE, "p1_new.bin"), "rb").read()))
data, meta = D["data"], D["meta"]
FUND = json.load(open(os.path.join(LIVE, "fund_live.json")))
RENAME = json.load(open(os.path.join(HERE, "_rename_map.json")))
ALIAS = json.loads(re.search(r"^const FUND_ALIAS = (\{.*?\});$",
                             open(os.path.join(ROOT, "docs", "backtest-engine.js"), encoding="utf-8").read(),
                             re.M).group(1))
cov = json.load(open(GAPS))

gapmonths = collections.defaultdict(list)
for r in cov["gaps"]:
    if r["why"] == "no-series":
        gapmonths[r["sym"]].append(r["md"])
for k in gapmonths:
    gapmonths[k].sort()

firstb = {k: o["d"][0] for k, o in data.items()}
lastb = {k: o["d"][-1] for k, o in data.items()}


def ann_min(rows):
    """Earliest announce date on a row that also carries a profit — con (3,4) or std (1,2)."""
    best = None
    for r in rows:
        for ni, ai in ((3, 4), (1, 2)):
            if r[ni] is not None and r[ai] and r[ai] > 0 and (best is None or r[ai] < best):
                best = r[ai]
    return best


ANN = {k: ann_min(v) for k, v in FUND.items()}
FLOOR = min(v for v in ANN.values() if v)          # 20030214 on live data — the hard ceiling

# ------------------------------------------- company grouping: rename chains + ISIN issuer
par = {}


def find(x):
    par.setdefault(x, x)
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        par[ra] = rb


for k in list(data) + list(FUND):
    find(k)
for m in (RENAME, ALIAS):
    for o, n in m.items():
        union(o, n)
issuer = collections.defaultdict(list)
for k, mm in meta.items():
    i = mm.get("isin") or ""
    if i.startswith("INE"):
        issuer[i[:7]].append(k)          # INE + 3 + 1 = the legal entity; digits after are series
for g in issuer.values():
    for k in g[1:]:
        union(g[0], k)
group = collections.defaultdict(list)
for k in par:
    group[find(k)].append(k)


def company_bars(k):
    return [(data[m]["d"][0], data[m]["d"][-1]) for m in group[find(k)] if m in data]


# ---------------------------------------------------------------------------- per symbol
report = {}
for O, months in sorted(gapmonths.items()):
    lo, fo = lastb.get(O), firstb.get(O)
    last_md = int(months[-1].replace("-", ""))
    ceiling = sum(1 for md in months if int(md.replace("-", "")) >= FLOOR)
    keypool, copool = [], []
    for T, e in ANN.items():
        if T == O or not e or e > last_md:
            continue
        buys = sum(1 for md in months if int(md.replace("-", "")) >= e)
        if not buys:
            continue
        f = firstb.get(T)
        if f is not None and lo is not None and f <= lo:
            continue                                  # key-level: coexisted with OLD
        keypool.append({"target": T, "buys": buys, "firstAnn": e})
        if find(T) != find(O) and any(a <= lo and b >= fo for a, b in company_bars(T)):
            continue                                  # COMPANY-level: the company was trading
        copool.append({"target": T, "buys": buys, "firstAnn": e})
    keypool.sort(key=lambda x: -x["buys"])
    copool.sort(key=lambda x: -x["buys"])
    alias = ALIAS.get(O)
    report[O] = {
        "gapMonths": len(months), "first": months[0], "last": months[-1],
        "binFirst": fo, "binLast": lo, "binIsin": meta.get(O, {}).get("isin"),
        "ceilingRows": ceiling,
        "candidatesKeyLevel": keypool[:8],
        "candidatesCompanyLevel": copool[:8],
        "alias": alias,
        "aliasFundRows": len(FUND.get(alias, [])) if alias else 0,
        "aliasFirstAnn": ANN.get(alias) if alias else None,
        "aliasBuysRows": (sum(1 for md in months
                              if ANN.get(alias) and int(md.replace("-", "")) >= ANN[alias])
                          if alias else 0),
    }

# --------------------------------------------------------- adjudications (2026-08-12 session)
# Every claim here was read off a PRIMARY dated file this session; nothing is inferred from a name.
VERDICTS = {
    "BILT": {
        "verdict": "RESOLVED -> BALLARPUR",
        "evidence": [
            "NSE EQUITY_L, Wayback capture 2006-08-24: 'BILT, Ballarpur Industries Ltd, "
            "INE294A01011, listed 19-Jul-95' (paid-up 10)",
            "NSE EQUITY_L, Wayback capture 2010-02-05: 'BALLARPUR, Ballarpur Industries Limited, "
            "INE294A01037, listed 31-MAR-2008' (face value 2)",
            "same ISIN issuer INE294A + identical company name; the trailing series differs "
            "because the face value went 10 -> 2, which is why the bin's FULL-ISIN auto-merge "
            "never fired and left two keys",
            "tape: BILT last bar 2008-02-28, BALLARPUR first bar 2008-03-31 = its NSE listing date",
            "NSE bhavcopy PREVCLOSE confirmation: BALLARPUR 2008-03-31 prevclose 27.50 == BILT's "
            "2008-02-28 close 137.50 / 5, exact to the paise",
            "neither symbol is in today's EQUITY_L and no INE294A symbol trades on NSE now, so "
            "neither is a recycled ticker (the 30-4c aliveness rule)",
        ],
        "postDriftRowsBought": 0,
        "why0": "BALLARPUR's first announced quarter is 2008-08-14; BILT's last screenable "
                "rebalance is 2008-02-29. Correct mapping, no era quarters behind it.",
        "sideEffect": "loadShp() now merges BILT's 18 shareholding quarters (2002-12-31 -> "
                      "2007-03-31) into BALLARPUR, which previously started at 2008-06-30.",
    },
    "SUNCLAYTON": {
        "verdict": "RESOLVED -> TVSHLTD",
        "evidence": [
            "NSE EQUITY_L, Wayback capture 2010-02-05: 'SUNCLAYTON, Sundaram Clayton Limited, "
            "INE105A01027, listed 20-JUN-2008' (face value 5)",
            "NSE EQUITY_L live 2026-08-12: 'TVSHLTD, TVS Holdings Limited, INE105A01035, "
            "listed 23-OCT-2012'",
            "NSE symbolchange.csv: 'TVS Holdings Limited, SUNCLAYLTD, TVSHLTD, 10-AUG-2023' — the "
            "chain is SUNCLAYTON -> SUNCLAYLTD -> TVSHLTD; the bin already merged the last hop by "
            "ISIN, so TVSHLTD is the bin key the map must point at",
            "same ISIN issuer INE105A",
            "NSE bhavcopy PREVCLOSE confirmation: SUNCLAYLTD 2012-10-23 prevclose 185.45 == "
            "SUNCLAYTON's 2012-09-06 close 185.45, exact, and that row carries INE105A01035",
            "SUNCLAYTON is absent from today's EQUITY_L: the 2023 demerger's new 'Sundaram Clayton "
            "Limited' is a different legal entity under a different ISIN, so this is not the "
            "DVL/DTIL recycled-ticker shape (89)",
        ],
        "postDriftRowsBought": 0,
        "why0": "TVSHLTD's first announced quarter is 2015-05-08; SUNCLAYTON's two blocked "
                "rebalances are 2008-10-31 and 2008-11-30.",
    },
    "KIRLOSBROS-as-BILT": {
        "verdict": "DISPROVED",
        "evidence": [
            "the ONLY company-level candidate pair left in the whole class (1 row, BILT's "
            "2008-02-29 rebalance) — it survives the coexistence filter because KIRLOSBROS' bin "
            "series starts 2010-04-20, after BILT's last bar",
            "ISIN refutes it: BILT is INE294A01011 (NSE 2006-08-24) and KIRLOSBROS is "
            "INE732A01036 (live bin meta) — different issuers, different companies",
            "BILT's real continuation, BALLARPUR (INE294A01037), is independently established",
        ],
    },
}

out = {
    "sfEnd": cov.get("sfEnd"), "gapsFrom": os.path.basename(GAPS),
    "verdicts": VERDICTS,
    "fundFloorAnn": FLOOR,
    "totals": {
        "symbols": len(report),
        "noSeriesRows": sum(v["gapMonths"] for v in report.values()),
        "ceilingRows": sum(v["ceilingRows"] for v in report.values()),
        "companyLevelCandidatePairs": sum(len(v["candidatesCompanyLevel"]) for v in report.values()),
        "rowsBoughtByCurrentAliases": sum(v["aliasBuysRows"] for v in report.values()),
    },
    "symbols": report,
}
json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
t = out["totals"]
print("fundamentals announce FLOOR (earliest anywhere in sf_fundamentals): %d" % FLOOR)
print("%d symbols · %d no-series rebalance rows · ceiling if every alias were perfect: %d"
      % (t["symbols"], t["noSeriesRows"], t["ceilingRows"]))
print("company-level candidate (old,target) pairs that could buy >0 rows: %d"
      % t["companyLevelCandidatePairs"])
for O, v in sorted(report.items()):
    if v["candidatesCompanyLevel"]:
        print("   %-12s %s" % (O, v["candidatesCompanyLevel"]))
print("rows bought by the FUND_ALIAS entries currently baked: %d" % t["rowsBoughtByCurrentAliases"])
print("wrote " + OUT)

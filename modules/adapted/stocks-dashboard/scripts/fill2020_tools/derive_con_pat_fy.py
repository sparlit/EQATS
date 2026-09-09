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
"""FILL-2020 pre-2020 con-PAT: derive the 4th quarter from the consolidated ANNUAL row.

The last lever on the pre-2020 con wall (§53: only 2.7% of gap cells have a con quarterly
filing). Where a fiscal year has THREE consolidated quarters stored and the fourth is our gap,
and NSE serves that year's consolidated ANNUAL row, the missing quarter is exact arithmetic:

    derived = annual - (sum of the three stored quarters)

Measured across all 311 gap companies: 35 fiscal years qualify, 13 of them also have the annual.

WHY A BARE IDENTITY IS NOT ENOUGH. The subtraction is only as trustworthy as the annual, and an
annual can silently be on another footing -- restated after a merger or an Ind-AS transition,
or covering a different period than its label suggests (§45's warning, and the reason §42 forbids
deriving from Screener annuals). A wrong annual produces a derived quarter that looks perfectly
reasonable and is entirely fabricated.

THE CALIBRATION GATE closes that. 555 fiscal years in this dataset have ALL FOUR con quarters
stored, so for the same company we can TEST the annual-equals-sum-of-quarters identity in a
NEIGHBOURING year where every term is known:

    |annual_cal - sum(4 stored quarters of the calibration FY)| <= max(3cr, 3%)

If the identity holds there, this company's annual row is on the same footing as its quarters and
the derivation in the gap year is sound. If it fails -- or if no calibration year exists -- the
cell is REFUSED rather than derived. That converts "the arithmetic is right" into "the arithmetic
is right AND the inputs are commensurable".

Anti-poison on every fetched page (as §53b): declared basis Consolidated, Period Ended == the
fiscal-year end, Symbol among the era spellings. Annual pages ARE legitimately cumulative, so the
quarterly cumulative-rejection is deliberately not applied here.

Run:  python -X utf8 scripts/fill2020_tools/derive_con_pat_fy.py [--apply]
"""
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

_spec = importlib.util.spec_from_file_location("nar", os.path.join(SCRIPTS, "_nse_archive_revop.py"))
NAR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NAR)
NAR.JAR = NAR.BF.nse_jar()

INV = os.path.join(HERE, "_con_nse_inventory.json")
TARGETS = os.path.join(HERE, "_con_targets_pre2020.json")
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(SCRIPTS, "fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "con_pat_fy_derived.json")
CACHE = os.path.join(SCRIPTS, "_nsearch_cache")

CAL_ABS, CAL_REL = 3.0, 0.03

R_OWN = re.compile(r"net profit.*after\s+taxe?s?.*minority\s+interest", re.IGNORECASE)
R_PERIOD = re.compile(r"net profit\s*/?\s*\(?\s*loss\s*\)?\s*for the period", re.IGNORECASE)
R_MINORITY = re.compile(r"^minority interest", re.IGNORECASE)


def fy_quarters(fyend):
    return [(fyend - 1) * 10000 + 630, (fyend - 1) * 10000 + 930, (fyend - 1) * 10000 + 1231, fyend * 10000 + 331]


MONN = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
R_FYSPAN = re.compile(
    r"Financial\s*Year\s*\|?\s*(\d{2})-([A-Za-z]{3})-(\d{4})\s*\|?\s*To\s*\|?\s*"
    r"(\d{2})-([A-Za-z]{3})-(\d{4})",
    re.IGNORECASE,
)


def fy_span_months(html):
    """Months covered by the page's own declared 'Financial Year <d> To <d>', or None."""
    m = R_FYSPAN.search(re.sub(r"<[^>]+>", "|", html))
    if not m:
        return None, None
    try:
        b = (int(m.group(3)), MONN[m.group(2).lower()])
        e = (int(m.group(6)), MONN[m.group(5).lower()])
    except KeyError:
        return None, None
    return (e[0] * 12 + e[1]) - (b[0] * 12 + b[1]) + 1, "{}-{}-{}..{}-{}-{}".format(*m.groups())


def annual_pat(sym, fyend, link):
    """Owners-attributable PAT from a consolidated ANNUAL page, or (None, reason)."""
    path = os.path.join(CACHE, "ann_%s_%d_c.html" % (sym.replace("&", "_"), fyend))
    try:
        html = NAR.get_detail(link, sym, path)
    except Exception as ex:
        return None, f"fetch:{type(ex).__name__}"
    # DATE-TILING CHECK (§45 / PRE2015 STEP-W's GLAXO finding). An "annual" row is not always 12
    # months: HCLTECH's FY2016 row covers only Jul-2015..Mar-2016, the 9-month stub created when it
    # moved from a June-ending to a March-ending fiscal year. Subtracting three quarters from a
    # 9-month total produced a phantom Jun-2015 con of 38.64 against siblings of ~1,870 -- a value
    # that passes every other gate here, including calibration on a neighbouring year. The page
    # declares its own span, so demand it covers the four quarters being differenced.
    span, txt = fy_span_months(html)
    if span is not None and span != 12:
        return None, "fy-span=%dm (%s) not 12m" % (span, txt)
    meta, rows = NAR.parse_detail(html)
    if (meta.get("Consolidated / Non-Consolidated", "")).strip().lower() != "consolidated":
        return None, "not-consolidated"
    if NAR.iso_qe(meta.get("Period Ended", "")) != fyend * 10000 + 331:
        return None, "period={}".format(meta.get("Period Ended"))
    if (meta.get("Symbol") or "").upper() not in {a.upper() for a in ([sym, *NAR.aliases(sym)])}:
        return None, "symbol={}".format(meta.get("Symbol"))
    own, per, mi = NAR.pick(rows, R_OWN), NAR.pick(rows, R_PERIOD), NAR.pick(rows, R_MINORITY)
    pat = own
    if pat is None:
        if mi not in (None, 0.0):
            return None, "no-owners-row-but-minority-present"
        pat = per
    if pat is None:
        return None, "no-pat-row"
    if abs(pat) < 1e-9:
        return None, "blank-template(all-zero)"
    return pat, "ok"


def main():
    apply_it = "--apply" in sys.argv
    fund = json.load(open(DOCS))
    inv = json.load(open(INV))
    tg = json.load(open(TARGETS))

    landed, refused = {}, []
    for mem, rec in sorted(tg.items()):
        key = rec["key"]
        rows = {r[0]: r for r in fund.get(key, [])}
        gapq = set(rec["qes"])
        anns = (inv.get(mem) or {}).get("ann") or {}
        for fyend in range(2015, 2021):
            qs = fy_quarters(fyend)
            vals = {}
            for q in qs:
                r = rows.get(q)
                vals[q] = r[3] if r and len(r) > 3 else None
            miss = [q for q in qs if vals[q] is None]
            if len(miss) != 1 or miss[0] not in gapq:
                continue
            akey = str(fyend * 10000 + 331)
            if akey not in anns:
                refused.append((mem, fyend, miss[0], "no-annual-row"))
                continue
            # ---- calibration: does annual == sum(4 quarters) in a neighbouring FULL year?
            cal = None
            for cfy in sorted(range(2015, 2021), key=lambda y: abs(y - fyend)):
                if cfy == fyend:
                    continue
                ck = str(cfy * 10000 + 331)
                if ck not in anns:
                    continue
                cvals = []
                for q in fy_quarters(cfy):
                    r = rows.get(q)
                    v = r[3] if r and len(r) > 3 else None
                    if v is None:
                        cvals = None
                        break
                    cvals.append(v)
                if not cvals:
                    continue
                a, why = annual_pat(mem, cfy, anns[ck])
                time.sleep(0.7)
                if a is None:
                    continue
                d = abs(a - sum(cvals))
                if d <= max(CAL_ABS, abs(a) * CAL_REL):
                    cal = "FY%d ok (annual %.2f vs sum %.2f, d=%.2f)" % (cfy, a, sum(cvals), d)
                    break
                cal = None
                refused.append(
                    (
                        mem,
                        fyend,
                        miss[0],
                        "calibration FY%d FAILED (annual %.2f vs sum %.2f, d=%.2f)" % (cfy, a, sum(cvals), d),
                    )
                )
                break
            if not cal:
                if not any(r[0] == mem and r[1] == fyend for r in refused):
                    refused.append((mem, fyend, miss[0], "no-calibration-FY"))
                continue
            a, why = annual_pat(mem, fyend, anns[akey])
            time.sleep(0.7)
            if a is None:
                refused.append((mem, fyend, miss[0], f"annual:{why}"))
                continue
            kvals = [v for q, v in vals.items() if v is not None]
            known = sum(kvals)
            derived = round(a - known, 2)
            # SIBLING-MAGNITUDE net, behind the span check. A derived quarter wildly out of scale
            # with the three it sits beside means the annual and the quarters are not describing the
            # same thing, whatever the labels say. Cheap, and catches span anomalies the page
            # neglects to declare.
            med = sorted(abs(v) for v in kvals)[len(kvals) // 2]
            if med > 0 and not (0.15 * med <= abs(derived) <= 6.0 * med):
                refused.append(
                    (mem, fyend, miss[0], f"implausible vs siblings (derived {derived:.2f}, sibling median {med:.2f})")
                )
                continue
            landed["%s|%d" % (mem, miss[0])] = {
                "con": derived,
                "src": "fy-identity-nse-annual",
                "fy": fyend,
                "annual": round(a, 2),
                "known_sum": round(known, 2),
                "calibration": cal,
                "key": key,
                "applied": "2026-08-06 FILL-2020 pre-2020 con",
            }
            print(
                "  OK   %-12s FY%d  %d con=%-10.2f (annual %.2f - known %.2f) | cal %s"
                % (mem, fyend, miss[0], derived, a, known, cal),
                flush=True,
            )
    print("\nderived %d | refused %d" % (len(landed), len(refused)))
    for r in refused:
        print("   REFUSE %-12s FY%d %d  %s" % r)
    if not apply_it:
        print("\nDRY RUN -- nothing written.")
        return
    for path in (DOCS, MIRROR):
        d = json.load(open(path))
        n = 0
        for k, v in landed.items():
            mem, qe = k.split("|")
            r = {x[0]: x for x in d.get(v["key"], [])}.get(int(qe))
            if not r:
                continue
            while len(r) < 5:
                r.append(None)
            if r[3] is not None:
                continue
            r[3] = v["con"]
            if r[4] is None:
                r[4] = r[2]
            n += 1
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("wrote %-28s %d cells" % (os.path.basename(path), n))
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    led.update(landed)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s" % (len(landed), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()

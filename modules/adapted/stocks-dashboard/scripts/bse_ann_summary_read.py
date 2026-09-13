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
"""BSE ANNOUNCEMENT-INDEX RESULT SUMMARIES as a standalone-PAT reader for the 2002-2005 era (runbook §129).

BSE's corporate-announcement index (AnnSubCategoryGetData, strCat=-1) reaches 2002 for a scrip, and in that
era the result rows carry NO attachment: the result is BSE's OWN summary sentence in the row body (MORE):
   "X Ltd has posted a net loss of Rs 169.80 million for the quarter ended June 30, 2003 as compared to
    Rs 244.70 million for the quarter ended June 30, 2002. Total income has increased from ... to ..."
Everything a gate needs is DECLARED in the sentence: sign (profit/loss), unit (million/crore/lakh), the
period KIND (quarter vs half year / nine months / year) and its END DATE, the YEAR-AGO comparative, and
often total income. Exchange-native, but a SUMMARY of the filing rather than the filing -- so a cell
lands only with an independent lock (runbook §58 step 6 shape):
   L1  the sentence's year-ago comparative reproduces our STORED std PAT for that quarter
   L2  the quarter is read twice -- its own announcement AND the year-later announcement's comparative -- and
       they agree (a restated comparative FAILS this and the as-filed own reading is kept with a note, §108)
   L3  the sentence's total income reproduces our stored revS (sf_revop slot 0)
   L3c a comparative-only reading (no own announcement found) locks only on its comparative total income
Refusals are typed; a 'consolidated' word anywhere refuses (the era's undeclared basis is the standalone filing);
a half-year / nine-month / year sentence never lands as a quarter; a 'year ended' comparative is not an anchor.
Hold-out FIRST: every own reading whose quarter we already store is compared before any proposal is emitted.

Usage (harvest first -- scripts/bse_ann_harvest.py -- then):
  python3 -X utf8 scripts/bse_ann_summary_read.py --cache <dir> --codes <sym->code json> --residue <cells json> --out props.json
"""
# Parse BSE's own result-summary sentence (announcement MORE/HEADLINE, 2002-2005 era) into declared facts.
#   "X Ltd has posted a net loss of Rs 169.80 million for the quarter ended June 30, 2003 as compared to
#    Rs 244.70 million for the quarter ended June 30, 2002. Total income has increased from Rs 1371.10
#    million in the JQ-02 to Rs 3200.90 million in the quarter ended June 30, 2003."
# Nothing here decides; it only reads what the sentence DECLARES (sign, unit, period kind, period end, comparative).
import collections
import datetime
import json
import os
import re
import sys

MON = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
MON.update({k[:3]: v for k, v in MON.items()})
UNIT = {
    "million": 10.0,
    "mn": 10.0,
    "mln": 10.0,
    "crore": 1.0,
    "crores": 1.0,
    "cr": 1.0,
    "lakh": 100.0,
    "lakhs": 100.0,
    "lac": 100.0,
    "lacs": 100.0,
    "billion": 0.01,
    "bn": 0.01,
}
R_DATE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})|([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
)


def _date(m):
    try:
        if m.group(1):
            d, mo, y = int(m.group(1)), MON.get(m.group(2).lower()), int(m.group(3))
        else:
            mo, d, y = MON.get(m.group(4).lower()), int(m.group(5)), int(m.group(6))
        if not mo:
            return None
        return y * 10000 + mo * 100 + d
    except Exception:
        return None


R_MAIN = re.compile(
    r"(?:posted|reported|recorded|registered|announced|declared|earned|incurred|has|have)\s+(?:a\s+|an\s+)?"
    r"(?P<kind>net\s+profit|net\s+loss|profit\s+after\s+tax|loss\s+after\s+tax|net\s+profit\s+after\s+tax|net\s+loss\s+after\s+tax|net\s+profit\s+\(after\s+tax\))"
    r"\s+of\s+Rs\.?\s*(?P<val>[\d,]+(?:\.\d+)?)\s*(?P<unit>million|mn|mln|crores?|cr|lakhs?|lacs?|billion|bn)\b"
    r"(?P<rest>.{0,220}?)"
    r"(?P<period>quarter|three\s+months|half\s*year|six\s+months|nine\s+months|year|twelve\s+months|fifteen\s+months|eighteen\s+months)\s+(?:ended|ending|to)\s+(?P<pend>[^.;]{4,40}?\d{4})",
    re.IGNORECASE | re.DOTALL,
)
R_CMP = re.compile(
    r"as\s+(?:compared\s+(?:to|with)|against|vis-a-vis)\s+(?:a\s+|an\s+)?(?P<ckind>net\s+profit|net\s+loss|profit|loss)?\s*(?:of\s+)?Rs\.?\s*(?P<cval>[\d,]+(?:\.\d+)?)\s*(?P<cunit>million|mn|mln|crores?|cr|lakhs?|lacs?|billion|bn)?\b",
    re.IGNORECASE | re.DOTALL,
)
R_LASTYR = re.compile(
    r"(corresponding|same|previous|last)\s+(period|quarter)(\s+(of\s+)?(the\s+)?(previous|last)\s+(year|fiscal))?|(previous|last)\s+(year|fiscal)|year[- ]ago",
    re.IGNORECASE,
)


def _shift_year(qe):
    return qe - 10000 if qe else None


def parse(text):
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", t)
    out = {"raw": t}
    m = R_MAIN.search(t)
    if not m:
        out["why"] = "no result sentence"
        return out
    kind = m.group("kind").lower()
    val = float(m.group("val").replace(",", ""))
    div = UNIT.get(m.group("unit").lower().rstrip("."))
    sign = -1.0 if "loss" in kind else 1.0
    out.update(
        {
            "kind": kind,
            "value_declared": val,
            "unit": m.group("unit").lower(),
            "pat_cr": round(sign * val / div, 2) if div else None,
            "period_kind": re.sub(r"\s+", " ", m.group("period").lower()),
            "period_text": m.group("pend"),
        }
    )
    dm = R_DATE.search(m.group("pend"))
    out["period_end"] = _date(dm) if dm else None
    out["consolidated"] = bool(re.search(r"consolidat", t, re.IGNORECASE))
    out["standalone_word"] = bool(re.search(r"standalone|stand-alone|unconsolidated", t, re.IGNORECASE))
    # comparative clause: bounded to the SAME sentence as the main result (a later sentence's "as compared to" is
    # the revenue comparative, which produced a 93.32-vs-5.97 phantom mismatch on BASF before this bound)
    sent_end = t.find(". ", m.end("pend"))
    if sent_end < 0:
        sent_end = len(t)
    c = R_CMP.search(t, m.end("unit"), sent_end)
    if c:
        cval = float(c.group("cval").replace(",", ""))
        cunit = (c.group("cunit") or m.group("unit")).lower()
        ck = (c.group("ckind") or "").lower()
        csign = -1.0 if "loss" in ck else (1.0 if "profit" in ck else sign)
        cdiv = UNIT.get(cunit.rstrip("."))
        clause = t[c.end() : sent_end]
        # the comparative must itself be a QUARTER figure: a 'year ended' / 'half year' / 'nine months' comparative
        # (BEL: 'as compared to Rs 2606.10 million for the year ended March 31, 2003') is not a quarter anchor
        ck_period = re.search(
            r"\b(year|twelve\s+months|half\s*year|six\s+months|nine\s+months|fifteen\s+months|eighteen\s+months)\s+(ended|ending|to)\b",
            clause,
            re.IGNORECASE,
        )
        cd = R_DATE.search(clause)
        if ck_period:
            cpe = None
            out["cmp_period_kind"] = ck_period.group(1).lower()
        elif cd:
            cpe = _date(cd)
            out["cmp_period_kind"] = "quarter"
        elif R_LASTYR.search(clause):
            cpe = _shift_year(out["period_end"])
            out["cmp_period_kind"] = "quarter(last-year implicit)"
        else:
            cpe = None
        out.update(
            {
                "cmp_pat_cr": round(csign * cval / cdiv, 2) if cdiv else None,
                "cmp_kind": ck or "same-as-main(implicit)",
                "cmp_period_end": cpe,
                "cmp_text": t[c.start() : sent_end][:160],
            }
        )
    ti = re.search(
        r"total\s+income\s+(?:has\s+)?(?:increased|decreased|declined|rose|fell|grew|went\s+(?:up|down)|stood)?.*?Rs\.?\s*(?P<a>[\d,]+(?:\.\d+)?)\s*(?P<au>million|mn|mln|crores?|cr|lakhs?|lacs?)\b.*?(?:to|at)\s+Rs\.?\s*(?P<b>[\d,]+(?:\.\d+)?)\s*(?P<bu>million|mn|mln|crores?|cr|lakhs?|lacs?)\b",
        t,
        re.IGNORECASE | re.DOTALL,
    )
    if ti:
        out["total_income_cr"] = round(
            float(ti.group("b").replace(",", "")) / UNIT[ti.group("bu").lower().rstrip(".")], 2
        )
        out["total_income_prev_cr"] = round(
            float(ti.group("a").replace(",", "")) / UNIT[ti.group("au").lower().rstrip(".")], 2
        )
    return out


# ---------------- reader ----------------

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--cache", required=True)
ap.add_argument("--codes", required=True)
ap.add_argument("--residue", required=True)
ap.add_argument("--out", required=True)
A = ap.parse_args()
codes = json.load(open(A.codes))
code2sym = collections.defaultdict(list)
for s, v in codes.items():
    if v:
        code2sym[str(v[1])].append(s)
sf = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
resid = json.load(open(A.residue))["cells"]
resid = {(s, qe) for s, qe in resid}


def stored(sym, qe):
    r = next((x for x in sf.get(sym, []) if x[0] == qe), None)
    return r[1] if r else None


def stored_rev(sym, qe):
    m = revop.get(sym) or {}
    c = m.get(str(qe)) if isinstance(m, dict) else None
    return c[0] if c and c[0] is not None else None


def close(a, b, tol=0.015):  # million->crore prints 2dp; allow 1 paisa + 1% of magnitude for rounding conventions
    return a is not None and b is not None and abs(a - b) <= max(tol, 0.01 * max(abs(a), abs(b)))


rows = []
files = [f for f in os.listdir(A.cache) if f.endswith(".json")]
n_att = 0
n_rows = 0
for f in files:
    rec = json.load(open(os.path.join(A.cache, f)))
    for r in rec["rows"]:
        n_rows += 1
        if r.get("ATTACHMENTNAME"):
            n_att += 1
        txt = r.get("MORE") or r.get("HEADLINE") or ""
        if not re.search(r"net\s+(profit|loss)|profit\s+after\s+tax|loss\s+after\s+tax", txt, re.IGNORECASE):
            continue
        p = parse(txt)
        if "pat_cr" not in p or p.get("pat_cr") is None:
            continue
        for sym in code2sym[str(rec["code"])]:
            rows.append(
                {
                    "sym": sym,
                    "code": rec["code"],
                    "news_dt": (r.get("NEWS_DT") or "")[:10],
                    "newsid": r.get("NEWSID"),
                    "name": r.get("SLONGNAME"),
                    **{k: v for k, v in p.items() if k != "raw"},
                    "raw": p["raw"][:400],
                }
            )
print("cache files", len(files), "rows", n_rows, "with attachment", n_att, "result sentences parsed", len(rows))
# index own readings and comparative readings per (sym, period_end)
own = collections.defaultdict(list)
cmp_ = collections.defaultdict(list)
for x in rows:
    if x.get("period_kind") != "quarter" or not x.get("period_end"):
        continue
    if x.get("consolidated"):
        continue
    own[(x["sym"], x["period_end"])].append(x)
    if x.get("cmp_pat_cr") is not None and x.get("cmp_period_end"):
        cmp_[(x["sym"], x["cmp_period_end"])].append(x)
# ---- calibration: own readings vs stored
cal = collections.Counter()
mism = []
for (sym, qe), xs in own.items():
    st = stored(sym, qe)
    if st is None:
        continue
    v = xs[0]["pat_cr"]
    if close(v, st):
        cal["match"] += 1
    else:
        cal["MISMATCH"] += 1
        mism.append((sym, qe, v, st, xs[0]["raw"][:160]))
calc = collections.Counter()
for (sym, qe), xs in cmp_.items():
    st = stored(sym, qe)
    if st is None:
        continue
    if close(xs[0]["cmp_pat_cr"], st):
        calc["match"] += 1
    else:
        calc["MISMATCH"] += 1
print("CALIBRATION own-reading vs stored std:", dict(cal), " comparative-reading vs stored:", dict(calc))
for m in mism[:25]:
    print("   MISMATCH", m)
# ---- residue proposals
props = {}
ref = collections.Counter()
detail = []
for sym, qe in sorted(resid):
    xs = own.get((sym, qe), [])
    cs = cmp_.get((sym, qe), [])
    if not xs and not cs:
        ref["no summary sentence for this quarter (own or year-later)"] += 1
        continue
    ovals = [x["pat_cr"] for x in xs]
    if ovals and not all(close(ovals[0], v) for v in ovals):
        ref["own readings DISAGREE (duplicate announcements differ)"] += 1
        detail.append((sym, qe, "own-dup", ovals))
        continue
    locks = []
    notes = []
    if xs:
        x = xs[0]
        v = x["pat_cr"]
        if x.get("cmp_pat_cr") is not None and x.get("cmp_period_end"):
            st = stored(sym, x["cmp_period_end"])
            if st is not None:
                if close(x["cmp_pat_cr"], st):
                    locks.append(
                        "L1 year-ago comparative %.2f == stored %s (%d)" % (x["cmp_pat_cr"], st, x["cmp_period_end"])
                    )
                else:
                    ref["L1 FAILS: own sentence year-ago comparative contradicts the store"] += 1
                    detail.append((sym, qe, "L1-fail", x["cmp_pat_cr"], st, x["cmp_period_end"]))
                    continue
        if x.get("total_income_cr") is not None:
            rv = stored_rev(sym, qe)
            if rv is not None and close(x["total_income_cr"], rv, 0.5):
                locks.append("L3 total income {:.2f} == stored revS {:.2f}".format(x["total_income_cr"], rv))
        if cs:
            if close(cs[0]["cmp_pat_cr"], v):
                locks.append(
                    "L2 own announcement {:.2f} == year-later comparative {:.2f}".format(v, cs[0]["cmp_pat_cr"])
                )
            else:
                notes.append(
                    "year-later comparative {:.2f} DIFFERS (restated later; as-filed own reading kept, §108)".format(
                        cs[0]["cmp_pat_cr"]
                    )
                )
    else:
        # comparative-only reading = a later filing's year-ago column: restated-vintage exposure (§108). Needs its own lock:
        # the same sentence's comparative TOTAL INCOME must reproduce stored revS for this quarter.
        c = cs[0]
        v = c["cmp_pat_cr"]
        cvals = [y["cmp_pat_cr"] for y in cs]
        if not all(close(cvals[0], y) for y in cvals):
            ref["comparative readings DISAGREE"] += 1
            detail.append((sym, qe, "cmp-dup", cvals))
            continue
        rv = stored_rev(sym, qe)
        if c.get("total_income_prev_cr") is not None and rv is not None and close(c["total_income_prev_cr"], rv, 0.5):
            locks.append(
                "L3c comparative total income {:.2f} == stored revS {:.2f}".format(c["total_income_prev_cr"], rv)
            )
        notes.append("read from the YEAR-LATER announcement comparative column (vintage = that later filing)")
    if not locks:
        ref["UNANCHORED (%s reading, nothing stored to lock against)" % ("own" if xs else "comparative-only")] += 1
        continue
    src = xs[0] if xs else cs[0]
    props["%s|%d|patS" % (sym, qe)] = {
        "value": round(v, 2),
        "locks": locks,
        "notes": notes,
        "state": "FILLED-BSE-ANN-SUMMARY",
        "src": "BSE corporate-announcement result summary (BSE's own text of the filed result), NEWSID {} dated {}, scrip {} '{}'".format(
            src["newsid"], src["news_dt"], src["code"], src["name"]
        ),
        "resolved_via": f"bse-announcement-index ({codes[sym][0]})",
        "chosen": {"precision": "sentence-declared ({})".format(src["unit"]), "row": src.get("kind")},
        "sites": {"bse_ann": "https://www.bseindia.com/corporates/ann.html?scrip={}".format(src["code"])},
        "evidence": (
            "BSE ANNOUNCEMENT INDEX (AnnSubCategoryGetData, strCat=-1) row {} dated {} for scrip {} ({}): the sentence DECLARES "
            "'{}' of Rs {} {} for the QUARTER ended {} (no 'consolidated' word; the era's filed result is standalone). Locks: {}. {} "
            'Sentence: "{}"'
        ).format(
            src["newsid"],
            src["news_dt"],
            src["code"],
            src["name"],
            src.get("kind") or "comparative",
            src.get("value_declared") if xs else src.get("cmp_pat_cr"),
            src.get("unit"),
            qe,
            "; ".join(locks),
            " ".join(notes),
            src["raw"][:300],
        ),
        "ann": int(src["news_dt"].replace("-", "")) if src["news_dt"] and len(src["news_dt"]) == 10 else None,
        "ann_basis": (
            "REAL public date: BSE's own dissemination timestamp (NEWS_DT {}) of the result-summary announcement that carries this figure{}; floored at the first traded bar (§99)".format(
                src["news_dt"],
                "" if xs else " (the YEAR-LATER announcement, so the availability date is that later filing)",
            )
        ),
    }
print("RESIDUE 2002-04 cells", len(resid), "-> proposals", len(props))
[print("  %5d %s" % (n, k)) for k, n in ref.most_common()]
print("by year", sorted(collections.Counter(int(k.split("|")[1]) // 10000 for k in props).items()))
print("locks", collections.Counter(l.split(" ")[0] for p in props.values() for l in p["locks"]))
json.dump(
    {
        "proposals": props,
        "calibration": {"own": dict(cal), "cmp": dict(calc), "mismatches": mism},
        "refusals": dict(ref),
        "detail": detail[:200],
        "rows_with_attachment": n_att,
        "rows": n_rows,
    },
    open(A.out, "w"),
    indent=1,
)

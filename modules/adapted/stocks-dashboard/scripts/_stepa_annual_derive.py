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
"""STEP A -- derive a single missing quarter from the FY ANNUAL filing (2005-2014).

Why this exists: STEP D refused ~50 FY-complete-but-one cells as "annual
unavailable/unparseable" (BSE detres had no .50 annual) and ~10 more as "annual
span N days (not ~365)". Both classes are the SAME root cause -- the company does
not run an Apr-Mar fiscal year (ABB/GLAXO = Jan-Dec, ESCORTS = Oct-Sep), so the
Apr-Mar-shaped annual lookup either missed or found a span it rejected.

NSE's own archive serves those annuals: period=Annual carries pre-2015 rows WITH
resultDetailedDataLink. This step reads the FY window off the filing itself
(fromDate/toDate) instead of assuming Apr-Mar, finds the quarters that fall inside
that window, and -- only when exactly ONE is missing and the other three are
stored -- derives it by subtraction.

LANDING RULES: the derivation is the approved annual-minus-three technique, but it
is NOT self-validating (compensating errors satisfy the same identity that defines
them -- the GAMMONIND rescue lesson). So every derived cell must additionally pass:
  * annual span 350-380 days (a real FY, not a stub/transition period)
  * all three sibling quarters span the window with no gap/overlap
  * derived rev > 0, and PAT derived on the SAME basis as the siblings
  * the annual page's Symbol meta matches the target symbol
Anything failing these is refused with a reason, never forced.

Run: python -X utf8 -u _stepa_annual_derive.py [--only SYM,SYM] [--limit N]
Writes: pre2015_reads_a.json (cell shape matching _apply_reads.py) + pre2015_attempted_a.json
"""
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _n500_member_bin as MB  # noqa: E402
import _nse_archive_revop as N  # noqa: E402
import build_fundamentals as BF  # noqa: E402

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
OUTP = os.path.join(HERE, "pre2015_reads_a.json")
ATTP = os.path.join(HERE, "pre2015_attempted_a.json")
ACACHE = os.path.join(HERE, "_stepa_cache")
os.makedirs(ACACHE, exist_ok=True)

QES = [y * 10000 + md for y in range(2005, 2015) for md in (331, 630, 930, 1231)]


def d2ord(qe):
    """qe int -> ordinal day count, for span math without datetime parsing games."""
    import datetime

    return datetime.date(qe // 10000, (qe // 100) % 100, qe % 100).toordinal()


def _first(prows, *pats):
    """First pattern that matches a row, by `is None` -- NOT `or` (0.00 is falsy)."""
    for p in pats:
        v = N.pick(prows, p)
        if v is not None:
            return v
    return None


def quarters_in(frm, to):
    """The calendar quarter-ends strictly inside (frm, to]. A standard FY yields 4."""
    return [q for q in QES if frm < d2ord(q) <= to]


def prev_qe(qe):
    y, md = qe // 10000, qe % 10000
    order = [331, 630, 930, 1231]
    i = order.index(md)
    return (y - 1) * 10000 + 1231 if i == 0 else y * 10000 + order[i - 1]


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None

    fund = json.load(open(FUND, encoding="utf8"))
    revop = json.load(open(REVOP, encoding="utf8"))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    out = json.load(open(OUTP, encoding="utf8")) if os.path.exists(OUTP) else {}
    att = json.load(open(ATTP, encoding="utf8")) if os.path.exists(ATTP) else {}

    # open member-quarter cells (standalone rev and/or PAT missing)
    open_by_sym = {}
    for qe in QES:
        for sym in MB.membership(qe):
            row = fmap.get(sym, {}).get(qe)
            has_pat = row is not None and row[1] is not None
            rr = revop.get(sym, {}).get(str(qe))
            has_rev = rr is not None and rr[0] is not None
            if has_pat and has_rev:
                continue
            open_by_sym.setdefault(sym, set()).add(qe)

    syms = sorted(open_by_sym)
    if only:
        syms = [s for s in syms if s in only]
    if limit:
        syms = syms[:limit]
    print("symbols with >=1 open 2005-14 cell: %d" % len(syms), flush=True)

    N.JAR = BF.nse_jar()
    n_land = n_ref = 0

    for si, sym in enumerate(syms, 1):
        wanted = {q for q in open_by_sym[sym] if str(q) not in out.get(sym, {})}
        if not wanted:
            continue
        lp = os.path.join(ACACHE, "annual_{}.json".format(re.sub(r"[^A-Z0-9]", "_", sym.upper())))
        rows = None
        for _attempt in (1, 2):
            try:
                raw = N.get(
                    "https://www.nseindia.com/api/corporates-financial-results"
                    "?index=equities&symbol={}&period=Annual".format(urllib.parse.quote(sym, safe="")),
                    lp,
                )
                rows = json.loads(raw)
                break
            except Exception:
                N.JAR = BF.nse_jar()
                time.sleep(1.5)
        if not isinstance(rows, list) or not rows:
            att[f"{sym}|list"] = {"reason": "no-nse-annual-rows"}
            continue

        for r in rows:
            if not r.get("resultDetailedDataLink"):
                continue
            frm, to = N.iso_qe(r.get("fromDate")), N.iso_qe(r.get("toDate"))
            if not frm or not to or to > 20150401:
                continue
            span = d2ord(to) - d2ord(frm) + 1
            qs = quarters_in(d2ord(frm) - 1, d2ord(to))
            miss = [q for q in qs if q in wanted]
            if len(miss) != 1 or len(qs) != 4:
                continue
            tgt = miss[0]
            if not (350 <= span <= 380):
                att["%s|%d" % (sym, tgt)] = {"reason": "annual-span-%dd-not-a-standard-FY" % span}
                n_ref += 1
                continue

            link = r["resultDetailedDataLink"]
            dp = os.path.join(ACACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link.rsplit("/", 1)[-1]))
            try:
                html = N.get_detail(link, sym, dp)
            except Exception:
                att["%s|%d" % (sym, tgt)] = {"reason": "annual-detail-fetch-failed"}
                n_ref += 1
                continue
            meta, prows = N.parse_detail(html)
            if (meta.get("Symbol") or "").upper() not in ([sym.upper()] + [a.upper() for a in N.aliases(sym)]):
                att["%s|%d" % (sym, tgt)] = {"reason": "annual-symbol-mismatch-{}".format(meta.get("Symbol"))}
                n_ref += 1
                continue
            basis = "con" if "Non" not in (meta.get("Consolidated / Non-Consolidated") or "Non") else "std"
            if basis != "std":
                continue  # standalone is the campaign's scope

            isbank = meta.get("fmt") == "Banking"
            # NOTE: chain on `is None`, never `or` -- a legitimate 0.00 is falsy and would
            # fall through to the next pattern (and then to None), silently turning a real
            # zero into an unreadable row.
            a_rev = (
                N.pick(prows, N.R_REV_BANK)
                if isbank
                else _first(prows, N.R_REV_IND, N.R_REV_IND2, N.R_REV_IND3, N.R_REV_SIGNED)
            )
            a_pat = _first(prows, N.R_PAT_OWN, N.R_PAT_ANY, N.R_PAT_SIGNED)
            if a_rev is None or a_pat is None:
                att["%s|%d" % (sym, tgt)] = {"reason": f"annual-rows-unreadable (rev={a_rev} pat={a_pat})"}
                n_ref += 1
                continue

            sibs = [q for q in qs if q != tgt]
            s_rev = s_pat = 0.0
            ok = True
            for q in sibs:
                rr = revop.get(sym, {}).get(str(q))
                fr = fmap.get(sym, {}).get(q)
                if not rr or rr[0] is None or not fr or fr[1] is None:
                    ok = False
                    break
                s_rev += rr[0]
                s_pat += fr[1]
            if not ok:
                att["%s|%d" % (sym, tgt)] = {"reason": "sibling-quarter-incomplete-at-derive-time"}
                n_ref += 1
                continue

            d_rev, d_pat = a_rev - s_rev, a_pat - s_pat
            if d_rev <= 0:
                att["%s|%d" % (sym, tgt)] = {
                    "reason": f"derived-rev-non-positive ({d_rev:.2f}; annual {a_rev:.2f} - sibs {s_rev:.2f})"
                }
                n_ref += 1
                continue
            # a derived quarter wildly out of family with its own siblings is a red flag
            sib_revs = [revop[sym][str(q)][0] for q in sibs]
            lo, hi = min(sib_revs), max(sib_revs)
            if d_rev > 4 * hi or d_rev < 0.2 * lo:
                att["%s|%d" % (sym, tgt)] = {
                    "reason": f"derived-rev-{d_rev:.2f}-outside-sibling-range-{lo:.2f}..{hi:.2f}"
                }
                n_ref += 1
                continue

            # PAT guards. The subtraction is only valid if the three siblings are DISCRETE
            # quarters on the same basis as the annual; when one is secretly cumulative (or
            # carries an exceptional the annual nets out) the identity still "works" and
            # emits a garbage residual -- AMBUJACEM CY2007 summed 3 siblings to 1781.81
            # against a 1769.10 full-year PAT, i.e. a -12.71 Q4 for a company earning
            # ~300-400/qtr. Refuse rather than force (LANDING RULES).
            sib_pats = [fmap[sym][q][1] for q in sibs]
            pmax = max(abs(p) for p in sib_pats)
            if s_pat > a_pat and all(p > 0 for p in sib_pats) and a_pat > 0:
                att["%s|%d" % (sym, tgt)] = {
                    "reason": f"sibling-PAT-sum-{s_pat:.2f}-exceeds-annual-{a_pat:.2f} (a sibling is cumulative "
                    "or non-comparable; subtraction invalid)"
                }
                n_ref += 1
                continue
            if abs(d_pat) > 3 * pmax:
                att["%s|%d" % (sym, tgt)] = {"reason": f"derived-PAT-{d_pat:.2f}-implausible-vs-sibling-max-{pmax:.2f}"}
                n_ref += 1
                continue
            if d_pat > d_rev:
                att["%s|%d" % (sym, tgt)] = {
                    "reason": f"derived-PAT-{d_pat:.2f}-exceeds-derived-rev-{d_rev:.2f} (exceptional-item "
                    "ambiguity, needs the filing itself)"
                }
                n_ref += 1
                continue

            out.setdefault(sym, {})[str(tgt)] = {
                "rev": round(d_rev, 2),
                "op": None,
                "pat": round(d_pat, 2),
                "ann": None,
                "basis": "std",
                "fin": 1 if isbank else 0,
                "gate": "A",
                "src": "nse-annual-derive %s | FY %d-%d span %dd | annual rev %.2f pat %.2f "
                "minus sibs %s" % (link.rsplit("/", 1)[-1], frm, to, span, a_rev, a_pat, sibs),
            }
            n_land += 1
            print(
                "%-12s %d  rev=%9.2f pat=%9.2f  (annual %.2f - %d sibs, span %dd)"
                % (sym, tgt, d_rev, d_pat, a_rev, len(sibs), span),
                flush=True,
            )
            wanted.discard(tgt)

        json.dump(out, open(OUTP, "w", encoding="utf8"), indent=0, sort_keys=True)
        json.dump(att, open(ATTP, "w", encoding="utf8"), indent=0, sort_keys=True)
        if si % 25 == 0:
            print("  [%d/%d] landed=%d refused=%d" % (si, len(syms), n_land, n_ref), flush=True)
        time.sleep(0.3)

    print("DONE landed=%d refused=%d" % (n_land, n_ref), flush=True)


if __name__ == "__main__":
    main()

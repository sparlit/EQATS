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
"""NSE results XBRL, read PER BASIS with an explicit period gate (rung 5 of the §57 ladder).

This is the decisive route for the 2019+ bulk of the audit population, where the archive's
resultDetailedDataLink is empty and many announcement PDFs are scans. Every row of
`corporates-financial-results` carries an `xbrl` URL, and NSE files ONE XBRL PER BASIS -- the row
declares which. So the standalone and consolidated numbers can each be read from the filer's own
structured document.

WHY THIS IS NOT JUST RE-RUNNING THE IMPORTER. runbook §45 warns that XBRL context ids have no fixed
meaning across filers, and the production parser leans on the "OneD == current quarter" convention.
Here nothing is assumed: each context declares DateOfStartOfReportingPeriod /
DateOfEndOfReportingPeriod and NatureOfReportStandaloneConsolidated, and a context is used only if
it spans EXACTLY the three months ending on the target quarter AND its declared nature matches the
basis being read. A filing whose contexts do not satisfy that is refused, not guessed at.
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contextlib

import nse_arch as NA  # noqa: E402

NAR = NA.NAR
CACHE = os.path.join(HERE, "_xbrl_cache")
NS = r"(?:in-bse-fin|in-capmkt|in-lifeins|in-genins)"
PAT_TAGS = [
    "ProfitLossForPeriod",
    "ProfitLossForThePeriod",
    "ProfitLossAfterTaxAndExtraordinaryItems",
    "ProfitLossAfterTax",
]
OWN_TAG = "ProfitOrLossAttributableToOwnersOfParent"
NCI_TAG = "ProfitOrLossAttributableToNonControllingInterests"
BANK_TAG = "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"
REV_TAGS = ["RevenueFromOperations", "Income", "TotalIncome"]


def _facts(xml, tag):
    out = {}
    for m in re.finditer(rf"<{NS}:{tag} contextRef=\"([^\"]+)\"[^>]*>([^<]+)<", xml):
        if m.group(1) not in out:
            with contextlib.suppress(ValueError):
                out[m.group(1)] = float(m.group(2))
    return out


def _strfacts(xml, tag):
    out = {}
    for m in re.finditer(rf"<{NS}:{tag} contextRef=\"([^\"]+)\"[^>]*>([^<]*)<", xml):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def _iso(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3)) if m else None


def rows_for(sym, qe, want_con):
    out = []
    for r in NA.rows_for(sym):
        b = (r.get("consolidated") or "").strip().lower()
        if (b == "consolidated") != want_con:
            continue
        if NAR.iso_qe(r.get("toDate") or "") != qe or not r.get("xbrl"):
            continue
        out.append(r)
    return out


def read(sym, qe, want_con):
    """(pat_cr, evidence dict) or (None, {'skip': reason}). PAT is owners-attributable."""
    cands = rows_for(sym, qe, want_con)
    if not cands:
        n = len([r for r in NA.rows_for(sym) if NAR.iso_qe(r.get("toDate") or "") == qe])
        return None, {"skip": "no-%s-row (%d list rows for this quarter)" % ("con" if want_con else "std", n)}
    os.makedirs(CACHE, exist_ok=True)
    last = None
    for r in cands:
        url = r["xbrl"]
        path = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1]))
        try:
            xml = NAR.get(url, path)
        except Exception as ex:
            last = {"skip": f"fetch:{type(ex).__name__}"}
            continue
        beg, end = (_strfacts(xml, "DateOfStartOfReportingPeriod"), _strfacts(xml, "DateOfEndOfReportingPeriod"))
        nat = {k: v.lower() for k, v in _strfacts(xml, "NatureOfReportStandaloneConsolidated").items()}
        symf = {k: v.upper() for k, v in _strfacts(xml, "Symbol").items()}
        known = {a.upper() for a in ([sym, *NAR.aliases(sym)])}
        if symf and not (set(symf.values()) & known):
            last = {"skip": f"symbol-mismatch:{sorted(set(symf.values()))[:2]}"}
            continue
        # the ONE context that is exactly this quarter, on exactly this basis
        want = "consolidated" if want_con else "standalone"
        ctxs = []
        for c, e in end.items():
            b0, e0 = _iso(beg.get(c, "")), _iso(e)
            if not b0 or not e0 or e0 != qe:
                continue
            months = (e0 // 10000 * 12 + (e0 // 100) % 100) - (b0 // 10000 * 12 + (b0 // 100) % 100)
            if months != 2:  # 3-month span; a YTD context is 5/8/11
                continue
            if nat and nat.get(c) and nat[c] != want:
                continue
            ctxs.append(c)
        if not ctxs:
            last = {
                "skip": "no-context spanning 3m to %d on basis %s (contexts=%s)"
                % (qe, want, {c: (beg.get(c), end.get(c), nat.get(c)) for c in list(end)[:4]})
            }
            continue
        vals, tagname = {}, None
        for t in PAT_TAGS:
            f = _facts(xml, t)
            hit = {c: f[c] for c in ctxs if c in f}
            if hit:
                vals, tagname = hit, t
                break
        own = {c: v for c, v in _facts(xml, OWN_TAG).items() if c in ctxs}
        nci = {c: v for c, v in _facts(xml, NCI_TAG).items() if c in ctxs}
        bank = {c: v for c, v in _facts(xml, BANK_TAG).items() if c in ctxs}
        rev = {}
        for t in REV_TAGS:
            f = _facts(xml, t)
            rev = {c: f[c] for c in ctxs if c in f}
            if rev:
                break
        if not vals and not own and not bank:
            last = {"skip": f"no-PAT-tag in {want} context"}
            continue
        c = ctxs[0]
        total = vals.get(c)
        # basis of this dataset = owners-attributable (§53c, project-stocks-profit-basis)
        pat, patsrc = own.get(c, bank.get(c, total)), "owners-tag"
        if own.get(c) is None:
            patsrc = "bank-bottom-line" if bank.get(c) is not None else "period-total"
        # EMPTY-TAG FILERS. Several filers tag BOTH attributable rows as 0.00 rather than omitting
        # them (EIMCOELECO/ANIKINDS/JINDCOT here; runbook §2d records the same for TRU Mar-26).
        # Taking the owners tag literally lands a 0.00 PAT on a company that plainly earned money.
        # When owners AND NCI are both zero but the period total is not, the split was never filed
        # and the total IS the owners' figure.
        if (
            own.get(c) is not None
            and abs(own[c]) < 1e-9
            and (nci.get(c) is None or abs(nci[c]) < 1e-9)
            and total not in (None, 0.0)
        ):
            pat, patsrc = total, "period-total (owners+NCI both tagged 0.00 -- split never filed)"
        # A consolidated PAT of exactly 0.00 is a blank form, not a result (§53b.1).
        if pat is not None and abs(pat) < 1e-9 and (total is None or abs(total) < 1e-9):
            last = {"skip": f"blank/zero PAT in {want} XBRL"}
            continue
        ev = {
            "ctx": c,
            "pat_src": patsrc,
            "basis_declared": nat.get(c) or f"(untagged, list row says {want})",
            "period": f"{beg.get(c)}..{end.get(c)}",
            "tag": tagname,
            "total": None if total is None else round(total / 1e7, 2),
            "owners": None if own.get(c) is None else round(own[c] / 1e7, 2),
            "nci": None if nci.get(c) is None else round(nci[c] / 1e7, 2),
            "bank_row": None if bank.get(c) is None else round(bank[c] / 1e7, 2),
            "rev": None if rev.get(c) is None else round(rev[c] / 1e7, 2),
            "filed": r.get("filingDate"),
            "url": url,
        }
        if pat is None:
            last = {"skip": "no-usable-PAT", **ev}
            continue
        return round(pat / 1e7, 2), ev
    return None, (last or {"skip": "all-candidates-failed"})

# -*- coding: utf-8 -*-
"""NSE results-archive detail pages (runbook §52/§53) -- BOTH bases for one (sym, qe).

Rung 2 of the §57 ladder. It reaches back to ~2005, serves DELISTED symbols and declares its own
basis/period/scale, which makes it the cleanest source where it answers at all -- but
resultDetailedDataLink is empty for most post-2019 rows, so it covers the pre-2020 tail of this
audit's population rather than its bulk.

Every anti-trap from read_con_pat_nse.py is kept: basis / period / symbol gates from the page BODY,
cumulative(YTD) refusal, blank-template refusal, owners-attributable row preference.
"""
import importlib.util, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "_nse_cache")
_spec = importlib.util.spec_from_file_location("nar", os.path.join(SCRIPTS, "_nse_archive_revop.py"))
NAR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NAR)
NAR.JAR = NAR.BF.nse_jar()

R_OWN = re.compile(r"net profit.*after\s+taxe?s?.*minority\s+interest", re.I)
R_PERIOD = re.compile(r"net profit\s*/?\s*\(?\s*loss\s*\)?\s*(\(?\s*for the period\s*\)?|for the period)", re.I)
R_MINORITY = re.compile(r"^minority interest", re.I)
_LIST = {}


def rows_for(sym):
    if sym not in _LIST:
        try:
            _LIST[sym] = NAR.list_rows(sym)
        except Exception:
            _LIST[sym] = []
        time.sleep(0.5)
    return _LIST[sym]


def link_for(sym, qe, want_con):
    for r in rows_for(sym):
        b = (r.get("consolidated") or "").strip().lower()
        is_con = b == "consolidated"
        if is_con == want_con and NAR.iso_qe(r.get("toDate") or "") == qe \
                and r.get("resultDetailedDataLink"):
            return r["resultDetailedDataLink"]
    return None


def read(sym, qe, want_con):
    """(pat, note) -- pat is owners-attributable PAT in crore, or None with a refusal reason."""
    link = link_for(sym, qe, want_con)
    if not link:
        n = len([r for r in rows_for(sym) if NAR.iso_qe(r.get("toDate") or "") == qe])
        return None, "no-detail-link (%d list rows for this quarter)" % n
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s_%d_%s.html" % (re.sub(r"[^A-Z0-9]", "_", sym.upper()), qe,
                                                  "c" if want_con else "s"))
    try:
        html = NAR.get_detail(link, sym, path)
    except Exception as ex:
        return None, "fetch:%s" % type(ex).__name__
    meta, rows = NAR.parse_detail(html)
    basis = (meta.get("Consolidated / Non-Consolidated") or "").strip().lower()
    if (basis == "consolidated") != want_con:
        return None, "basis-mismatch:%s" % (basis or "?")
    if NAR.iso_qe(meta.get("Period Ended", "")) != qe:
        return None, "period-mismatch:%s" % meta.get("Period Ended")
    if (meta.get("Symbol") or "").upper() not in {a.upper() for a in ([sym] + NAR.aliases(sym))}:
        return None, "symbol-mismatch:%s" % meta.get("Symbol")
    m = re.search(r"Cumulative\s*/\s*Non-?Cumulative\s*\|?\s*(Non-?Cumulative|Cumulative)", html, re.I)
    if m and m.group(1).lower().replace("-", "").startswith("cumulative"):
        return None, "cumulative-page(YTD not quarter)"      # §53b.3
    own, per, mi = NAR.pick(rows, R_OWN), NAR.pick(rows, R_PERIOD), NAR.pick(rows, R_MINORITY)
    pat, which = own, "owners"
    if pat is None:
        if want_con and mi not in (None, 0.0):
            return None, "no-owners-row-but-minority-present"   # §53c
        pat, which = per, "period"
    if pat is None:
        return None, "no-pat-row"
    if abs(pat) < 1e-9:
        return None, "blank-template(zero)"                  # §53b.1
    return round(pat, 2), "%s row; page declares %s / %s" % (which, basis or "?",
                                                             meta.get("Period Ended"))

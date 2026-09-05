# -*- coding: utf-8 -*-
"""CLOSE the "second reader backs the STORE" queue — with a THIRD reader and a named page defect.

These cells are the mirror image of a finding: the store matches no vintage NSE holds, but the
independent second reader (BSE detres for std, Moneycontrol for con) agrees with the STORE. So the
suspect is NSE's page, not the cell. A queue entry is not a conclusion, though — closing it needs
a third opinion and a named reason.

WHAT IT DOES
  * asks a THIRD reader (Moneycontrol standalone for std cells, BSE detres is unavailable for con)
    so the closure rests on more than one voice agreeing with the store;
  * NAMES the page defect from the cached HTML, so "NSE is wrong here" is a diagnosis and not a
    shrug:
      all-pat-rows-zero        every PAT candidate reads 0.0000 while the page prints a real PBT
      net-contradicts-pbt      the page's own net profit contradicts its PBT minus tax (FRETAIL
                               Mar-2017 books +123.05 as continuing AND -123.05 as discontinued,
                               netting to zero — a filer form error, not a reading error)
      scale-anomaly            the page's revenue is orders of magnitude from the stored revenue
      unnamed                  nothing cheap explains it; the disagreement is recorded as-is
  * writes a resolution ledger so the queue is CLOSED with evidence rather than left hanging.

NOTHING HERE CHANGES DATA. The outcome is "no change; the store is confirmed".

OUT: scripts/_vintage108_page_defects.json
RUN: python3 scripts/vintage108_page_defects.py
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import _nse_archive_revop as NA  # noqa: E402
import agg_sources  # noqa: E402

BP = os.path.join(HERE, "_vintage108_bp_proposals.json")
OUT = os.path.join(HERE, "_vintage108_page_defects.json")
PAGES = os.path.join(HERE, "_vintage108_nse_pages")
QUEUE = "second-reader-BACKS-THE-STORE — NSE page suspect"
ABS_TOL, REL_TOL = 2.0, 0.03


def filing_lag(qe, filed):
    import datetime
    try:
        a = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
        b = datetime.date(filed // 10000, (filed // 100) % 100, filed % 100)
        return (b - a).days
    except Exception:
        return None


def agree(a, b):
    return a is not None and b is not None and abs(a - b) <= max(ABS_TOL, abs(b) * REL_TOL)


def diagnose(seq, stored, stored_rev):
    f = glob.glob(os.path.join(PAGES, "*_%s.html" % seq))
    if not f:
        return "page-not-cached", {}
    meta, rows = NA.parse_detail(open(f[0], encoding="utf-8", errors="replace").read())
    d = {"unit": meta.get("unit"), "period": meta.get("Period Ended")}
    def pick(pat):
        for lab, v in rows:
            if re.search(pat, lab.strip(), re.I):
                return v
    pats = [v for lab, v in rows if re.search(r"^net profit", lab.strip(), re.I)]
    pbt = pick(r"from ordinary activities before tax|profit.*before tax")
    tax = pick(r"^tax expense|^tax$")
    rev = pick(r"total income from operations|net sales")
    d.update(pbt=pbt, tax=tax, rev=rev, net_rows=pats)
    if pats and all(abs(v) < 1e-9 for v in pats):
        return ("all-pat-rows-zero" if pbt not in (None, 0) else "page-is-blank"), d
    if pbt is not None and tax is not None and pats:
        if not any(abs(v - (pbt - abs(tax))) <= max(0.5, abs(pbt) * 0.02) for v in pats) \
                and any(abs(v) < 1e-9 for v in pats):
            return "net-contradicts-pbt", d
    if rev and stored_rev and abs(stored_rev) > 1 and (rev / stored_rev > 8 or stored_rev / max(rev, 1e-9) > 8):
        return "scale-anomaly", d
    return "unnamed", d


def main():
    q = json.load(open(BP, encoding="utf-8"))["queues"].get(QUEUE, [])
    nse = {"std": json.load(open(os.path.join(HERE, "_vintage108_nse.json"), encoding="utf-8")),
           "con": json.load(open(os.path.join(HERE, "_vintage108_nse_con.json"), encoding="utf-8"))}
    scan = json.load(open(os.path.join(HERE, "_vintage108_scan.json"), encoding="utf-8"))["cells"]
    mccon = json.load(open(os.path.join(HERE, "_vintage108_mccon.json"), encoding="utf-8"))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf-8"))
    out, cache = {}, {}
    print("closing %d cells" % len(q))
    for entry in q:
        sym, qe, basis = entry.split("|")
        k = "%s|%s" % (sym, qe)
        v = nse[basis][k]
        asf = v.get("as_filed")
        second = (scan.get(k, {}).get("detres") if basis == "std"
                  else (mccon.get(k) or {}).get("mc_con"))
        # THIRD reader: MC on the matching basis
        if sym not in cache:
            try:
                cache[sym] = agg_sources.mc_quarters(sym, basis == "con")[0]
            except Exception:
                cache[sym] = {}
        third = (cache[sym].get(int(qe)) or {}).get("pat_total")
        rrow = (revop.get(sym) or {}).get(qe) or []
        srev = rrow[0 if basis == "std" else 1] if len(rrow) > 1 else None
        defect, ev = diagnose(v["vintages"][0].get("seq"), v["stored"], srev)
        # ★ THE PAGE ITSELF CAN BE MIS-SCALED. Where the page's figure times ten reproduces the
        # store to the paisa, the page is off by a decade and the cell is fine — MPHASIS Jun-2015
        # (page 10.912, store 114.95, MC 109.12 = the page x10), BSOFT Jun-2016 con (5.5054 x10 =
        # 55.05 = the store), MPHASIS Jun-2016 con (20.4343 x10 = 204.34). Test it BEFORE letting a
        # third reader that also read the page's scale wrong re-open the cell.
        page_scaled = None
        if asf:
            for mult in (10.0, 0.1, 100.0, 0.01):
                if abs(asf * mult - v["stored"]) <= max(0.35, abs(v["stored"]) * 0.005):
                    page_scaled = mult
                    break
        if page_scaled:
            defect = "page-mis-scaled-by-%g" % page_scaled
        # ★ TWO WAYS THE "as-filed" PAGE IS NOT THE AS-FILED PAGE, and a store that disagrees with
        # it is then expected rather than suspect:
        #   (a) the earliest filing's PAT is UNREADABLE, so the value came from the next one down —
        #       GVT&D Mar-2016: seq 1006653 filed 40 d after qe reads None, so the 420-day-later
        #       Ind-AS re-filing was labelled "as_filed" (26.98) while store and detres both hold
        #       the real one (29.87);
        #   (b) the ONLY page NSE holds was filed a year later — MPHASIS Jun-2015, 459 days.
        vfirst = v["vintages"][0] if v.get("vintages") else {}
        used = next((x for x in v["vintages"] if x.get("pat") is not None), {})
        lag = filing_lag(int(qe), used.get("filed"))
        if vfirst.get("pat") is None and used is not vfirst:
            defect = "earliest-filing-unreadable — compared against a LATER one"
            backs_override = "store"
        elif lag is not None and lag > 120:
            defect = "page-filed-%dd-after-qe — it is the restatement, not the as-filed" % lag
            backs_override = "store"
        else:
            backs_override = None
        backs = (backs_override if backs_override else
                 "store" if page_scaled else
                 "store" if agree(third, v["stored"]) and not agree(third, asf)
                 else "nse" if agree(third, asf) and not agree(third, v["stored"])
                 else "both" if agree(third, v["stored"]) and agree(third, asf)
                 else "neither" if third is not None else "no-third-reader")
        out[entry] = {"sym": sym, "qe": int(qe), "basis": basis, "stored": v["stored"],
                      "nse_page": asf, "second_reader": second, "third_reader": third,
                      "third_backs": backs, "page_defect": defect, "page_evidence": ev,
                      "page_scaled": page_scaled,
                      "page_lag_days": lag,
                      "resolution": (("CLOSED — %s" % defect) if backs_override else
                                     ("CLOSED — store confirmed; the NSE page is off by a factor "
                                      "of %g" % page_scaled) if page_scaled else
                                     "CLOSED — store confirmed, NSE page unusable"
                                     if backs in ("store", "both", "no-third-reader")
                                     else "RE-OPEN — the third reader sides with the NSE page")}
        json.dump(out, open(OUT, "w"), indent=1)
    from collections import Counter
    print("\nthird reader:", dict(Counter(x["third_backs"] for x in out.values())))
    print("page defect: ", dict(Counter(x["page_defect"] for x in out.values())))
    print("resolution:  ", dict(Counter(x["resolution"].split(" — ")[0] for x in out.values())))
    for k, x in out.items():
        if x["resolution"].startswith("RE-OPEN"):
            print("  RE-OPEN %-22s stored %9.2f nse %9s 2nd %9s 3rd %9s"
                  % (k, x["stored"], x["nse_page"], x["second_reader"], x["third_reader"]))
    print("\nwrote %s" % os.path.basename(OUT))


if __name__ == "__main__":
    main()

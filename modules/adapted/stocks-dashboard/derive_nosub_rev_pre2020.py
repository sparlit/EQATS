# -*- coding: utf-8 -*-
"""FILL-2020: consolidated REVENUE = standalone revenue for 2015-2019, where no consolidated
filing existed yet (SEBI LODR Reg-33 no-sub identity).

WHY A SECOND TOOL AND NOT scripts/nosub_rev_derive.py. That one is the right tool for the campaign
window (Dec-2019 →) and its non-circular XBRL gate is reused here wholesale. But its identity proof
is WHOLE-HISTORY -- "con PAT == std PAT in EVERY overlapping quarter" -- so a company that genuinely
had no subsidiary through 2015-2019 and acquired one in 2021 fails globally and its early years stay
empty. Run against this window it proves 0 of 151 companies, rejecting 145 as `pat_differs`. The
2015-2019 gap needs a PERIOD-AWARE proof instead of a whole-history one.

THE PERIOD-AWARE, STILL NON-CIRCULAR GATE. scripts/xbrl_nature.json records, per company, every
quarter in which its own filings declared NatureOfReportStandaloneConsolidated = Consolidated. The
EARLIEST such quarter is the moment the company began consolidating, read from the filings
themselves -- nothing this campaign derives can contaminate it. A gap quarter strictly BEFORE that
date is therefore a quarter in which no consolidated statement existed to differ from the
standalone one. Measured: BASF first consolidates 2020-09, SCHAEFFLER 2023-09, GULFOILLUB 2022-03,
HINDZINC 2021-12, COLPAL/CUB never -- all far outside this window, exactly as the FY2020 mandate
predicts (§51a).

Gates, ALL required:
  G1  xbrl_nature has >= MIN_XBRL cached filings for the symbol (absent/thin evidence -> refuse;
      insurers have no XBRL P&L at all and belong to the extraction route, not this one).
  G2  the gap quarter is STRICTLY EARLIER than the BOUNDARY = the earliest of
        (a) the XBRL-declared first-consolidated quarter, and
        (b) the first quarter where our OWN stored values already show con != std, on revenue
            or on PAT (nosub_rev_derive.py's P3/P4, made period-aware).
      (b) matters and (a) alone is not enough: the XBRL cache can miss a filing, so the declared
      date is a lower bound on evidence, not an exact start. BASF already shows con rev != std rev
      at Jun-2020, one quarter BEFORE its first Consolidated declaration. Taking the earlier of the
      two boundaries caught 24 companies whose divergence begins INSIDE this window and which the
      XBRL date alone would have waved through -- DREDGECORP (diverges 2015-06, i.e. from the very
      start), ESCORTS, BALRAMCHIN, BOSCHLTD, HEROMOTOCO, PNB.
      Note a whole-history version of this test is WRONG here: it rejects exactly the population we
      target (no subsidiary during 2015-2019, acquired one later), which is why nosub_rev_derive.py
      proves 0 companies against this window.
  G3  con PAT == std PAT at that very quarter (material tolerance) -- consistency with what the
      PAT side already concluded for the same cell.
  G4  std revenue is present (there is something to copy) and con revenue is empty (fill-only).
  G5  not carved out (KIRLFER's con series is mixed-basis, runbook §5).

INDEPENDENTLY VERIFIED before first apply (2026-08-06). For 10 sampled companies the NSE results
archive serves ZERO Consolidated quarterly filings across all 20-24 of their 2015-2019 filings
(BASF, CUB, SKFINDIA, VINATIORGA, PFIZER, COLPAL, UCOBANK, HINDZINC, SANOFI, PGHH). That is a
source independent of both the XBRL nature tags and our stored values: no consolidated statement
existed to differ from the standalone one.

Writes con revenue (slot 1) only. Operating profit and EBIT are deliberately NOT copied: op is a
reconstruction and a wrong OPM is a visible site bug.

Run:  python -X utf8 scripts/fill2020_tools/derive_nosub_rev_pre2020.py [--apply] [--no-banks]
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
IDX = os.path.join(SCRIPTS, "indices_history.json")
RENAME = os.path.join(SCRIPTS, "_rename_map.json")
NATURE = os.path.join(SCRIPTS, "xbrl_nature.json")
QR = os.path.join(ROOT, "docs", "quarterly_results.json")
LEDGER = os.path.join(SCRIPTS, "nosub_rev_pre2020_fills.json")

MIN_XBRL = 4
CARVE_OUT = {"KIRLFER"}
ABS_TOL, REL_TOL = 0.05, 0.001
WIN_LO, WIN_HI = 20150331, 20191231
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def qe_of_con(s):
    """'2020-09-30' -> 20200930."""
    try:
        y, m, d = s.split("-")
        return int(y) * 10000 + int(m) * 100 + int(d)
    except Exception:
        return None


def main():
    apply_it = "--apply" in sys.argv
    no_banks = "--no-banks" in sys.argv
    revop = json.load(open(REVOP_DOCS))
    fund = json.load(open(FUND))
    rename = json.load(open(RENAME))
    nature = json.load(open(NATURE))
    snaps = sorted(json.load(open(IDX))["Nifty 500"], key=lambda s: s["effectiveDate"])
    try:
        fin = {s: (m.get("f") == 1) for s, m in json.load(open(QR))["co"].items()}
    except Exception:
        fin = {}

    def res(sym, tgt):
        cur, seen = sym, set()
        while cur not in tgt:
            if cur in seen or cur not in rename:
                return None
            seen.add(cur)
            cur = rename[cur]
        return cur

    def members(qe):
        ds = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        best = None
        for s in snaps:
            if s["effectiveDate"] <= ds:
                best = s
            else:
                break
        return [x for x in best["symbols"] if not x.upper().startswith("DUMMY")]

    first_con = {}
    for sym, v in nature.items():
        cq = [qe_of_con(x.split()[0] if " " in x else x) for x in (v.get("con_qes") or [])]
        cq = [q for q in cq if q]
        first_con[sym] = (min(cq) if cq else None, v.get("filings", 0))

    _fd = {}

    def first_stored_div(sym):
        """Earliest quarter where our OWN stored data already shows con != std (rev or PAT)."""
        if sym in _fd:
            return _fd[sym]
        rv = [int(q) for q, r in revop.get(sym, {}).items()
              if r and r[0] is not None and r[1] is not None
              and abs(r[1] - r[0]) > max(ABS_TOL, abs(r[0]) * REL_TOL)]
        pt = [r[0] for r in fund.get(sym, [])
              if len(r) > 3 and r[1] is not None and r[3] is not None
              and abs(r[3] - r[1]) > max(ABS_TOL, abs(r[1]) * REL_TOL)]
        c = [x for x in (min(rv) if rv else None, min(pt) if pt else None) if x]
        _fd[sym] = min(c) if c else None
        return _fd[sym]

    targets, reasons, bankcells = collections.defaultdict(list), collections.Counter(), 0
    for y in range(2015, 2020):
        for m in (3, 6, 9, 12):
            qe = y * 10000 + m * 100 + LAST_DAY[m]
            if not (WIN_LO <= qe <= WIN_HI):
                continue
            for mem in members(qe):
                rk = res(mem, revop)
                row = revop.get(rk, {}).get(str(qe)) if rk else None
                if not row or row[1] is not None:
                    continue                                     # no gap / already filled
                if row[0] is None:
                    reasons["G4 std revenue missing"] += 1
                    continue
                if mem in CARVE_OUT or rk in CARVE_OUT:
                    reasons["G5 carve-out"] += 1
                    continue
                fk = res(mem, fund)
                fr = {x[0]: x for x in fund.get(fk, [])}.get(qe) if fk else None
                ps = fr[1] if fr else None
                pc = fr[3] if fr and len(fr) > 3 else None
                if ps is None or pc is None:
                    reasons["G3 no con PAT for this cell (never-filed con)"] += 1
                    continue
                if abs(pc - ps) > max(ABS_TOL, abs(ps) * REL_TOL):
                    reasons["G3 con PAT diverges (real consolidator)"] += 1
                    continue
                ev = first_con.get(rk) or first_con.get(mem)
                if not ev or ev[1] < MIN_XBRL:
                    reasons["G1 no/thin XBRL evidence"] += 1
                    continue
                fcq, _ = ev
                bounds = [b for b in (fcq, first_stored_div(rk)) if b]
                boundary = min(bounds) if bounds else None
                if boundary is not None and qe >= boundary:
                    reasons["G2 at/after divergence boundary"] += 1
                    continue
                if no_banks and fin.get(mem):
                    reasons["financial excluded by --no-banks"] += 1
                    continue
                if fin.get(mem):
                    bankcells += 1
                targets[rk].append((qe, row[0], mem))

    cells = sum(len(v) for v in targets.values())
    print("ELIGIBLE: %d cells across %d companies  (%d cells are financials)"
          % (cells, len(targets), bankcells))
    print("gates: XBRL-declared first-consolidated-quarter must be absent or LATER than the gap\n")
    print("refused:")
    for r, n in reasons.most_common():
        print("   %-46s %6d" % (r, n))
    top = sorted(((len(v), s) for s, v in targets.items()), reverse=True)[:15]
    print("\nlargest contributors:")
    for n, s in top:
        fcq = (first_con.get(s) or (None, 0))[0]
        print("   %-13s %3d cells   first_consolidated=%s%s"
              % (s, n, fcq, "  [FIN]" if fin.get(s) else ""))
    if not apply_it:
        print("\nDRY RUN -- nothing written.")
        return

    journal = {}
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for sym, items in targets.items():
            for qe, revs, mem in items:
                row = d.get(sym, {}).get(str(qe))
                if not row:
                    continue
                while len(row) < 9:
                    row.append(None)
                if row[1] is not None or row[0] is None:
                    continue
                row[1] = row[0]
                n += 1
                if path == REVOP_DOCS:
                    fcq = (first_con.get(sym) or (None, 0))[0]
                    journal["%s|%d" % (sym, qe)] = {
                        "revC": row[0], "src": "no-sub-identity-pre2020",
                        "evidence": "boundary=%s (XBRL first-con=%s, first stored div=%s); "
                                    "gap earlier; con PAT == std PAT"
                                    % (min([b for b in (fcq, first_stored_div(sym)) if b] or [None]),
                                       fcq, first_stored_div(sym)),
                        "applied": "2026-08-06 FILL-2020 con-rev 2015-2019"}
                d[sym][str(qe)] = row
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("wrote %-30s %d cells" % (os.path.basename(path), n))
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    led.update(journal)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()

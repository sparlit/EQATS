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
"""FILL-2020 pre-2020 con-PAT: read CONSOLIDATED PAT from the NSE archive detail pages.

Consumes _con_nse_inventory.json (the discovery sweep) and reads only the gap cells that
actually have a consolidated filing. Runbook §51a: most pre-FY2020 con quarters were never
filed, so this route's ceiling is small by nature -- the point is to land what genuinely exists,
with the same anchor discipline as every other route.

THE ANCHOR PROBLEM, AND THE FIX. Every other backfill anchors the read against the stored PAT
for that (sym, qe, basis). Here the stored con IS the gap -- there is nothing to anchor to. So
gates, in priority order (at least one must pass; all are recorded):

  GATE S' (sibling-basis, strongest and preferred). Fetch the NON-Consolidated page for the SAME
      quarter and check its owners-PAT against our STORED std within max(0.05cr, 0.5%). That
      proves source + scale + period-mapping + symbol identity for this exact company-quarter;
      the consolidated page then comes from the same page family under the same declared unit.
      This is the SpiceJet manoeuvre generalised (validate the document via the basis you already
      hold, then read the basis you don't).
  GATE E (EPS reconstruction on the con page itself). PAT_cr == eps * eqcap_cr / fv, within 6%.
      The unit divisor cancels in that expression, so it is immune to the parser scaling
      per-share rows (Face Value prints as 0.02 for a Rs 2 share after the lakh division).
  GATE F (FY identity). The four con quarters of the fiscal year sum to the con ANNUAL row within
      max(3cr, 3%). Siblings may come from our stored con or from other con pages in the same FY.

ANTI-POISON, all mandatory before any figure is used (STEP N/W discipline):
  * the page's own "Consolidated / Non-Consolidated" must read Consolidated,
  * its "Period Ended" must equal the target quarter (never trust the list row's date alone),
  * its "Symbol" must be one of the target's known era-spellings (NSE rewrites archive filenames
    to the CURRENT symbol while the stored file keeps the old one -- get_detail handles the 404
    fallback, but identity is re-checked from the page body).

PAT row preference: "Net Profit/(Loss) after taxes, minority interest and share of profit of
associates" (owners-attributable = this dataset's basis, memory project-stocks-profit-basis).
Falls back to the plain period row ONLY when minority interest is absent or zero.

Writes nothing directly: lands to scripts/con_pat_nse_reads.json for review, then --apply merges
fill-only into docs/sf_fundamentals.json + scripts/fundamentals.json.

Run:  python -X utf8 scripts/fill2020_tools/read_con_pat_nse.py [--limit N] [--only SYM,SYM]
      python -X utf8 scripts/fill2020_tools/read_con_pat_nse.py --apply
"""
import contextlib
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
_spec.loader.exec_module(NAR)  # reuse aliases/get_detail/parse_detail/pick
# NAR.get() reads a module-global JAR that NAR.main() normally creates; importing the module
# skips that, so every fetch raised NameError. Seed it here (NAR refreshes it itself on 4xx).
NAR.JAR = NAR.BF.nse_jar()

INV = os.path.join(HERE, "_con_nse_inventory.json")
TARGETS = os.path.join(HERE, "_con_targets_pre2020.json")
READS = os.path.join(SCRIPTS, "con_pat_nse_reads.json")
CACHE = os.path.join(SCRIPTS, "_nsearch_cache")
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(SCRIPTS, "fundamentals.json")

EPS_TOL, FY_ABS, FY_REL = 0.06, 3.0, 0.03
STD_ABS, STD_REL = 0.05, 0.005  # GATE S' tolerance

R_OWN = re.compile(r"net profit.*after\s+taxe?s?.*minority\s+interest", re.IGNORECASE)
R_PERIOD = re.compile(r"net profit\s*/?\s*\(?\s*loss\s*\)?\s*for the period", re.IGNORECASE)
R_MINORITY = re.compile(r"^minority interest", re.IGNORECASE)
R_EQCAP = re.compile(r"paid-?up equity share capital", re.IGNORECASE)
R_FV = re.compile(r"face value", re.IGNORECASE)
R_BASIC = re.compile(r"^\(?a\)?\s*basic", re.IGNORECASE)
# PRE-2011 ARCHIVE TEMPLATE (measured on the MPHASIS Mar-2008 and GMRINFRA Sep-2010 pages,
# 2026-09-02, CON-GAP PRE-2020 campaign). The labels differ from both later templates:
#   "Net Profit (+) / Loss (-) for the period"               = the period row (before MI/associates)
#   "Minority Interest" / "Shares of Associates"              = SIGNED deductions
#   "Consolidated Net Profit (+) / Loss (-) for the period"   = period - MI - associates = OWNERS
# GMRINFRA Sep-2010 prints 42.53 - (-25.98) - (-2.61) = 71.12 on that last row exactly. In the
# Ind-AS-era template (§53e) the "Consolidated Net Profit" row merely DUPLICATES the period row, so
# it is trusted only when it reproduces the deduction identity or when no MI/associates row exists.
R_PERIOD_OLD = re.compile(r"^net profit\s*\(\+\)\s*/\s*loss\s*\(-\)\s*for the period", re.IGNORECASE)
R_CONNET = re.compile(r"^consolidated net profit.*for the period", re.IGNORECASE)
R_ASSOC = re.compile(r"^shares? of\b.*associates", re.IGNORECASE)
# the old template prints "Basic EPS before/after Extraordinary items (in Rs.)" with no "(a)"
# serial, which R_BASIC (written for "(a) Basic") never matched -> every 2005-2010 page read as
# "eps-inputs-missing". Both spellings are candidates; the recon still has to land within 6%.
R_BASIC_OLD = re.compile(r"^basic\s+eps\b", re.IGNORECASE)
IDENT_ABS, IDENT_REL = 0.02, 0.002  # on-page identity tolerance (print rounding)


def owners_pat(rows, want_con):
    """Owners-attributable PAT from the page rows -> (value, mode) or (None, refusal reason).
    Modes are journalled so a later session can see WHICH convention produced each figure."""
    own = NAR.pick(rows, R_OWN)
    per = NAR.pick(rows, R_PERIOD, R_PERIOD_OLD)
    mi = NAR.pick(rows, R_MINORITY)
    assoc = NAR.pick(rows, R_ASSOC)
    connet = NAR.pick(rows, R_CONNET)
    if own is not None:
        return own, "owners-row"
    if per is None:
        return None, "no-pat-row"
    if not want_con:
        return per, "period-row(std)"

    def tol(x):
        return max(IDENT_ABS, abs(x) * IDENT_REL)

    def via_intermediate_rows():
        # ABAN Dec-2010 class: the deduction sits under a generic label ("Other Related Items"
        # 43.26) between the period row (105.27) and the consolidated row (62.02). Accept the
        # consolidated row when the rows printed BETWEEN the two close the identity exactly; the
        # EPS gate still has to reconcile to the figure chosen (ABAN: 0.1425*8.7033/0.02 = 62.01).
        labs = [lab.strip() for lab, _ in rows]
        ip = next((i for i, l in enumerate(labs) if R_PERIOD.search(l) or R_PERIOD_OLD.search(l)), None)
        ic = next((i for i, l in enumerate(labs) if R_CONNET.search(l)), None)
        if ip is not None and ic is not None and ic > ip + 1:
            mid = [v for _, v in rows[ip + 1 : ic]]
            if abs(per - sum(mid) - connet) <= tol(connet):
                return connet, "connet==period-minus-intermediate-rows({})".format(
                    "; ".join(f"{l[:28]}={v:.2f}" for l, v in rows[ip + 1 : ic])
                )
        return None, None

    if mi in (None, 0.0) and assoc in (None, 0.0):
        if connet is not None and abs(connet - per) > tol(per):
            v, mode = via_intermediate_rows()
            if v is not None:
                return v, mode
            return None, f"connet-differs-from-period-without-MI({connet:.2f} vs {per:.2f})"
        return per, "period-row(no-MI)"
    ident = per - (mi or 0.0) - (assoc or 0.0)
    if connet is not None and abs(connet - ident) <= tol(ident):
        return connet, "connet==period-MI-assoc(old template)"
    if connet is not None:
        v, mode = via_intermediate_rows()
        if v is not None:
            return v, mode
    if connet is not None and abs(connet - per) <= tol(per):
        # Ind-AS template: the consolidated row duplicates the period row (§53e convention,
        # calibrated 49/49 on that template): owners = period - minority - associates
        return ident, "deduction-identity(§53e)"
    if connet is None:
        return None, "no-owners-row-but-minority-present"
    return None, f"owners-identity-unresolved(per {per:.2f} mi {mi} assoc {assoc} connet {connet:.2f})"


def qe_of(s):
    return NAR.iso_qe(s)


def read_page(link, sym, qe, want_con):
    """Fetch + validate one detail page. Returns (pat, meta, rows) or (None, reason, None)."""
    path = os.path.join(CACHE, "con_%s_%d_%s.html" % (sym.replace("&", "_"), qe, "c" if want_con else "s"))
    try:
        html = NAR.get_detail(link, sym, path)
    except Exception as ex:
        return None, f"fetch:{type(ex).__name__}", None
    meta, rows = NAR.parse_detail(html)
    basis = meta.get("Consolidated / Non-Consolidated", "")
    # §53e: a page with NO declared basis and no rows is the archive's content-free shell
    # (symbols containing '&', 0-byte files) -- say so, never "basis-mismatch:?", which sent a
    # whole pass hunting for a better link.
    if not basis and not rows:
        return None, "empty-shell(no meta, %d bytes)" % len(html), None
    is_con = basis.strip().lower() == "consolidated"
    if is_con != want_con:
        return None, "basis-mismatch:%s" % (basis or "?"), None
    if qe_of(meta.get("Period Ended", "")) != qe:
        return None, "period-mismatch:{}".format(meta.get("Period Ended")), None
    # aliases() returns the OTHER era spellings, not the symbol itself -- omitting sym rejected
    # every page whose Symbol was simply the current one (BALLARPUR "mismatched" itself).
    if (meta.get("Symbol") or "").upper() not in {a.upper() for a in ([sym, *NAR.aliases(sym)])}:
        return None, "symbol-mismatch:{}".format(meta.get("Symbol")), None
    # CUMULATIVE PAGES ARE YEAR-TO-DATE, NOT THE QUARTER. parse_detail does not surface this field,
    # so read it from the body: a Q2/Q3/Q4 cumulative row would land a 6/9/12-month figure as a
    # quarter. (PRE2015 STEP N carries the same check.)
    m = re.search(r"Cumulative\s*/\s*Non-?Cumulative\s*\|?\s*(Non-?Cumulative|Cumulative)", html, re.IGNORECASE)
    if m and m.group(1).lower().replace("-", "").startswith("cumulative"):
        return None, "cumulative-page(YTD not quarter)", None
    pat, mode = owners_pat(rows, want_con)
    if pat is None:
        return None, mode, None
    meta["pat_mode"] = mode
    # BLANK TEMPLATE PAGES. Some filers submitted the consolidated form with every P&L row left at
    # 0.00 (SUNTV Mar-2017: profit, tax, EPS, minority all 0.0; only Paid-up equity populated).
    # The page validates on basis/period/symbol and its sibling std page is perfectly good, so
    # nothing upstream catches it -- but the consolidated figures were simply never entered. A
    # genuine consolidated PAT of exactly 0.00 is vanishingly unlikely; refusing it costs at most
    # one real cell and blocks a whole class of silent zero-fills.
    if abs(pat) < 1e-9:
        return None, "blank-template(all-zero con page)", None
    return pat, meta, rows


_LIST_CACHE = {}


def std_link(sym, qe, key=None):
    """resultDetailedDataLink of the NON-Consolidated filing for this quarter, or None.
    `key` (the fundamentals key = the CURRENT name, e.g. BBOX for era symbol AGCNET) is queried
    too: NAR.list_rows(sym) merges only names OLDER than sym, so a std row filed under the newer
    name was invisible and GATE S' silently read as unavailable for every era-named symbol."""
    if sym not in _LIST_CACHE:
        try:
            _LIST_CACHE[sym] = NAR.list_rows(sym)
        except Exception:
            _LIST_CACHE[sym] = []
        if key and key.upper() != sym.upper():
            with contextlib.suppress(Exception):
                _LIST_CACHE[sym] = _LIST_CACHE[sym] + NAR.list_rows(key)
        time.sleep(0.5)
    for row in _LIST_CACHE[sym]:
        if (row.get("consolidated") or "").strip().lower().startswith("non"):
            if qe_of(row.get("toDate") or "") == qe and row.get("resultDetailedDataLink"):
                return row["resultDetailedDataLink"]
    return None


def eps_gate(pat, rows):
    """PAT == eps * eqcap / fv. The declared-unit divisor cancels, so per-share rows scaled by
    the parser (Face Value 2 -> 0.02 under lakhs) are harmless here."""
    eq, fv = NAR.pick(rows, R_EQCAP), NAR.pick(rows, R_FV)
    # §53e: test EVERY basic-EPS row (before/after extraordinary items) and journal which one
    # matched -- the archive prints both, and a first-match-only read picked the wrong one.
    cands = [
        (lab, v)
        for lab, v in rows
        if R_BASIC.search(lab.strip())
        or R_BASIC.search(NAR.ROWNUM.sub("", lab.strip()))
        or R_BASIC_OLD.search(lab.strip())
    ]
    if not (eq and fv and cands) or abs(pat) < 1e-9:
        return None, "eps-inputs-missing"
    best = None
    for lab, eps in cands:
        recon = eps * eq / fv
        err = abs(recon - pat) / abs(pat)
        if best is None or err < best[0]:
            best = (err, recon, lab.strip())
    err, recon, lab = best
    return (err <= EPS_TOL), f"eps {err * 100:.1f}% (recon {recon:.2f} vs {pat:.2f}; row '{lab[:45]}')"


def main():
    args = sys.argv[1:]
    # --inv / --targets: another campaign's inventory + target files (CON-GAP PRE-2020 uses
    # con_discover_pre2015.py's _con_pre2015_nse_inventory.json, whose per-cell entries are dicts
    # carrying the exchange filing date). Defaults keep the 2015-19 behaviour byte-identical.
    inv_path = args[args.index("--inv") + 1] if "--inv" in args else INV
    tgt_path = args[args.index("--targets") + 1] if "--targets" in args else TARGETS
    # --reads PATH: a private ledger for one shard of a parallel run (two readers writing the
    # shared ledger every 10 cells would clobber each other); merge shards back with
    # merge_con_reads.py before --apply. The shard still SEEDS its skip-list from the shared
    # ledger so no cell is read twice.
    global READS
    shard_reads = args[args.index("--reads") + 1] if "--reads" in args else None
    if "--apply" in args:
        return apply_reads(inv_path if "--inv" in args else None, tgt_path)
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    if not os.path.exists(inv_path):
        print(f"no inventory yet -- run the discovery sweep first ({inv_path})")
        return None
    inv = json.load(open(inv_path))
    fund = json.load(open(DOCS))
    targets = json.load(open(tgt_path))
    reads = json.load(open(READS)) if os.path.exists(READS) else {}
    if shard_reads:
        done_keys = set(reads)  # shared ledger = what NOT to re-read
        reads = json.load(open(shard_reads)) if os.path.exists(shard_reads) else {}
        READS = shard_reads
    else:
        done_keys = set(reads)
    os.makedirs(CACHE, exist_ok=True)

    work = []
    for sym, rec in sorted(inv.items()):
        if only and sym not in only:
            continue
        qmap = rec.get("con_qtr") if "con_qtr" in rec else (rec.get("qtr") or {})
        for qe_s, ent in sorted((qmap or {}).items()):
            if f"{sym}|{qe_s}" in done_keys or f"{sym}|{qe_s}" in reads:
                continue
            link = ent["link"] if isinstance(ent, dict) else ent
            filed = ent.get("filed") if isinstance(ent, dict) else None
            if link:
                work.append((sym, int(qe_s), link, filed))
    if limit:
        work = work[:limit]
    print("con-PAT reads to attempt: %d" % len(work), flush=True)

    ok = skip = 0
    for i, (sym, qe, link, filed) in enumerate(work):
        key = targets.get(sym, {}).get("key", sym)
        stdrow = {r[0]: r for r in fund.get(key, [])}.get(qe)
        stored_std = stdrow[1] if stdrow else None
        pat, meta, rows = read_page(link, sym, qe, True)
        time.sleep(0.7)
        if pat is None:
            reads["%s|%d" % (sym, qe)] = {"skip": meta}
            skip += 1
            print("  SKIP %-12s %d  %s" % (sym, qe, meta), flush=True)
            continue
        gates, passed = [], False
        # GATE S' -- validate the document family via the basis we already hold.
        # The std link comes from NAR.list_rows (disk-cached, alias-aware: it merges the era
        # spellings, which matters because NSE rewrites archive filenames to the CURRENT symbol).
        srec = std_link(sym, qe, key)
        blocked = None
        spat, stdrows = None, None
        if stored_std is not None and srec:
            spat, smeta, stdrows = read_page(srec, sym, qe, False)
            time.sleep(0.7)
            if spat is not None:
                d = abs(spat - stored_std)
                good = d <= max(STD_ABS, abs(stored_std) * STD_REL)
                gates.append("S':{} std_page={:.2f} stored={:.2f}".format("PASS" if good else "FAIL", spat, stored_std))
                passed = passed or good
                # A FAILING S' is a HARD BLOCK, not merely an unpassed gate. It means this page
                # family disagrees with a value we already hold for the same company-quarter --
                # revised filing, restatement, or period mis-mapping. Whatever the cause, a
                # consolidated figure read from the same family cannot be trusted, and GATE E
                # (an internal self-consistency check) cannot rescue it: EPS and PAT can agree
                # with each other on a page that is describing a different period entirely.
                if not good:
                    blocked = f"S'-mismatch (std page {spat:.2f} vs stored {stored_std:.2f})"
            else:
                gates.append(f"S':unavailable({smeta})")
        eg, note = eps_gate(pat, rows)
        # §53e GATE C -- the EPS POSITIVE CONTROL, run on the same filing's STANDALONE page whose
        # PAT just reproduced our stored std to the paisa (S' PASS). EPS is computed on the
        # weighted-average share count while the page prints PERIOD-END paid-up capital, so in a
        # quarter with a rights issue / QIP / conversion the recon misses on BOTH bases by the
        # same margin. If the std page misses by (nearly) the same error, the miss is the share
        # count, not the row choice, and the con figure stands; if the std page reconciles while
        # the con page does not, the picked con row is suspect and the block stays.
        if eg is False and stdrows is not None and spat is not None:
            ceg, cnote = eps_gate(spat, stdrows)
            m = re.search(r"eps ([\d.]+)%", note)
            mc = re.search(r"eps ([\d.]+)%", cnote)
            if ceg is False and m and mc and abs(float(m.group(1)) - float(mc.group(1))) <= 3.0:
                eg = True
                note += f" | CONTROLLED: std page misses identically ({cnote})"
            else:
                note += f" | control: std page {cnote}"
        gates.append("E:{} {}".format({True: "PASS", False: "FAIL", None: "n/a"}[eg], note))
        passed = passed or (eg is True)
        # A FAILING E is also a hard block, for the same reason as S': GATE S' validates the page
        # FAMILY (source, scale, period, identity) via the std sibling, but it says nothing about
        # WHICH ROW was picked on the CON page. Where the con page does carry EPS + equity, that
        # reconstruction is the only check on the row choice, so a failure means the picked row is
        # wrong even though the document is right (TATASTEEL Sep-2016: recon -230.92 vs picked
        # -54.42). E:n/a -- inputs genuinely absent -- stays acceptable when S' passed.
        if eg is False:
            blocked = blocked or f"E-recon failed ({note})"
        if blocked:
            passed = False
        rec = {
            "con": round(pat, 2),
            "unit": meta.get("unit"),
            "gates": gates,
            "stored_std": stored_std,
            "link": link,
            "pat_mode": meta.get("pat_mode"),
        }
        if filed:
            rec["filed"] = filed  # exchange filing timestamp from the list row
        if passed:
            reads["%s|%d" % (sym, qe)] = rec
            ok += 1
            print(
                "  OK   %-12s %d  con=%-10.2f std=%-10s | %s" % (sym, qe, pat, stored_std, " ; ".join(gates)),
                flush=True,
            )
        else:
            rec["skip"] = blocked or "no-gate-passed"
            reads["%s|%d" % (sym, qe)] = rec
            skip += 1
            print("  SKIP %-12s %d  %s | %s" % (sym, qe, blocked or "no gate passed", " ; ".join(gates)), flush=True)
        if (i + 1) % 10 == 0:
            json.dump(reads, open(READS, "w"), indent=0, sort_keys=True)
    json.dump(reads, open(READS, "w"), indent=0, sort_keys=True)
    print("\nlanded %d | skipped %d  -> %s" % (ok, skip, os.path.basename(READS)))
    return None


def filed_int(s, qe):
    """'01-May-2008 13:45' -> 20080501, or None when unparseable / before the quarter end."""
    d = NAR.iso_qe((s or "").split(" ")[0])
    return d if d and d >= qe else None


def apply_reads(inv_path=None, tgt_path=TARGETS):
    """Fill-only merge into both twins. With inv_path, ONLY reads whose (sym, qe) is a con-quarter
    hit in that inventory are applied -- a re-apply of the whole ledger would otherwise re-land
    every earlier campaign's reads too (fill-only is no defence against a cell a later campaign
    deliberately emptied: memory feedback-held-cell-asserts-absence)."""
    reads = json.load(open(READS))
    good = {k: v for k, v in reads.items() if "con" in v and not v.get("skip")}
    if inv_path:
        inv = json.load(open(inv_path))
        allowed = set()
        for sym, rec in inv.items():
            qmap = rec.get("con_qtr") if "con_qtr" in rec else (rec.get("qtr") or {})
            for qe_s in qmap or {}:
                allowed.add(f"{sym}|{qe_s}")
        good = {k: v for k, v in good.items() if k in allowed}
    targets = json.load(open(tgt_path))
    n_files = []
    applied = []
    for path in (DOCS, MIRROR):
        d = json.load(open(path))
        n = 0
        for k, v in sorted(good.items()):
            sym, qe = k.split("|")
            qe = int(qe)
            key = targets.get(sym, {}).get("key", sym)
            r = {x[0]: x for x in d.get(key, [])}.get(qe)
            if not r:
                continue
            while len(r) < 5:
                r.append(None)
            if r[3] is not None:  # fill-only
                continue
            r[3] = v["con"]
            if r[4] is None:
                # the exchange's own filing timestamp for the CONSOLIDATED row when the list carried
                # one (§52: stored pre-2018 std announce dates are often a qe+45d default, not a
                # filing date); the std announce date otherwise.
                r[4] = filed_int(v.get("filed"), qe) or r[2]
            n += 1
            if path == DOCS:
                applied.append((key, qe, v["con"], r[4]))
        json.dump(d, open(path, "w"), separators=(",", ":"))
        n_files.append(n)
    print(
        "applied: docs %d | mirror %d (of %d landed reads%s)"
        % (n_files[0], n_files[1], len(good), " in inventory scope" if inv_path else "")
    )
    return applied


if __name__ == "__main__":
    main()

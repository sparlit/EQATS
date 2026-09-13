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
"""FILL-2020 con-PAT: re-attempt the archive refusals whose only problem was the OWNERS ROW.

Runbook §53c refused 7 cells as `no-owners-row-but-minority-present`: the Ind-AS-era NSE archive
template drops the explicit "Net Profit/(Loss) after taxes, minority interest and share of profit
of associates" line and prints instead

    Net Profit / (Loss) for the period            <- BEFORE minority / associates
    Share of profit / (loss) of associates        <- printed as a DEDUCTION
    Minority interest                             <- printed as a DEDUCTION
    Consolidated Net Profit/Loss for the period   <- in this template a DUPLICATE of the period row

so the reader had no owners-basis figure and (correctly, at the time) refused rather than land
total PAT on an owners-basis series.

THE CONVENTION, discovered later during the con-REVENUE pass:

    owners = period - minority - associates

⚠️ Unlike the revenue pass, the PAT here IS the value being written, so "offer several variants and
let the anchor pick" is not available -- there is nothing to match against. The convention therefore
has to be ESTABLISHED first and VALIDATED per cell second:

  --calibrate  proves the formula on the same page family and era: cells whose con PAT we already
               store, whose page uses this template, and whose |associates| is large enough that the
               sign actually matters. Only the cases where the variants are separable are counted --
               a near-tie proves nothing.

  per cell     GATE S' (§53a, hard): fetch the NON-consolidated page for the same quarter and check
                   it against our STORED std. Proves source + scale + period + identity.
               GATE E (hard when inputs exist): owners == eps x eqcap / fv, testing EVERY EPS row on
                   the page. The single-row form of this gate produced three FALSE refusals
                   (TATASTEEL x2, JINDALPOLY) because `^\\(?a\\)?\\s*basic` grabs the
                   BEFORE-exceptional-items EPS while the archive also prints the after-exceptional
                   one; the correct EPS variant is not knowable a priori, so all are tried and the
                   matching row is journalled.
               GATE I (identity, when the page DOES print the owners row): owners row ==
                   period - minority - associates. Two independent rows agreeing pins the row choice.
               GATE C (EPS positive control, §51b discipline): before believing a failing GATE E,
                   point it at quarters of the SAME company whose con PAT we already store. Where
                   the filer's EPS reconciles there (JINDALPOLY: 6 of 7 controls exact to the
                   paisa), a failure on the target is real and blocks. Where it never reconciles
                   (TATASTEEL: 4 of 4 controls miss by a near-constant 35-53cr, the signature of an
                   EPS numerator net of hybrid-perpetual/preference distributions), GATE E is
                   NON-DISPOSITIVE for that filer and may not block on its own.
               GATE F (FY identity, §45): the fiscal year's four con quarters -- stored siblings
                   plus this read -- must sum to the AUDITED con annual within max(3cr, 3%).
                   Required whenever GATE E has been ruled non-dispositive.
               Refuse owners == 0 (§53b blank-template rule).

Writes nothing directly: lands to scripts/con_pat_owners_reads.json for review; --apply merges
fill-only into docs/sf_fundamentals.json + scripts/fundamentals.json.

Run:  python3 -X utf8 scripts/fill2020_tools/read_con_pat_owners.py --calibrate [N]
      python3 -X utf8 scripts/fill2020_tools/read_con_pat_owners.py [--only SYM] [--classes a,b]
      python3 -X utf8 scripts/fill2020_tools/read_con_pat_owners.py --apply
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
CONREV_INV = os.path.join(HERE, "_conrev_nse_inventory.json")
CONREV_READS = os.path.join(SCRIPTS, "con_rev_nse_reads.json")
OLD_READS = os.path.join(SCRIPTS, "con_pat_nse_reads.json")
READS = os.path.join(SCRIPTS, "con_pat_owners_reads.json")
CALIB = os.path.join(SCRIPTS, "con_pat_owners_calibration.json")
CACHE = os.path.join(SCRIPTS, "_nsearch_cache")
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(SCRIPTS, "fundamentals.json")

EPS_TOL = 0.06
STD_ABS, STD_REL = 0.05, 0.005  # GATE S' / GATE I tolerance

R_OWN = re.compile(r"net profit.*after\s+taxe?s?.*minority\s+interest", re.IGNORECASE)
R_CONFINAL = re.compile(r"^consolidated net profit\s*/?\s*\(?loss\)?\s*for the period", re.IGNORECASE)
R_PERIOD = re.compile(r"^net profit\s*/?\s*\(?\s*loss\s*\)?\s*for the period", re.IGNORECASE)
R_MINORITY = re.compile(r"^minority interest", re.IGNORECASE)
R_ASSOC = re.compile(r"share of profit.*associat", re.IGNORECASE)
R_EQCAP = re.compile(r"paid-?up equity share capital", re.IGNORECASE)
R_FV = re.compile(r"face value", re.IGNORECASE)
# every EPS row the archive prints: the old template's "(a) Basic" under
# "Earnings Per Share (before/after extraordinary items)", and the Ind-AS template's
# "Basic EPS for continuing / discontinued / continued and discontinued operations".
R_EPS_ANY = re.compile(r"^\(?a\)?[\.\)\s]*basic\b|^basic\s+eps\b|^basic\b.*earnings? per", re.IGNORECASE)


_LIST = {}


def _list_rows(sym):
    if sym not in _LIST:
        try:
            _LIST[sym] = NAR.list_rows(sym)
        except Exception:
            _LIST[sym] = []
        time.sleep(0.5)
    return _LIST[sym]


def rows_matching(rows, pat):
    return [(lab, v) for lab, v in rows if pat.search(lab.strip()) or pat.search(NAR.ROWNUM.sub("", lab.strip()))]


def near(a, b):
    return abs(a - b) <= max(STD_ABS, abs(b) * STD_REL)


def fetch(link, sym, qe, tag):
    path = os.path.join(CACHE, "own_%s_%d_%s.html" % (sym.replace("&", "_"), qe, tag))
    html = NAR.get_detail(link, sym, path)
    meta, rows = NAR.parse_detail(html)
    return html, meta, rows


def validate_page(html, meta, sym, qe, want_con):
    """The §53b anti-poison block, shared by the con page and its std sibling."""
    # An archive page with NO meta at all is not a basis mismatch -- it is the server returning a
    # content-free ~2.9KB shell. §42 records the cause: symbols containing '&' (M&MFIN, J&KBANK)
    # break the archive's own page generator, and no URL escaping fixes it (raw '&' and '%26' both
    # return the shell; '%2526' and de-ampersanded names 404). Reporting it as "basis-mismatch:?"
    # sent a previous pass looking for a wrong link when the link was right and the source is dead.
    if not any(meta.get(k) for k in ("Consolidated / Non-Consolidated", "Period Ended", "Symbol")):
        return "archive-empty-shell(%d bytes; NSE serves no content for this page%s)" % (
            len(html),
            " -- '&' in the symbol, §42" if "&" in sym else "",
        )
    basis = (meta.get("Consolidated / Non-Consolidated") or "").strip().lower()
    if (basis == "consolidated") != want_con:
        return "basis=%s" % (basis or "?")
    if NAR.iso_qe(meta.get("Period Ended", "")) != qe:
        return "period={}".format(meta.get("Period Ended"))
    if (meta.get("Symbol") or "").upper() not in {a.upper() for a in ([sym, *NAR.aliases(sym)])}:
        return "symbol={}".format(meta.get("Symbol"))
    m = re.search(r"Cumulative\s*/\s*Non-?Cumulative\s*\|?\s*(Non-?Cumulative|Cumulative)", html, re.IGNORECASE)
    if m and m.group(1).lower().replace("-", "").startswith("cumulative"):
        return "cumulative-page(YTD not quarter)"
    return None


def owners_of(rows):
    """-> (owners, src, parts) or (None, reason, parts). Never guesses between variants."""
    own = NAR.pick(rows, R_OWN)
    fin = NAR.pick(rows, R_CONFINAL)
    per = NAR.pick(rows, R_PERIOD)
    mi = NAR.pick(rows, R_MINORITY)
    asc = NAR.pick(rows, R_ASSOC)
    parts = {"owners_row": own, "consolidated_final_row": fin, "period": per, "minority": mi, "associates": asc}
    if own is not None:
        return own, "owners-row", parts
    # A "Consolidated Net Profit/Loss for the period" that DIFFERS from the period row is the
    # template's real owners line; where it merely duplicates the period row (the Ind-AS archive
    # form these refusals hit) it carries no information and the deduction convention applies.
    if fin is not None and per is not None and not near(fin, per):
        return fin, "consolidated-final-row", parts
    if per is None:
        return None, "no-period-row", parts
    if mi in (None, 0.0) and asc in (None, 0.0):
        return per, "period-row(no-minority-no-associates)", parts
    if mi is None:
        return None, "no-minority-row", parts
    return per - mi - (asc or 0.0), "period-minority-assoc", parts


def eps_gate(pat, rows):
    """owners == eps x eqcap / fv, over EVERY EPS row the page prints."""
    eq, fv = NAR.pick(rows, R_EQCAP), NAR.pick(rows, R_FV)
    cands = rows_matching(rows, R_EPS_ANY)
    if not (eq and fv and cands) or abs(pat) < 1e-9:
        return None, "eps-inputs-missing"
    best = None
    for lab, eps in cands:
        if abs(eps) < 1e-12:
            continue
        recon = eps * eq / fv
        err = abs(recon - pat) / abs(pat)
        if best is None or err < best[0]:
            best = (err, lab.strip()[:44], recon)
    if best is None:
        return None, "eps-all-zero"
    return (best[0] <= EPS_TOL), f"eps {best[0] * 100:.1f}% via {best[1]!r} (recon {best[2]:.2f} vs {pat:.2f})"


# ------------------------------------------------- GATE C / GATE F (rescue pair)


_CTL = {}


def eps_control(sym, fund, want=4):
    """Does THIS filer's archive EPS reconcile where we already know the answer?

    -> (dispositive, note). dispositive False means every control quarter misses, so a GATE E
    failure on the target says nothing about the read (runbook §51b: never believe a negative
    without a positive control)."""
    if sym in _CTL:
        return _CTL[sym]
    stored = {r[0]: (r[3] if len(r) > 3 else None) for r in fund.get(sym, [])}
    errs = []
    for lr in _list_rows(sym):
        if len(errs) >= want:
            break
        qe = NAR.iso_qe(lr.get("toDate") or "")
        link = lr.get("resultDetailedDataLink")
        if not qe or not link or not (lr.get("consolidated") or "").lower().startswith("cons"):
            continue
        if stored.get(qe) is None:
            continue
        try:
            html, meta, rows = fetch(link, sym, qe, "ctl")
        except Exception:
            continue
        time.sleep(0.6)
        if validate_page(html, meta, sym, qe, True):
            continue
        eg, note = eps_gate(stored[qe], rows)
        if eg is None:
            continue
        errs.append((qe, eg, note))
    if not errs:
        _CTL[sym] = (True, "control:none-available")
        return _CTL[sym]
    good = sum(1 for _, eg, _ in errs if eg)
    disp = good > 0
    _CTL[sym] = (
        disp,
        "control:%d/%d stored quarters reconcile (%s)"
        % (good, len(errs), "; ".join("%d %s" % (q, n.split(" via")[0]) for q, _, n in errs)),
    )
    return _CTL[sym]


def fy_of(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return y + 1 if m > 3 else y  # Apr-Mar fiscal year, labelled by its END year


def fy_identity(sym, qe, value, fund, inv, pending):
    """GATE F: the fiscal year's four con quarters must sum to the AUDITED con annual."""
    fy = fy_of(qe)
    quarters = [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930, (fy - 1) * 10000 + 1231, fy * 10000 + 331]
    stored = {r[0]: (r[3] if len(r) > 3 else None) for r in fund.get(sym, [])}
    parts, missing = [], []
    for q in quarters:
        if q == qe:
            parts.append(value)
        elif q in pending:
            parts.append(pending[q])
        elif stored.get(q) is not None:
            parts.append(stored[q])
        else:
            missing.append(q)
    if missing:
        return None, "F:n/a missing con quarters {}".format(",".join(str(m) for m in missing))
    link = (inv.get(sym, {}).get("ann") or {}).get("%d0331" % fy)
    if not link:
        return None, "F:n/a no audited con annual page for FY%d" % fy
    try:
        html, meta, rows = fetch(link, sym, fy * 10000 + 331, "ann")
    except Exception as ex:
        return None, f"F:n/a annual fetch {type(ex).__name__}"
    time.sleep(0.6)
    bad = validate_page(html, meta, sym, fy * 10000 + 331, True)
    if bad:
        return None, f"F:n/a annual page invalid ({bad})"
    ann, asrc, _ = owners_of(rows)
    if ann is None:
        return None, f"F:n/a annual owners ({asrc})"
    tot = sum(parts)
    d = abs(tot - ann)
    ok = d <= max(3.0, abs(ann) * 0.03)
    return ok, "F:%s FY%d qtrs=%.2f vs audited annual=%.2f (%.2f, %.2f%%)" % (
        "PASS" if ok else "FAIL",
        fy,
        tot,
        ann,
        d,
        100.0 * d / abs(ann) if ann else 0,
    )


# ---------------------------------------------------------------- calibration


def calibrate(limit):
    """Prove `owners = period - minority - associates` on the SAME template and era.

    Population: cells whose con PAT we ALREADY store and whose archive page the con-revenue pass
    matched through a minority/associates variant. Only SEPARABLE cases are scored -- those where
    the +assoc and -assoc variants are further apart than the anchor tolerance, so the sign is
    actually being tested rather than lost in a near-tie.
    """
    reads = json.load(open(CONREV_READS))
    inv = json.load(open(CONREV_INV))
    fund = json.load(open(DOCS))
    os.makedirs(CACHE, exist_ok=True)
    work = []
    for k, v in sorted(reads.items()):
        if v.get("anchor_via") not in ("period-minority-assoc", "period-minority+assoc"):
            continue
        sym, qe = k.rsplit("|", 1)
        link = (inv.get(sym, {}).get("qtr") or {}).get(qe)
        if link:
            work.append((sym, int(qe), link))
    if limit:
        work = work[:limit]
    print("calibration pages: %d\n" % len(work), flush=True)

    out, sep_ok, sep_bad, tie, other = [], 0, 0, 0, 0
    for sym, qe, link in work:
        row = {r[0]: r for r in fund.get(sym, [])}.get(qe)
        stored = row[3] if row and len(row) > 3 else None
        if stored is None:
            continue
        try:
            html, meta, rows = fetch(link, sym, qe, "cal")
        except Exception:
            other += 1
            continue
        time.sleep(0.6)
        if validate_page(html, meta, sym, qe, True):
            other += 1
            continue
        per, mi = NAR.pick(rows, R_PERIOD), NAR.pick(rows, R_MINORITY)
        asc, own = NAR.pick(rows, R_ASSOC), NAR.pick(rows, R_OWN)
        if per is None or mi is None or asc is None:
            other += 1
            continue
        minus, plus = per - mi - asc, per - mi + asc
        tol = max(STD_ABS, abs(stored) * STD_REL)
        if abs(minus - plus) <= 2 * tol:  # variants indistinguishable -> proves nothing
            tie += 1
            continue
        hit = "minus" if abs(minus - stored) <= tol else ("plus" if abs(plus - stored) <= tol else "neither")
        if hit == "minus":
            sep_ok += 1
        elif hit == "plus":
            sep_bad += 1
        else:
            other += 1
        out.append(
            {
                "key": "%s|%d" % (sym, qe),
                "stored_con": stored,
                "period": per,
                "minority": mi,
                "associates": asc,
                "minus": round(minus, 2),
                "plus": round(plus, 2),
                "owners_row": own,
                "verdict": hit,
                "template": "old(owners-row)" if own is not None else "indas(no-owners-row)",
            }
        )
        print(
            "  %-12s %d  stored=%-11.2f per=%-11.2f mi=%-9.2f asc=%-9.2f  -asc=%-11.2f +asc=%-11.2f  %s  %s"
            % (sym, qe, stored, per, mi, asc, minus, plus, hit, "old" if own is not None else "indas"),
            flush=True,
        )
    json.dump(out, open(CALIB, "w"), indent=1, sort_keys=True)
    tot = sep_ok + sep_bad
    print("\nSEPARABLE cases (sign of `associates` actually tested): %d" % tot)
    print(
        "  period - minority - associates  == stored con : %d  (%.1f%%)" % (sep_ok, 100.0 * sep_ok / tot if tot else 0)
    )
    print("  period - minority + associates  == stored con : %d" % sep_bad)
    print("  near-ties skipped: %d | unusable/other: %d" % (tie, other))
    indas = [r for r in out if r["template"].startswith("indas")]
    print(
        "  of the separable, %d sit on the Ind-AS (no-owners-row) template, %d correct"
        % (len(indas), sum(1 for r in indas if r["verdict"] == "minus"))
    )
    print(f"  -> {os.path.basename(CALIB)}")


# ---------------------------------------------------------------- main pass


CLASSES = {
    "owners": "no-owners-row",
    "eps": "E-recon failed",
    "sprime": "S'-mismatch",
    "basis": "basis-mismatch",
    "blank": "blank-template",
}


def targets(only, classes):
    old = json.load(open(OLD_READS))
    out = []
    for k, v in sorted(old.items()):
        s = v.get("skip") or ""
        cls = next((c for c, needle in CLASSES.items() if needle in s), None)
        if cls not in classes:
            continue
        sym, qe = k.split("|")
        if only and sym not in only:
            continue
        out.append((sym, int(qe), cls, v))
    return out


ADJ = os.path.join(SCRIPTS, "con_pat_sprime_adjudication.json")
REV_REL = 0.02  # a revised quarter, not a different document


def revision_ok(sym, qe):
    """Can a FAILING GATE S' be explained as a later revision of that one quarter?

    Requires the adjudication ledger to show, for this cell: all three sibling quarters of the
    fiscal year reproduced by the archive to the paisa, the disputed quarter off by less than the
    campaign's 3% value tolerance, and the AUDITED annual tiling OUR stored series (so the archive
    is holding the earlier revision rather than the wrong company/period). One cell in the class
    qualifies -- BLISSGVS Jun-2016; GITANJALI/GLOBOFFS/ZEELEARN/CGPOWER are all excluded because
    their sibling quarters do NOT reproduce, and NOIDATOLL because its FY2016 standalone series
    does not tile its own audited annual either way."""
    try:
        adj = json.load(open(ADJ))
    except Exception:
        return None
    r = adj.get("%s|%d" % (sym, qe))
    if not r:
        return None
    if r.get("sibling_quarters_exact") != 3:
        return None
    if not r.get("stored_tiles_annual"):
        return None
    rel = r.get("disputed_rel_miss")
    if rel is None or rel > REV_REL:
        return None
    return (
        "FY%d siblings 3/3 exact, disputed quarter off %.2f%%, stored series tiles the audited "
        "annual (%.2f vs %.2f)" % (r["fy"], rel * 100, r["stored_qtr_sum"], r["audited_std_annual"])
    )


def std_link(sym, qe):
    for row in _list_rows(sym):
        if (row.get("consolidated") or "").strip().lower().startswith("non"):
            if NAR.iso_qe(row.get("toDate") or "") == qe and row.get("resultDetailedDataLink"):
                return row["resultDetailedDataLink"]
    return None


def main():
    args = sys.argv[1:]
    if "--apply" in args:
        return apply_reads()
    if "--calibrate" in args:
        i = args.index("--calibrate")
        n = int(args[i + 1]) if len(args) > i + 1 and args[i + 1].isdigit() else 0
        return calibrate(n)
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    classes = set((args[args.index("--classes") + 1]).split(",")) if "--classes" in args else {"owners", "eps"}
    inv = json.load(open(INV))
    fund = json.load(open(DOCS))
    reads = json.load(open(READS)) if os.path.exists(READS) else {}
    os.makedirs(CACHE, exist_ok=True)

    work = targets(only, classes)
    print("re-attempting %d refusals (classes: %s)\n" % (len(work), ",".join(sorted(classes))), flush=True)
    ok = skip = 0
    deferred = []
    for sym, qe, cls, _old in work:
        key = "%s|%d" % (sym, qe)
        link = (inv.get(sym, {}).get("qtr") or {}).get(str(qe))
        row = {r[0]: r for r in fund.get(sym, [])}.get(qe)
        stored_std = row[1] if row else None
        stored_con = row[3] if row and len(row) > 3 else None
        if stored_con is not None:
            reads[key] = {"skip": "already-filled", "was": cls}
            continue
        if not link:
            reads[key] = {"skip": "no-link-in-inventory", "was": cls}
            skip += 1
            continue
        try:
            html, meta, rows = fetch(link, sym, qe, "c")
        except Exception as ex:
            reads[key] = {"skip": f"fetch:{type(ex).__name__}", "was": cls}
            skip += 1
            print("  SKIP %-12s %d  fetch %s" % (sym, qe, type(ex).__name__), flush=True)
            continue
        time.sleep(0.6)
        bad = validate_page(html, meta, sym, qe, True)
        if bad:
            reads[key] = {"skip": f"page-invalid:{bad}", "was": cls}
            skip += 1
            print("  SKIP %-12s %d  page-invalid %s" % (sym, qe, bad), flush=True)
            continue
        pat, src, parts = owners_of(rows)
        if pat is None:
            reads[key] = {"skip": src, "was": cls, "parts": parts}
            skip += 1
            print("  SKIP %-12s %d  %s" % (sym, qe, src), flush=True)
            continue
        if abs(pat) < 1e-9:
            reads[key] = {"skip": "blank-template(owners 0.00)", "was": cls, "parts": parts}
            skip += 1
            continue

        gates, blocked, passes, needs_fy = [], None, 0, False
        # GATE I -- the page's own owners row against the deduction identity.
        if parts["owners_row"] is not None and parts["minority"] is not None:
            ident = parts["period"] - parts["minority"] - (parts["associates"] or 0.0)
            good = near(ident, parts["owners_row"])
            gates.append(
                "I:{} owners_row={:.2f} identity={:.2f}".format("PASS" if good else "FAIL", parts["owners_row"], ident)
            )
            if good:
                passes += 1
            else:
                blocked = "identity-vs-owners-row mismatch ({:.2f} vs {:.2f})".format(parts["owners_row"], ident)
        # GATE S'
        sl = std_link(sym, qe)
        if stored_std is not None and sl:
            try:
                shtml, smeta, srows = fetch(sl, sym, qe, "s")
                time.sleep(0.6)
                sbad = validate_page(shtml, smeta, sym, qe, False)
                if sbad:
                    gates.append(f"S':unavailable({sbad})")
                else:
                    spat, ssrc, _ = owners_of(srows)
                    if spat is None:
                        gates.append(f"S':unavailable({ssrc})")
                    else:
                        good = near(spat, stored_std)
                        gates.append(
                            "S':{} std_page={:.2f} stored={:.2f}".format("PASS" if good else "FAIL", spat, stored_std)
                        )
                        if good:
                            passes += 1
                        else:
                            rev = revision_ok(sym, qe)
                            if rev:
                                # GATE S'' -- a REVISED FILING, not a wrong document. Everything
                                # GATE S' exists to prove (source, scale, period-mapping, symbol) is
                                # proven by the rest of the fiscal year reproducing our stored
                                # standalone to the paisa; only the disputed quarter moved, by less
                                # than the campaign's own 3% value tolerance, and the AUDITED annual
                                # sides with our stored series -- i.e. the archive holds the earlier
                                # revision of that one quarter. Evidence in
                                # con_pat_sprime_adjudication.json (adjudicate_sprime.py).
                                gates.append(f"S'':REVISION {rev}")
                                passes += 1
                            else:
                                blocked = blocked or (f"S'-mismatch (std page {spat:.2f} vs stored {stored_std:.2f})")
            except Exception as ex:
                gates.append(f"S':unavailable(fetch:{type(ex).__name__})")
        else:
            gates.append("S':unavailable(no-std-link)" if not sl else "S':unavailable(no-stored-std)")
        # GATE E, and -- only if it fails -- the GATE C control that decides whether that failure
        # is evidence about THIS read or just how the filer computes EPS.
        eg, note = eps_gate(pat, rows)
        gates.append("E:{} {}".format({True: "PASS", False: "FAIL", None: "n/a"}[eg], note))
        if eg is True:
            passes += 1
        elif eg is False:
            disp, cnote = eps_control(sym, fund)
            gates.append("C:{} {}".format("E-DISPOSITIVE" if disp else "E-NON-DISPOSITIVE", cnote))
            if disp:
                blocked = blocked or f"E-recon failed ({note})"
            else:
                # The filer's EPS never reconciles even where the answer is known, so it cannot
                # veto. The FY quarter-sum identity has to carry the read instead -- deferred to a
                # second pass, because sibling quarters of the SAME fiscal year are often targets
                # of this very run (TATASTEEL Sep-16 + Dec-16 both sit in FY2017).
                needs_fy = True

        rec = {
            "con": round(pat, 2),
            "src": src,
            "unit": meta.get("unit"),
            "gates": gates,
            "stored_std": stored_std,
            "link": link,
            "was": cls,
            "parts": {k: v for k, v in parts.items() if v is not None},
        }
        if needs_fy and not blocked:
            deferred.append((sym, qe, rec, passes))
            print(
                "  DEFER %-11s %d  con=%-11.2f awaiting FY identity | %s" % (sym, qe, pat, " ; ".join(gates)),
                flush=True,
            )
            continue
        if blocked or passes == 0:
            rec["skip"] = blocked or "no-gate-passed"
            skip += 1
            print("  SKIP %-12s %d  %s | %s" % (sym, qe, rec["skip"], " ; ".join(gates)), flush=True)
        else:
            ok += 1
            print("  OK   %-12s %d  con=%-11.2f (%s) | %s" % (sym, qe, pat, src, " ; ".join(gates)), flush=True)
        reads[key] = rec

    # SECOND PASS -- GATE F for the cells whose EPS gate was ruled non-dispositive. `pending`
    # carries this run's own candidates so co-quarters of one fiscal year can complete each other.
    if deferred:
        print("\nGATE F pass over %d deferred cells" % len(deferred), flush=True)
    pending = {}
    for sym, qe, rec, _ in deferred:
        pending.setdefault(sym, {})[qe] = rec["con"]
    for sym, qe, rec, passes in deferred:
        fok, fnote = fy_identity(sym, qe, rec["con"], fund, inv, pending.get(sym, {}))
        rec["gates"].append(fnote)
        if fok:
            ok += 1
            print(
                "  OK   %-12s %d  con=%-11.2f (%s) | %s" % (sym, qe, rec["con"], rec["src"], " ; ".join(rec["gates"])),
                flush=True,
            )
        else:
            rec["skip"] = f"E-recon failed and the FY identity did not rescue it ({fnote})"
            skip += 1
            print("  SKIP %-12s %d  %s" % (sym, qe, rec["skip"]), flush=True)
        reads["%s|%d" % (sym, qe)] = rec

    json.dump(reads, open(READS, "w"), indent=1, sort_keys=True)
    print("\nlanded %d | skipped %d -> %s" % (ok, skip, os.path.basename(READS)))
    return None


def apply_reads():
    reads = json.load(open(READS))
    good = {k: v for k, v in reads.items() if "con" in v and not v.get("skip")}
    counts = []
    for path in (DOCS, MIRROR):
        d = json.load(open(path))
        n = over = 0
        for k, v in good.items():
            sym, qe = k.split("|")
            qe = int(qe)
            r = {x[0]: x for x in d.get(sym, [])}.get(qe)
            if not r:
                continue
            while len(r) < 5:
                r.append(None)
            if r[3] is not None:  # fill-only, never overwrite
                over += 1
                continue
            r[3] = v["con"]
            if r[4] is None:
                r[4] = r[2]
            n += 1
        json.dump(d, open(path, "w"), separators=(",", ":"))
        counts.append((os.path.basename(path), n, over))
    for name, n, over in counts:
        print("wrote %-28s %d cells (skipped %d already-populated)" % (name, n, over))
    print("(of %d landed reads)" % len(good))


if __name__ == "__main__":
    main()

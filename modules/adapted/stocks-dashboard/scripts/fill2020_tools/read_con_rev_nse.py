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
"""FILL-2020: consolidated REVENUE 2015-2019 for REAL consolidators, from the NSE archive.

The population left after the no-sub identity pass: 1,128 cells / 356 companies whose consolidated
PAT is STORED and DIFFERS from standalone. They genuinely filed consolidated statements, so the
revenue exists -- it was simply never parsed into sf_revop.

THE GATE IS THE STRONGEST ONE THIS CAMPAIGN HAS. Unlike the con-PAT pass (§53a), which had no
stored value on its own basis and had to validate the document through the STANDALONE sibling
(GATE S'), here the con PAT for the exact cell is already in our data:

    the consolidated page's owners-attributable PAT must match our STORED con PAT
    within max(0.05cr, 0.5%)  ->  same company, same quarter, SAME BASIS, same scale
    -> only then is that page's revenue read

A same-basis anchor cannot be satisfied by a standalone page, a wrong quarter, or a wrong scale, so
no further reconstruction is needed. Cells whose page fails the anchor are refused, never coerced.

Carries over every §53b trap the con-PAT reader learned:
  * declared basis must read Consolidated, Period Ended must equal the target quarter, and Symbol
    must be among the era spellings (NSE rewrites archive filenames to the CURRENT symbol);
  * CUMULATIVE pages are year-to-date -- a Q2/Q3/Q4 cumulative row would land 6/9/12 months as a
    quarter, and parse_detail does not surface the field, so it is read from the body;
  * blank-template pages (every P&L row 0.00) are refused outright.
Revenue rows follow the archive's own wording, industrial and banking both (§42: bank filings have
no "revenue from operations" line -- their top line is Interest Earned).

Lands to scripts/con_rev_nse_reads.json for review; --apply merges fill-only into
docs/sf_revop.json + scripts/revop_fundamentals.json (slot 1 only; op/EBIT untouched).

⚠️ Another session writes post-2020 revenue in those same files -- re-verify against fresh origin
before every push and re-apply from the ledger if origin moved.

Run:  python -X utf8 scripts/fill2020_tools/read_con_rev_nse.py [--limit N] [--only SYM,SYM]
      python -X utf8 scripts/fill2020_tools/read_con_rev_nse.py --apply
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

INV = os.path.join(HERE, "_conrev_nse_inventory.json")
TARGETS = os.path.join(HERE, "_conrev_targets.json")
READS = os.path.join(SCRIPTS, "con_rev_nse_reads.json")
CACHE = os.path.join(SCRIPTS, "_nsearch_cache")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")

PAT_ABS, PAT_REL = 0.05, 0.005

R_OWN = re.compile(r"net profit.*after\s+taxe?s?.*minority\s+interest", re.IGNORECASE)
R_PERIOD = re.compile(r"net profit\s*/?\s*\(?\s*loss\s*\)?\s*for the period", re.IGNORECASE)
R_MINORITY = re.compile(r"^minority interest", re.IGNORECASE)
R_ASSOC = re.compile(r"share of profit.*associat", re.IGNORECASE)
# revenue: the archive's own wordings, industrial then banking (§42)
R_REV = (
    re.compile(r"total income from operations", re.IGNORECASE),
    re.compile(r"net sales\s*/\s*income from operations", re.IGNORECASE),
    re.compile(r"^revenue from operations", re.IGNORECASE),
    re.compile(r"net sales\s*/\s*revenue from operations", re.IGNORECASE),
    re.compile(r"income from operations", re.IGNORECASE),
)
R_REV_BANK = (re.compile(r"^interest earned", re.IGNORECASE), re.compile(r"total income", re.IGNORECASE))


def read_con(link, sym, qe):
    path = os.path.join(CACHE, "crev_%s_%d_c.html" % (sym.replace("&", "_"), qe))
    try:
        html = NAR.get_detail(link, sym, path)
    except Exception as ex:
        return None, f"fetch:{type(ex).__name__}"
    meta, rows = NAR.parse_detail(html)
    if (meta.get("Consolidated / Non-Consolidated", "")).strip().lower() != "consolidated":
        return None, "basis=%s" % (meta.get("Consolidated / Non-Consolidated") or "?")
    if NAR.iso_qe(meta.get("Period Ended", "")) != qe:
        return None, "period={}".format(meta.get("Period Ended"))
    if (meta.get("Symbol") or "").upper() not in {a.upper() for a in ([sym, *NAR.aliases(sym)])}:
        return None, "symbol={}".format(meta.get("Symbol"))
    m = re.search(r"Cumulative\s*/\s*Non-?Cumulative\s*\|?\s*(Non-?Cumulative|Cumulative)", html, re.IGNORECASE)
    if m and m.group(1).lower().replace("-", "").startswith("cumulative"):
        return None, "cumulative-page(YTD)"
    own, per, mi = NAR.pick(rows, R_OWN), NAR.pick(rows, R_PERIOD), NAR.pick(rows, R_MINORITY)
    asc = NAR.pick(rows, R_ASSOC)
    # CANDIDATE PATs, not a derived one. Many pages omit the explicit owners row while printing its
    # components, and the archive's sign convention for the associates line is not what it looks
    # like: `period - minority - associates` is what reproduces our stored con (BAJAJ-AUTO 836.74
    # from 789.70 - 0.01 - (-47.05); likewise ALLCARGO, ANANTRAJ, AVANTIFEED), because those rows
    # are printed as deductions leading to the final owners line.
    # We do NOT need to know which convention a given filer used. The anchor below only has to
    # establish that this page is the right company/quarter/basis; whichever legitimate variant
    # reproduces our stored con proves that, and the REVENUE we then read is the same number
    # regardless of which one matched. A wrong page still matches none of them.
    cands = []
    for v, tag in ((own, "owners-row"), (per, "period-row")):
        if v is not None:
            cands.append((v, tag))
    if per is not None and mi is not None:
        cands.append((per - mi, "period-minority"))
        if asc is not None:
            cands.append((per - mi - asc, "period-minority-assoc"))
            cands.append((per - mi + asc, "period-minority+assoc"))
    if not cands:
        return None, "no-pat-row"
    rev = NAR.pick(rows, *R_REV)
    src = "rev-from-ops"
    if rev is None:
        rev = NAR.pick(rows, *R_REV_BANK)
        src = "interest-earned(bank)"
    if rev is None:
        return None, "no-revenue-row"
    if all(abs(v) < 1e-9 for v, _ in cands) and abs(rev) < 1e-9:
        return None, "blank-template(all-zero)"
    return (cands, rev, src), "ok"


def main():
    args = sys.argv[1:]
    if "--apply" in args:
        return apply_reads()
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    if not os.path.exists(INV):
        print(
            "no inventory yet -- run nse_con_discover.py --targets _conrev_targets.json "
            "--out _conrev_nse_inventory.json first"
        )
        return None
    inv = json.load(open(INV))
    fund = json.load(open(FUND))
    revop_std = json.load(open(REVOP_DOCS))
    reads = json.load(open(READS)) if os.path.exists(READS) else {}
    os.makedirs(CACHE, exist_ok=True)

    work = []
    for sym, rec in sorted(inv.items()):
        if only and sym not in only:
            continue
        for qe_s, link in sorted((rec.get("qtr") or {}).items()):
            if f"{sym}|{qe_s}" in reads:
                continue
            work.append((sym, int(qe_s), link))
    if limit:
        work = work[:limit]
    print("con-revenue reads to attempt: %d" % len(work), flush=True)

    ok = skip = 0
    for i, (sym, qe, link) in enumerate(work):
        row = {r[0]: r for r in fund.get(sym, [])}.get(qe)
        stored_con = row[3] if row and len(row) > 3 else None
        if stored_con is None:
            reads["%s|%d" % (sym, qe)] = {"skip": "no-stored-con-pat-anchor"}
            skip += 1
            continue
        got, why = read_con(link, sym, qe)
        time.sleep(0.7)
        if got is None:
            reads["%s|%d" % (sym, qe)] = {"skip": why}
            skip += 1
            print("  SKIP %-12s %d  %s" % (sym, qe, why), flush=True)
            continue
        cands, rev, src = got
        tol = max(PAT_ABS, abs(stored_con) * PAT_REL)
        best = min(cands, key=lambda c: abs(c[0] - stored_con))
        d = abs(best[0] - stored_con)
        if d > tol:
            reads["%s|%d" % (sym, qe)] = {
                "skip": f"con-pat-anchor off {d:.2f} (closest {best[1]}={best[0]:.2f} vs stored {stored_con:.2f})"
            }
            skip += 1
            print(
                "  SKIP %-12s %d  anchor off %.2f (closest %s %.2f vs stored %.2f)"
                % (sym, qe, d, best[1], best[0], stored_con),
                flush=True,
            )
            continue
        pat = best[0]
        if rev < 0:
            reads["%s|%d" % (sym, qe)] = {"skip": "negative-revenue"}
            skip += 1
            continue
        # CON-BELOW-STD REVIEW GUARD. Consolidated revenue normally >= standalone (subsidiaries add
        # to it), and 193/196 landed cells satisfy that. The exceptions are ambiguous in a way this
        # pass cannot settle: BAJAJHLDNG 121.65 vs std 583.96 is probably genuine (an investment
        # holding company equity-accounts its associates and eliminates intra-group dividends, so
        # consolidated revenue really is smaller), but ACC 2917.23 vs 3286.08 more likely reflects a
        # DEFINITION mismatch -- these pages print "Net sales/income from operations (Net of excise
        # duty)" and excise is material for cement, so a net-of-excise con landing beside a
        # gross-of-excise std would show consolidated BELOW standalone on the site. Both look
        # identical from here, so refuse and flag rather than guess.
        std_rev = (revop_std.get(sym, {}).get(str(qe)) or [None])[0]
        if std_rev and rev < 0.9 * std_rev:
            reads["%s|%d" % (sym, qe)] = {
                "skip": f"con-below-std REVIEW (con {rev:.2f} vs std {std_rev:.2f})",
                "revC_candidate": round(rev, 2),
            }
            skip += 1
            print("  SKIP %-12s %d  con-below-std review (con %.2f vs std %.2f)" % (sym, qe, rev, std_rev), flush=True)
            continue
        reads["%s|%d" % (sym, qe)] = {
            "revC": round(rev, 2),
            "anchor_pat": stored_con,
            "page_pat": round(pat, 2),
            "anchor_via": best[1],
            "src": src,
            "link": link,
        }
        ok += 1
        print(
            "  OK   %-12s %d  rev=%-12.2f (con-PAT anchor %.2f cr; %s)" % (sym, qe, rev, d, best[1] + "/" + src),
            flush=True,
        )
        if (i + 1) % 10 == 0:
            json.dump(reads, open(READS, "w"), indent=0, sort_keys=True)
    json.dump(reads, open(READS, "w"), indent=0, sort_keys=True)
    print("\nlanded %d | skipped %d -> %s" % (ok, skip, os.path.basename(READS)))
    return None


def apply_reads():
    reads = json.load(open(READS))
    good = {k: v for k, v in reads.items() if "revC" in v and not v.get("skip")}
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for k, v in good.items():
            sym, qe = k.rsplit("|", 1)
            row = d.get(sym, {}).get(qe)
            if not row:
                continue
            while len(row) < 9:
                row.append(None)
            if row[1] is not None:
                continue
            row[1] = v["revC"]
            n += 1
            d[sym][qe] = row
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("wrote %-30s %d cells" % (os.path.basename(path), n))


if __name__ == "__main__":
    main()

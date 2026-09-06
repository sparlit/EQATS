# -*- coding: utf-8 -*-
"""FILL-2019 rev track: mine COMPARATIVE CONTEXTS of later same-basis XBRL filings.

WHY. For the 2019 quarters (esp. Mar-2019, the last pre-compulsory-consolidation quarter, §51a)
the NSE index often has NO con row, or a con row whose XBRL 404s (the Mar-2019 `_WEB_2.xml`
class — 13 measured dead 2026-08-10). But the company's NEXT filings carry the target quarter as
a comparative column, and the 2018-2021 INDAS/BANKING XBRLs tag those comparatives in their own
contexts WITH DECLARED PERIOD DATES. §45's rule: declared context dates beat every inference —
never assign by list-row toDate, never by context-id convention (FourD means different things to
different filers). So this reader:

  1. source candidates = the SAME company's rows in scripts/_nselist with a fetchable XBRL,
     declared basis == the target basis, toDate within (qe, qe+1y] — nearest filing first;
  2. requires the source file's OneD NatureOfReport to confirm the basis (per-basis files);
  3. enumerates EVERY context in the file whose DECLARED period == the target quarter
     (endDate == qe AND 80..100 days long — kills YTD/FY columns by construction);
  4. reads rev/op/ebit/pat via build_revop.metrics_for (same branches the nightly uses:
     industrial / bank / NBFC / insurer);
  5. gates before writing (mirrors nse_xbrl_rev.py G1-G5):
       ANCHOR   that context's PAT (owners preferred, total fallback) == stored sf_fundamentals
                PAT for (sym, qe, basis) within max(2cr, 3%);
       BAND     rev > 0 and within [0.2x, 5x] of the same-basis neighbour median
                (0.5-2x flagged for review) — never banded against the other basis;
       FILL-ONLY never over a non-null cell.

Ledgers: scripts/xbrl_comparative_rev_fills2019.json (tracked, per-cell provenance: source XBRL,
context id, declared period, anchor chain), scripts/_xbrl_comp_rev_skips.json (scratch refusals).

Run:  python -X utf8 scripts/fill2020_tools/xbrl_comparative_rev.py [--only SYM,SYM] [--apply]
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import build_fundamentals as BF          # noqa: E402
import build_revop as BR                 # noqa: E402

LIST_CACHE = os.path.join(SCRIPTS, "_nselist")
XBRL_CACHE = os.path.join(SCRIPTS, "_xbrl_cache")
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
FILLS = os.path.join(SCRIPTS, "xbrl_comparative_rev_fills2019.json")
SKIPS = os.path.join(SCRIPTS, "_xbrl_comp_rev_skips.json")

H = {"User-Agent": BF.UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
MON = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
SLOT = {"std": {"rev": 0, "op": 2, "ebit": 7}, "con": {"rev": 1, "op": 3, "ebit": 8}}
BAND_LO, BAND_HI = 0.2, 5.0
REVIEW_LO, REVIEW_HI = 0.5, 2.0
NEIGHBOURS = 8

RE_CTX_BLOCK = re.compile(
    r'<xbrli:context id="([^"]+)"[^>]*>.*?<xbrli:startDate>(\d{4}-\d{2}-\d{2})</xbrli:startDate>'
    r'\s*<xbrli:endDate>(\d{4}-\d{2}-\d{2})</xbrli:endDate>', re.DOTALL)
RE_DATE_ANY = re.compile(
    r'DateOf(Start|End)OfReportingPeriod contextRef="([^"]+)"[^>]*>(\d{4}-\d{2}-\d{2})')


def iso_qe(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    if not m or m.group(2).title() not in MON:
        return None
    return int(m.group(3)) * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))


def qe_iso(qe):
    return "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)


def arm(cid):
    """Extend build_revop's precompiled OneD/FourD regex tables to an arbitrary context id."""
    if cid in BR.RE_CTX:
        return
    esc = re.escape(cid)
    BR.RE_CTX[cid] = re.compile(
        r'<xbrli:context id="' + esc + r'">.*?<xbrli:startDate>(\d{4}-\d{2}-\d{2})</xbrli:startDate>'
        r'\s*<xbrli:endDate>(\d{4}-\d{2}-\d{2})</xbrli:endDate>', re.DOTALL)
    BR.RE_DATE[cid] = {b: re.compile(
        r'DateOf' + b + r'OfReportingPeriod contextRef="' + esc + r'"[^>]*>(\d{4}-\d{2}-\d{2})')
        for b in ("Start", "End")}
    for t in BR.TAGS:
        BR.RE_TAG[t][cid] = re.compile(
            r'<in-(?:bse-fin|capmkt):' + t + r' contextRef="' + esc + r'"[^>]*>([-0-9.eE+]+)<')
    stem = cid[:-1] if cid.endswith("D") else cid
    BR.RE_ORFO_CID[cid] = re.compile(r'^' + re.escape(stem) + r'Revenue\d+D$')


def contexts_for_period(xml, start_iso, end_iso):
    """Every context id whose DECLARED period is exactly [start_iso..end_iso]."""
    out = []
    for cid, s, e in RE_CTX_BLOCK.findall(xml):
        if s == start_iso and e == end_iso:
            out.append(cid)
    dates = {}
    for which, cid, d in RE_DATE_ANY.findall(xml):
        dates.setdefault(cid, {})[which] = d
    for cid, d in dates.items():
        if d.get("Start") == start_iso and d.get("End") == end_iso and cid not in out:
            out.append(cid)
    return out


def quarter_start(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return "%04d-%02d-01" % (y, m - 2)


def fetch_xbrl(url, jar):
    fname = re.sub(r"[^A-Za-z0-9]", "_", url.rsplit("/", 1)[-1])
    path = os.path.join(XBRL_CACHE, fname)
    if os.path.exists(path) and os.path.getsize(path) > 500:
        return path, fname
    data = BF._get(url, headers=H, jar=jar)
    if isinstance(data, str):
        data = data.encode("utf8", "replace")
    if not data or len(data) < 500:
        raise RuntimeError("short-body-%d" % len(data or b""))
    os.makedirs(XBRL_CACHE, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path, fname


def neighbour_median(revop, sym, qe, basis):
    slot = SLOT[basis]["rev"]
    have = [(abs(int(q) - qe), row[slot]) for q, row in (revop.get(sym) or {}).items()
            if row[slot] is not None and int(q) != qe and row[slot] > 0]
    if not have:
        return None
    vals = sorted(v for _, v in sorted(have)[:NEIGHBOURS])
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def declared_nat(xml):
    """The filing's own OneD NatureOfReport ('consolidated'/'non-consolidated'/None)."""
    m = re.search(r'NatureOfReportStandaloneConsolidated contextRef="OneD"[^>]*>([^<]+)<', xml)
    return m.group(1).strip().lower() if m else None


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    apply_it = "--apply" in argv

    targets = json.load(open(TARGETS))
    revop = json.load(open(REVOP_DOCS))
    ledger = json.load(open(REVOP_LEDGER))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    jar = BF.nse_jar()

    syms = sorted(targets)
    if only:
        syms = [s for s in syms if s in only]

    nread = nskip = 0
    for si, sym in enumerate(syms, 1):
        lp = os.path.join(LIST_CACHE, re.sub(r"[^A-Z0-9]", "_", sym.upper()) + ".json")
        if not os.path.exists(lp):
            continue
        rows = json.load(open(lp))
        want = [("std", q) for q in targets[sym]["revS"]] + [("con", q) for q in targets[sym]["revC"]]
        for basis, qe in want:
            key = "%s|%d|%s" % (sym, qe, basis)
            if key in fills:
                continue
            row = (revop.get(sym) or {}).get(str(qe))
            if row is not None and row[SLOT[basis]["rev"]] is not None:
                continue                                   # already closed by an earlier rung
            stored_pat = (fmap.get(sym, {}).get(qe) or [None] * 4)[1 if basis == "std" else 3]
            if stored_pat is None:
                skips[key] = "comp:no-stored-pat-anchor"
                nskip += 1
                continue
            nat_want = "consolidated" if basis == "con" else "non-consolidated"
            # source candidates: later same-basis filings within a year, nearest first
            cands = []
            for r in rows:
                sqe = iso_qe(r.get("toDate"))
                x = r.get("xbrl") or ""
                if (not sqe or sqe <= qe or sqe > qe + 10000 or not x
                        or x.rstrip("/").endswith("/-")):
                    continue
                b = "con" if r.get("consolidated") == "Consolidated" else "std"
                if b != basis:
                    continue
                cands.append((sqe, r))
            cands.sort(key=lambda t: t[0])
            if not cands:
                skips[key] = "comp:no-later-same-basis-xbrl"
                nskip += 1
                continue
            start_iso, end_iso = quarter_start(qe), qe_iso(qe)
            got, why = None, "comp:no-context-with-declared-period"
            for sqe, r in cands[:5]:
                try:
                    path, fname = fetch_xbrl(r["xbrl"], jar)
                except Exception:
                    why = "comp:fetch-error"
                    jar = BF.nse_jar()
                    continue
                try:
                    xml = open(path, encoding="utf8", errors="replace").read()
                except Exception:
                    why = "comp:read-error"
                    continue
                nat = declared_nat(xml)
                if nat and nat != nat_want:
                    why = "comp:source-basis=%s" % nat
                    continue
                cids = contexts_for_period(xml, start_iso, end_iso)
                if not cids:
                    continue
                for cid in cids:
                    arm(cid)
                    rev, op, ebit, pat, owners = BR.metrics_for(xml, cid)
                    anchor = tag = None
                    for v, t in ((owners, "owners"), (pat, "pat")):
                        if v is not None and abs(v - stored_pat) <= max(2.0, 0.03 * max(abs(v), abs(stored_pat))):
                            anchor, tag = v, t
                            break
                    if anchor is None:
                        why = "comp:pat-anchor %s/%s vs stored %s (ctx %s of %s)" % (
                            owners, pat, stored_pat, cid, fname)
                        continue
                    if rev is None:
                        why = "comp:no-rev-tag (ctx %s of %s)" % (cid, fname)
                        continue
                    fin = 1 if ("InterestEarned" in xml or "NetPremiumIncome" in xml
                                or "PremiumEarned" in xml) else 0
                    got = {"rev": round(rev, 2),
                           "op": None if op is None else round(op, 2),
                           "ebit": None if ebit is None else round(ebit, 2),
                           "basis": basis, "anchor": round(anchor, 2), "anchor_tag": tag,
                           "stored_pat": stored_pat, "fin": fin,
                           "src": r["xbrl"], "src_toDate": r.get("toDate"),
                           "ctx": cid, "declared_period": "%s..%s" % (start_iso, end_iso),
                           "filed": r.get("filingDate")}
                    break
                if got:
                    break
                time.sleep(0.2)
            if not got:
                skips[key] = why
                nskip += 1
                continue
            if got["rev"] <= 0:
                skips[key] = "comp:zero-or-negative-rev %.2f" % got["rev"]
                nskip += 1
                continue
            med = neighbour_median(revop, sym, qe, basis)
            if med is None:
                got["review"] = "no same-basis neighbour to sanity-check against"
            else:
                ratio = got["rev"] / med
                if not (BAND_LO <= ratio <= BAND_HI):
                    skips[key] = "comp:neighbour-band %.2f (%.2f vs %s-median %.2f)" % (
                        ratio, got["rev"], basis, med)
                    nskip += 1
                    continue
                got["neighbour_ratio"] = round(ratio, 3)
                if not (REVIEW_LO <= ratio <= REVIEW_HI):
                    got["review"] = "%.2fx the %s-basis neighbour median (%.2f vs %.2f)" % (
                        ratio, basis, got["rev"], med)
            fills[key] = got
            nread += 1
            print("%-13s %d %-3s rev %-12.2f op %-11s anchor %.2f (%s) ctx %s <- %s%s" % (
                sym, qe, basis, got["rev"], got["op"], got["anchor"], tag, got["ctx"],
                got["src_toDate"],
                "  <-- REVIEW " + got["review"] if got.get("review") else ""), flush=True)
        if si % 20 == 0:
            print("  [%d/%d] read %d, skipped %d" % (si, len(syms), nread, nskip), flush=True)
            json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            jar = BF.nse_jar()

    json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    print("\nREAD %d cells this run (%d ledgered total), skipped %d" % (nread, len(fills), nskip))

    if not apply_it:
        print("(dry run — ledgers written, data files untouched. Re-run with --apply)")
        return

    applied = 0
    for key, v in sorted(fills.items()):
        sym, qe_s, basis = key.split("|")
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None:
            continue
        for field in ("rev", "op", "ebit"):
            idx_slot = SLOT[basis].get(field)
            if idx_slot is None or v.get(field) is None:
                continue
            if row[idx_slot] is not None:
                continue
            row[idx_slot] = v[field]
            applied += 1
            lrow = ledger.setdefault(sym, {}).get(qe_s)
            if lrow is None:
                ledger[sym][qe_s] = list(row)
            elif lrow[idx_slot] is None:
                lrow[idx_slot] = v[field]
        if v.get("fin") == 1 and row[6] is None:
            row[6] = 1
    json.dump(revop, open(REVOP_DOCS, "w"), separators=(",", ":"))
    json.dump(ledger, open(REVOP_LEDGER, "w"), separators=(",", ":"))
    print("APPLIED %d cell-values to sf_revop.json + revop_fundamentals.json" % applied)


if __name__ == "__main__":
    main()

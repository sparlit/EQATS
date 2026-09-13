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
"""FILL-2020 rev track: fill empty rev/op cells from the XBRL NSE still serves for that quarter.

WHY THIS EXISTS. sf_revop is built by re-parsing scripts/_xbrl_cache. A cell is empty when the
cache never held that filing -- NSE's daily list was missed, the symbol traded under another name
that day, or the filing landed late. But NSE's per-company filing INDEX
(`corporates-financial-results?symbol=X&period=Quarterly`) still lists it, with the `xbrl` URL,
back to ~2018. So the gap is a FETCH gap, not a document gap, and the fix needs no PDF at all:
download that XBRL, parse it with build_revop's own parser, anchor, write.

This is strictly better than the PDF route for any quarter it covers: the numbers are tagged, the
scale is explicit, banks/NBFCs/insurers have first-class branches in metrics_for(), and the file
is the same artifact the nightly rebuild would have used, so a later full rebuild reproduces it.

GATES (a cell is written only if ALL hold -- otherwise it is skipped WITH a reason):
  G1  the list row's declared basis == the basis we are filling (Consolidated / Non-Consolidated),
      and the parsed OneD/FourD context confirms it (parse_file assigns by NatureOfReport tag).
  G2  the parsed quarter-end == the target quarter (never trust the list row's toDate alone --
      NSE double-indexes one file under two quarters, runbook §45).
  G3  PAT ANCHOR: the filing's PAT for that basis == our stored sf_fundamentals PAT within
      max(2cr, 3%). For con we prefer the owners-attributable tag (our stored basis) and accept
      the total-PAT tag as a fallback, since the tags get swapped by some filers (§ xbrl-attr-tag-swap).
  G4  NEIGHBOUR-BAND: the value must sit within [0.2x, 5x] of the median revenue this company
      already stores ON THE SAME BASIS in the eight nearest quarters, and must be > 0.
      ⚠️ Do NOT gate this against the OTHER basis' stored twin (the first version of this tool did,
      and it was wrong twice over):
        * con/std ratios are legitimately enormous for holding structures — TMPV con 79,611 vs std
          14,851 (JLR sits in the consolidation, 5.4x), GMRAIRPORT con 1,588 vs std 21.9 (72x),
          M&M 2.2x. A twin band tight enough to be useful rejects all of them.
        * the stored twin is sometimes itself the junk cell (ETERNAL Mar-2022 stores con rev 1.21
          against a true standalone 1,014.80), so gating against it rejects the GOOD read.
      The company's own recent revenue on the same basis has neither problem. What this guards
      against is a scale/row blunder — the 3MINDIA class (con 1.23 against std 1228) — which is
      off by orders of magnitude and fails the neighbour band just as loudly.
      Anything outside [0.5x, 2x] of the neighbour median is still PRINTED for eyeball review.
      Cells with no same-basis neighbour at all are accepted on the PAT anchor alone and flagged.
  G5  fill-only: never overwrites a non-null cell.

Ledgers (tracked): scripts/nse_xbrl_rev_fills.json = per-cell provenance (XBRL URL + anchor used),
scripts/_nse_xbrl_rev_skips.json = per-cell refusal reason (gitignored scratch, kept for re-runs).
XBRL bodies cache under scripts/_xbrl_cache/ using build_fundamentals' own naming, so a later
`build_revop.py --fresh` re-derives these very cells from the same bytes.

Run:  python -X utf8 scripts/fill2020_tools/nse_xbrl_rev.py [--only SYM,SYM] [--limit N] [--apply]
      (default = DRY RUN: fetches + parses + gates, writes only the ledgers, not the data files)
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

import build_fundamentals as BF  # noqa: E402
import build_revop as BR  # noqa: E402

LIST_CACHE = os.path.join(SCRIPTS, "_nselist")
XBRL_CACHE = os.path.join(SCRIPTS, "_xbrl_cache")
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
FILLS = os.path.join(SCRIPTS, "nse_xbrl_rev_fills.json")
SKIPS = os.path.join(SCRIPTS, "_nse_xbrl_rev_skips.json")

H = {"User-Agent": BF.UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}
# sf_revop row: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
SLOT = {"std": {"rev": 0, "op": 2, "ebit": 7}, "con": {"rev": 1, "op": 3, "ebit": 8}}
BAND_LO, BAND_HI = 0.2, 5.0  # hard reject outside this (vs same-basis neighbour median)
REVIEW_LO, REVIEW_HI = 0.5, 2.0  # inside the band but unusual -> print for review
NEIGHBOURS = 8  # quarters either side used to build the median


def neighbour_median(revop, sym, qe, basis):
    """Median stored revenue for this company on THIS basis, from the nearest quarters."""
    slot = SLOT[basis]["rev"]
    have = [
        (abs(int(q) - qe), row[slot])
        for q, row in (revop.get(sym) or {}).items()
        if row[slot] is not None and int(q) != qe and row[slot] > 0
    ]
    if not have:
        return None
    vals = sorted(v for _, v in sorted(have)[:NEIGHBOURS])
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def iso_qe(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    if not m or m.group(2).title() not in MON:
        return None
    return int(m.group(3)) * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))


def filing_key(r):
    """Sortable filing timestamp so the LATEST revision of a quarter wins (same rule as build_revop)."""
    m = re.search(r"(\d{2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}):(\d{2})", r.get("filingDate") or "")
    if m and m.group(2).title() in MON:
        return "%s%02d%s%s%s" % (m.group(3), MON[m.group(2).title()], m.group(1), m.group(4), m.group(5))
    return "0"


def fetch_xbrl(url, jar):
    """Cache the XBRL under build_fundamentals' own cache name and return (path, filename)."""
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


def anchored(parsed_basis, stored):
    """(value_used, which_tag) if the filing's PAT matches the stored PAT, else (None, None)."""
    if stored is None or parsed_basis is None:
        return None, None
    for tag in ("owners", "pat"):
        v = parsed_basis.get(tag)
        if v is None:
            continue
        if abs(v - stored) <= max(2.0, 0.03 * max(abs(v), abs(stored))):
            return v, tag
    return None, None


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
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
    if limit:
        syms = syms[:limit]

    nread = nskip = 0
    for si, sym in enumerate(syms, 1):
        lp = os.path.join(LIST_CACHE, re.sub(r"[^A-Z0-9]", "_", sym.upper()) + ".json")
        if not os.path.exists(lp):
            skips[f"{sym}|list"] = "no-cached-nse-list"
            continue
        rows = json.load(open(lp))
        idx = {}
        placeholders = 0
        for r in rows:
            qe = iso_qe(r.get("toDate"))
            if not qe or not r.get("xbrl"):
                continue
            # NSE lists some filings with the literal placeholder ".../corporate/xbrl/-" (ACC
            # Dec-2021 and 36 others): the row is real, the XBRL was never published. Treat it as
            # absent so the skip reason is honest instead of a permanent 404 retry.
            if r["xbrl"].rstrip("/").endswith("/-"):
                placeholders += 1
                continue
            b = "con" if r.get("consolidated") == "Consolidated" else "std"
            idx.setdefault((qe, b), []).append(r)
        want = [("std", q) for q in targets[sym]["revS"]] + [("con", q) for q in targets[sym]["revC"]]
        for basis, qe in want:
            key = "%s|%d|%s" % (sym, qe, basis)
            if key in fills:
                continue
            cands = sorted(idx.get((qe, basis), []), key=filing_key, reverse=True)
            if not cands:
                skips[key] = (
                    "nse-xbrl-placeholder (row listed, XBRL never published)" if placeholders else "no-nse-xbrl-row"
                )
                nskip += 1
                continue
            got = None
            for r in cands[:3]:  # latest revision first
                path = None
                for _attempt in (1, 2):
                    try:
                        path, fname = fetch_xbrl(r["xbrl"], jar)
                        break
                    except Exception as e:
                        skips[key] = f"fetch-{type(e).__name__}"
                        time.sleep(1.0)
                        jar = BF.nse_jar()  # a stale cookie jar reads as an HTTPError
                if path is None:
                    continue
                try:
                    parsed = BR.parse_file(path, fname)
                except Exception as e:
                    skips[key] = f"parse-{type(e).__name__}"
                    continue
                if not parsed:
                    skips[key] = "parse-none"
                    continue
                if parsed["qe"] != qe:  # G2 — never trust the list row's quarter alone
                    skips[key] = "qe-mismatch %d" % parsed["qe"]
                    continue
                side = parsed.get(basis)  # G1 — basis per the filing's own NatureOfReport
                if not side:
                    skips[key] = f"no-{basis}-context"
                    continue
                stored_pat = (fmap.get(sym, {}).get(qe) or [None, None, None, None])[1 if basis == "std" else 3]
                hit, tag = anchored(side, stored_pat)  # G3
                if hit is None:
                    skips[key] = "pat-anchor {}/{} vs stored {}".format(side.get("owners"), side.get("pat"), stored_pat)
                    continue
                if side.get("rev") is None:
                    skips[key] = "no-rev-tag"
                    continue
                got = {
                    "rev": round(side["rev"], 2),
                    "op": None if side.get("op") is None else round(side["op"], 2),
                    "ebit": None if side.get("ebit") is None else round(side["ebit"], 2),
                    "basis": basis,
                    "anchor": round(hit, 2),
                    "anchor_tag": tag,
                    "stored_pat": stored_pat,
                    "fin": parsed.get("fin", 0),
                    "src": r["xbrl"],
                    "filed": r.get("filingDate"),
                }
                break
            if not got:
                nskip += 1
                continue
            # G4 — neighbour band (see the module docstring for why NOT the twin)
            if got["rev"] <= 0:
                skips[key] = "zero-rev ({:.2f}) — placeholder row, not a result".format(got["rev"])
                nskip += 1
                continue
            med = neighbour_median(revop, sym, qe, basis)
            if med is None:
                got["review"] = "no same-basis neighbour to sanity-check against"
            else:
                ratio = got["rev"] / med
                if not (BAND_LO <= ratio <= BAND_HI):
                    skips[key] = "neighbour-band {:.2f} ({:.2f} vs {}-median {:.2f})".format(
                        ratio, got["rev"], basis, med
                    )
                    nskip += 1
                    continue
                got["neighbour_ratio"] = round(ratio, 3)
                if not (REVIEW_LO <= ratio <= REVIEW_HI):
                    got["review"] = "{:.2f} x the {}-basis neighbour median ({:.2f} vs {:.2f})".format(
                        ratio, basis, got["rev"], med
                    )
            fills[key] = got
            nread += 1
            print(
                "%-13s %d %-3s rev %-12.2f op %-11s anchor %.2f (%s)%s"
                % (
                    sym,
                    qe,
                    basis,
                    got["rev"],
                    got["op"],
                    got["anchor"],
                    tag,
                    "  <-- REVIEW " + got["review"] if got.get("review") else "",
                ),
                flush=True,
            )
            time.sleep(0.25)
        if si % 15 == 0:
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
            if row[idx_slot] is not None:  # G5 fill-only
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

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
"""Pull rev/op/PAT for PRE-2018 quarters from NSE's ARCHIVED financial-results HTML.

Why this exists (and why the earlier "2015-17 is unreachable" verdict was WRONG):
BSE serves no attachment before ~2019 and the local _xbrl_cache floors at 2018, so every
PDF/OCR route dead-ends. But sf_fundamentals HAS 2015-16 PAT — and that PAT came from
somewhere. It came from NSE: `corporates-financial-results?symbol=X&period=Quarterly`
returns filings back to ~2005, and while pre-2018 rows carry NO xbrl link, they DO carry
`resultDetailedDataLink` -> https://nsearchives.nseindia.com/archives/financial_results/
financial_res_<SYM>_<id>.html — the complete filed P&L as a label/value table.

That page is a better source than the PDFs it replaces:
  * the scale is DECLARED ("Amount(Rs. in lakhs)") instead of inferred,
  * "Banking"/"Non Banking" is DECLARED, so bank vs industrial format needs no guessing,
  * operating profit is a printed line, not a reconstruction from expense components,
  * "Net Profit/(Loss) after taxes, minority interest and share of profit of associates"
    is exactly the owners-attributable convention this dataset uses.

Anchor discipline is unchanged: the page's PAT must match the stored sf_fundamentals PAT
for that (sym, qe, basis) or the cell is SKIPPED. A misparse fails the anchor instead of
corrupting data.

Output: scripts/_nsearch_reads.json in _b3_reads shape (applied by _apply_reads.py).
Caches list+detail under scripts/_nsearch_cache/ so re-runs are nearly free.

Run: python -X utf8 scripts/_nse_archive_revop.py [--gaps FILE] [--only SYM,SYM]
     [--shard I/N --out-suffix _sN] [--limit N]
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import contextlib

import build_fundamentals as BF

CACHE = os.path.join(HERE, "_nsearch_cache")
os.makedirs(CACHE, exist_ok=True)
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
OUT = os.path.join(HERE, "_nsearch_reads.json")
SKIPS = os.path.join(HERE, "_nsearch_skips.json")

H = {"User-Agent": BF.UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}
NUM = re.compile(r"^-?[\d,]+\.?\d*$")

# rev: the printed top line. Banking filings have no "income from operations" row at all.
R_REV_IND = re.compile(r"total income from operations", re.IGNORECASE)
R_REV_IND2 = re.compile(r"net sales\s*/\s*income from operations", re.IGNORECASE)
# Ind-AS-era pages (~2016+) label the line plainly "Revenue from operations" — neither pattern
# above matches it, so those filings read as "no-rev-row" even when the anchor passed.
R_REV_IND3 = re.compile(
    r"^revenue from operations?\b|^income from operations?$"
    r"|^total revenue from operations?",
    re.IGNORECASE,
)
R_REV_BANK = re.compile(r"^interest earned", re.IGNORECASE)
# Two more operating-revenue spellings found 2026-08-07 on pages whose PAT anchor PASSED (so the
# page is definitely the right filing) but which still reported "no-rev-row":
#   "Net Income from sales / services"  -- unambiguously the operating revenue line
R_REV_IND5 = re.compile(r"^net income from sales\s*/?\s*services?", re.IGNORECASE)
#   bare "Total Income" -- LAST RESORT ONLY, and deliberately kept separate from the patterns
# above rather than folded in. For a BANK/NBFC Total Income IS the top line, but for an
# industrial it is sales PLUS other income, so preferring it over a real sales row would
# silently overstate revenue. It is therefore tried only after every other pattern has failed,
# which matches the campaign's own rule: "for banks/NBFCs use Total Income; if ONLY Total
# Income is shown, use that".
R_REV_TOTINC = re.compile(r"^total income$", re.IGNORECASE)
# op: printed directly — no reconstruction from expense components needed
R_OP_IND = re.compile(r"profit\s*/?\s*\(?loss\)?\s*from operations before other income", re.IGNORECASE)
R_OP_BANK = re.compile(r"operating profit before provisions", re.IGNORECASE)
# PAT: prefer the owners-attributable line (post minority interest + associates)
# "after taxES, minority interest" — the archive's actual wording. The old pattern demanded
# "after tax" immediately followed by anything then "minority interest", which the plural broke,
# so pick() returned None and 128 cells failed as "pat-anchor None" with the number on the page.
R_PAT_OWN = re.compile(r"net profit.*after\s+taxe?s?.*minority\s+interest", re.IGNORECASE)
R_PAT_ANY = re.compile(
    r"net profit\s*/?\s*\(?loss\)?\s*for the period"
    r"|net profit.*from ordinary activities after tax",
    re.IGNORECASE,
)
# Same template, sign-notation variants the two patterns above miss:
#   "Net Sales/Income from Operation"          <- SINGULAR, R_REV_IND2 demands "operations"
#   "Net Profit (+) / Loss (-) for the period" <- the (+)/(-) markers sit between the words
#                                                 R_PAT_ANY expects to be adjacent
# Both are tried STRICTLY LAST (separate pick() calls, never folded into the alternations
# above) so every currently-matching page keeps the exact row it matches today -- widening an
# existing alternation could make it match an EARLIER row and silently change landed values.
R_REV_SIGNED = re.compile(r"net sales\s*/\s*income from operations?\b", re.IGNORECASE)
R_PAT_CONNET = re.compile(r"^consolidated net profit.*for the period", re.IGNORECASE)
R_PAT_SIGNED = re.compile(
    r"net profit\s*\([+-]\)\s*/?\s*\(?loss\)?\s*\([+-]\)?\s*for the period"
    r"|net profit\s*\([+-]\)\s*/\s*loss",
    re.IGNORECASE,
)


def aliases(sym):
    """Era symbols for `sym` (transitive), oldest last. NSE keys its archive by the symbol that
    traded THEN, so GMRAIRPORT's 2018 filings live under GMRINFRA, SHRIRAMFIN's under SRTRANSFIN —
    929 of the 1,039 residual cells were 'no row for quarter' purely because we asked under the
    current name. Sources: _rename_map.json (era->current) + symchg.csv (old,new)."""
    edges = {}  # new -> set(old)
    try:
        for old, new in json.load(open(os.path.join(HERE, "_rename_map.json"))).items():
            edges.setdefault(new.upper(), set()).add(old.upper())
    except Exception:
        pass
    try:
        import csv as _csv

        for row in _csv.reader(open(os.path.join(HERE, "symchg.csv"), encoding="utf8", errors="replace")):
            if len(row) >= 3 and row[1].strip() and row[2].strip():
                edges.setdefault(row[2].strip().upper(), set()).add(row[1].strip().upper())
    except Exception:
        pass
    out, queue, seen = [], [sym.upper()], {sym.upper()}
    while queue:
        for old in sorted(edges.get(queue.pop(0), ())):
            if old not in seen:
                seen.add(old)
                out.append(old)
                queue.append(old)
    return out


def list_rows(sym):
    """NSE filing list for sym AND its era symbols, merged (each cached separately).
    The symbol goes through urllib.parse.quote — J&KBANK/L&TFH/GVT&D were silently
    truncated at the '&' before (symbol=J), which read as 'no filings'."""
    import urllib.parse

    rows = []
    for s in [sym, *aliases(sym)]:
        lp = os.path.join(CACHE, "list_{}.json".format(re.sub(r"[^A-Z0-9]", "_", s.upper())))
        got, err = None, None
        # the list endpoint is the fragile www.nseindia.com API (cookie-gated, rate-limited);
        # a silent fallback to current-symbol rows here made the whole rename pass no-op with
        # zero diagnostics. Retry once with a fresh jar, and SAY when an alias list is lost.
        for _attempt in (1, 2):
            try:
                raw = get(
                    "https://www.nseindia.com/api/corporates-financial-results"
                    "?index=equities&symbol={}&period=Quarterly".format(urllib.parse.quote(s, safe="")),
                    lp,
                )
                got = json.loads(raw)
                break
            except Exception as e:
                err = type(e).__name__
                global JAR
                JAR = BF.nse_jar()
                time.sleep(1.5)
        if got is None:
            print(f"   [list {s}: {err} — era rows LOST]", flush=True)
            continue
        if isinstance(got, list):
            rows.extend(got)
    return rows


def get_detail(link, sym, path=None):
    """Fetch a financial_res_<SYM>_<id>.html detail page, falling back to ERA-symbol filenames.

    NSE's list API rewrites the filename to the CURRENT symbol (financial_res_GMRAIRPORT_131242
    .html) but the archived file keeps the name the company had when it filed — the rewritten URL
    404s while financial_res_GMRINFRA_131242.html serves 13KB. Proven the whole rename residue:
    fills AND skips were both zero because the fetch failed silently before any row was parsed."""
    names = [link]
    m = re.match(r"(.*financial_res_)(.+)(_\d+\.html?)$", link, re.IGNORECASE)
    if m:
        # `sym` ITSELF is a candidate too (2026-09-02, CON-GAP PRE-2020): when the list is queried
        # under an era name (AGCNET) the API still rewrites the filename to the CURRENT name
        # (financial_res_BBOX_53155.html, 404) while the stored file carries the era name that
        # was asked for -- aliases(sym) lists only names OLDER than sym, so AGCNET was never tried
        # and all 14 of its 2008-2011 consolidated pages read as fetch:HTTPError.
        for a in [sym, *aliases(sym)]:
            if a.upper() != m.group(2).upper():
                names.append(m.group(1) + a + m.group(3))
    err = None
    for u in names:
        try:
            return get(u, path)
        except Exception as e:
            err = e
    raise err


def iso_qe(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    if not m or m.group(2).title() not in MON:
        return None
    return int(m.group(3)) * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))


def get(url, path=None):
    if path and os.path.exists(path):
        cached = open(path, encoding="utf8", errors="replace").read()
        if cached.strip():
            return cached
        os.remove(path)  # never trust an EMPTY cache entry: a transient 0-byte response was
        # being written and then re-read forever, so the page parsed to 0 rows
        # and reported "pat-anchor None" as if the label regex had failed
    # '&' inside the PATH (J&KBANK, M&M, GVT&D detail files) must be %26 — raw, the archive
    # server parses it as a separator and returns a 2.8KB empty shell, which then gets cached.
    base, sep, q = url.partition("?")
    d = BF._get(base.replace("&", "%26") + sep + q, headers=H, jar=JAR)
    if isinstance(d, bytes):
        d = d.decode("utf8", "replace")
    if path and d.strip():
        open(path, "w", encoding="utf8").write(d)
    return d


def cells_of(html):
    t = re.sub(r"<[^>]+>", "|", html)
    t = re.sub(r"&nbsp;?", " ", t)
    return [c.strip() for c in t.split("|") if c.strip()]


def parse_detail(html):
    """-> dict(meta=..., rows=[(label, value)]) with value already scaled to CRORE."""
    cells = cells_of(html)
    meta, rows = {}, []
    for i, c in enumerate(cells):
        nxt = cells[i + 1] if i + 1 < len(cells) else ""
        if c in ("Consolidated / Non-Consolidated", "Period Ended", "Symbol", "Audited / Un-Audited"):
            meta[c] = nxt
        if c in ("Banking", "Non Banking"):
            meta["fmt"] = c
        m = re.match(r"Amount\s*\(\s*Rs\.?\s*in\s*(lakhs?|crores?|thousands?|millions?)", c, re.IGNORECASE)
        if m:
            meta["unit"] = m.group(1).lower()
        if not NUM.match(c) and NUM.match(nxt or ""):
            with contextlib.suppress(ValueError):
                rows.append((c, float(nxt.replace(",", ""))))
    # declared unit -> crore. Absent unit is treated as lakhs (the archive's overwhelming default);
    # a wrong guess simply fails the PAT anchor rather than writing a mis-scaled cell.
    div = {
        "lakh": 100.0,
        "lakhs": 100.0,
        "crore": 1.0,
        "crores": 1.0,
        "thousand": 10000.0,
        "thousands": 10000.0,
        "million": 10.0,
        "millions": 10.0,
    }
    d = div.get(meta.get("unit", "lakhs"), 100.0)
    meta["div"] = d
    return meta, [(lab, v / d) for lab, v in rows]


# Strip a LEADING ROW NUMBER only: "13 ", "(a) ", "iv. ". The earlier form of this pattern was
# ^\(?[a-z0-9]{1,3}\)?[\.\s]+ , which also matches the first WORD of a label when it is <=3 letters
# — it ate the "Net " of "Net Profit / (Loss) for the period", so every `net profit` regex missed
# and ~4,500 pre-2017 cells were skipped as "pat-anchor None". 2017 filings hid the bug because
# their labels embed a serial ("13 Net Profit ..."), where stripping happens to produce a clean match.
ROWNUM = re.compile(r"^\(?(?:\d{1,3}|[ivxlcdm]{1,4}|[a-z])\)?[\.\)\s]+", re.IGNORECASE)


def pick(rows, *pats):
    for p in pats:
        for lab, v in rows:
            lab = lab.strip()
            # test the RAW label first, then the de-numbered one — never only the stripped form
            if p.search(lab) or p.search(ROWNUM.sub("", lab)):
                return v
    return None


def close(a, b):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(2.0, 0.03 * max(abs(a), abs(b)))


def main():
    global JAR
    argv = sys.argv
    gapf = argv[argv.index("--gaps") + 1] if "--gaps" in argv else os.path.join(HERE, "_gaps_pre2018.json")
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    shard = argv[argv.index("--shard") + 1] if "--shard" in argv else None
    suffix = argv[argv.index("--out-suffix") + 1] if "--out-suffix" in argv else ""
    # --basis con|std (2026-09-02, WP1 revCon): the reads file is keyed by (sym, qe) only, so a
    # quarter read once for STD was never re-visited for CON -- 181 of the Nifty-500 revCon gaps
    # carried a std-only entry that made `want` drop the quarter before any con page was fetched
    # (memory feedback-key-the-ledger-by-basis). With --basis, a quarter counts as done only when
    # an entry of THAT basis exists, list rows of the other basis are not fetched, and a page whose
    # DECLARED basis differs is skipped after parsing (the page, never the index row, is trusted).
    # Without the flag the legacy basis-blind behaviour is unchanged.
    basis_want = argv[argv.index("--basis") + 1] if "--basis" in argv else None
    if basis_want not in (None, "con", "std"):
        sys.exit("--basis must be con or std")

    outp = OUT.replace(".json", suffix + ".json")
    skipp = SKIPS.replace(".json", suffix + ".json")
    gaps = json.load(open(gapf))
    revop_now = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    # seed from the shared reads so a shard never re-fetches a cell another shard already got
    out = json.load(open(OUT)) if (suffix and os.path.exists(OUT)) else {}
    if os.path.exists(outp):
        for s, v in json.load(open(outp)).items():
            out.setdefault(s, {}).update(v)
    skips = json.load(open(skipp)) if os.path.exists(skipp) else {}
    JAR = BF.nse_jar()

    syms = sorted(gaps)
    if only:
        syms = [s for s in syms if s in only]
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        syms = [s for k, s in enumerate(syms) if k % n == i]
        print("shard %s: %d companies" % (shard, len(syms)), flush=True)
    if limit:
        syms = syms[:limit]

    nfill = 0
    for si, sym in enumerate(syms, 1):

        def have(q):
            ent = out.get(sym, {}).get(str(q))
            if ent is None:
                return False
            if basis_want is None:
                return True
            return any(e.get("basis") == basis_want for e in (ent if isinstance(ent, list) else [ent]))

        want = {int(q) for q in gaps[sym] if not have(q)}
        if not want:
            continue
        rows = list_rows(sym)
        if not rows:
            skips[f"{sym}|list"] = "no-nse-filings-any-era"
            continue

        for r in rows:
            qe = iso_qe(r.get("toDate"))
            if qe not in want or not r.get("resultDetailedDataLink"):
                continue
            if basis_want:
                row_basis = "con" if str(r.get("consolidated", "")).strip().lower() == "consolidated" else "std"
                if row_basis != basis_want:
                    continue
            link = r["resultDetailedDataLink"]
            dp = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link.rsplit("/", 1)[-1]))
            try:
                html = get_detail(link, sym, dp)
            except Exception:
                continue
            meta, prows = parse_detail(html)
            isbank = meta.get("fmt") == "Banking"
            # financial-format per the DATA (any existing cell fin=1), never the ticker name —
            # catches AAVAS/DHANI/HUDCO/SHRIRAMFIN-class NBFCs no name regex would
            isfin = isbank or any(
                c[6] == 1 for c in (revop_now.get(sym) or {}).values() if len(c) > 6 and c[6] is not None
            )
            basis = "con" if "Non" not in (meta.get("Consolidated / Non-Consolidated") or "Non") else "std"
            if basis_want and basis != basis_want:
                skips["%s|%d|%s" % (sym, qe, basis_want)] = f"page-basis-{basis}-not-{basis_want}"
                continue
            frow = fmap.get(sym, {}).get(qe)
            if not frow:
                continue
            stored = frow[1] if basis == "std" else (frow[3] if len(frow) > 3 else None)
            pat = pick(prows, R_PAT_OWN) if not isbank else None
            pat2 = pick(prows, R_PAT_ANY)
            # R_PAT_SIGNED was DEFINED ABOVE BUT NEVER CALLED (found 2026-08-26, pre-2009 std-rev
            # campaign). Its own comment describes the exact label it was written for --
            # "Net Profit (+) / Loss (-) for the period" -- which made that comment the bug's
            # alibi: the pattern existed, was correct, and no code path ever reached it, while
            # R_REV_SIGNED two blocks below WAS wired in. That spelling is the DOMINANT one in the
            # 2005-2008 archive: of 148 pages re-read for the refusals this campaign recorded, 128
            # print it, and R_PAT_ANY matches none of them (it wants "loss" adjacent to "for the
            # period"; here the "(-)" marker sits between). 121 std cells were refused as
            # "pat-anchor None" with the number plainly on the page.
            # Tried STRICTLY LAST, exactly as the comment above always claimed it was: the loop
            # breaks on the first candidate matching the stored anchor, so a last-place candidate
            # cannot change any page that resolves today -- it can only rescue one resolving None.
            pat3 = pick(prows, R_PAT_SIGNED)
            # PRE-2011 CONSOLIDATED pages print minority interest / associates as signed deductions
            # BELOW the period row and then "Consolidated Net Profit (+) / Loss (-) for the period"
            # = the owners-attributable figure this dataset stores (GMRINFRA Sep-2010: period 42.53,
            # consolidated 71.12 = stored). The three candidates above all read the PERIOD row, so
            # every such page failed the con anchor. Tried strictly LAST, same rule as pat3
            # (2026-09-02, CON-GAP PRE-2020 campaign).
            pat4 = pick(prows, R_PAT_CONNET) if basis == "con" else None
            hit = None
            for cand in (pat, pat2, pat3, pat4):
                if close(cand, stored):
                    hit = cand
                    break
            if hit is None:
                # report whichever PAT row WAS read, so a refusal stays diagnosable rather than
                # printing None when only the signed spelling was present
                seen = next((c for c in (pat2, pat3, pat) if c is not None), None)
                skips["%s|%d|%s" % (sym, qe, basis)] = (
                    f"pat-anchor {round(seen, 2) if seen is not None else None} vs stored {stored}"
                )
                continue
            # `is None` chaining, never `or` -- a legitimate 0.00 is falsy and would fall through.
            if isbank:
                rev = pick(prows, R_REV_BANK)
            else:
                rev = pick(prows, R_REV_IND, R_REV_IND2, R_REV_IND3)
                if rev is None:
                    rev = pick(prows, R_REV_SIGNED)
                if rev is None:
                    rev = pick(prows, R_REV_IND5)
            # LAST RESORT, FINANCIALS ONLY. For a bank/NBFC "Total Income" is the genuine top
            # line. For an industrial it is not: NAHARPOLY Jun-2008 prints Other Income 0.53 and
            # Total Income 0.53 with NO sales row at all, so taking Total Income there would
            # publish 0.53 as "revenue" for a company whose operating revenue is actually absent
            # -- the same holding-company shape where this dataset correctly stores None
            # (cf. BHARTIARTL). Caught 2026-08-07 before any of it was pushed.
            if rev is None and isfin:
                rev = pick(prows, R_REV_TOTINC)
            if rev is None or rev <= 0:
                skips["%s|%d|%s" % (sym, qe, basis)] = "no-rev-row"
                continue
            if isbank:
                op = pick(prows, R_OP_BANK)
            elif isfin:
                # NBFC/HFC: the printed "before other income, finance costs" line is not an
                # operating profit for a lender — finance cost IS its operating expense (SHRIRAMFIN
                # came out op 1,806 on rev 2,717). Same guard as the XBRL branch: leave op unset.
                op = None
            else:
                op = pick(prows, R_OP_IND)
            if op == 0.0:
                op = None  # a printed 0.00 on a crore-scale filer is a placeholder row, not a result
            prev = out.setdefault(sym, {}).get(str(qe))
            ent = {
                "rev": round(rev, 2),
                "op": None if op is None else round(op, 2),
                "pat_seen": round(hit, 2),
                "basis": basis,
                "fin": 1 if (isbank or isfin) else 0,
                "src": "nse-archive {} ({}, {})".format(
                    link.rsplit("/", 1)[-1], meta.get("unit", "lakhs"), meta.get("fmt", "?")
                ),
            }
            out[sym][str(qe)] = (prev if isinstance(prev, list) else ([prev] if prev else [])) + [ent] if prev else ent
            nfill += 1
            print(
                "%-12s %d %-3s -> rev %.2f op %s (anchor %.2f)"
                % (sym, qe, basis, rev, "None" if op is None else round(op, 2), hit),
                flush=True,
            )
        json.dump(out, open(outp, "w", encoding="utf8"), indent=1, sort_keys=True)
        json.dump(skips, open(skipp, "w", encoding="utf8"), indent=0, sort_keys=True)
        if si % 20 == 0:
            print("  [%d/%d] %d cells" % (si, len(syms), nfill), flush=True)
        time.sleep(0.3)

    print("DONE: %d cells -> %s" % (nfill, os.path.basename(outp)), flush=True)


if __name__ == "__main__":
    main()

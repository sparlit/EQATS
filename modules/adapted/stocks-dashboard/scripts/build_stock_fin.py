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
"""Build docs/fin/<SLUG>.json — the per-stock FINANCIALS slice for docs/stock.html.

WHY SEPARATE FROM THE PRICE SLICE (build_stock_slices.py)
  Prices move for every stock every trading day, so price slices are force-pushed
  to the sf-data Pages repo (committing 40 MB/day here would be repo suicide).
  Financials move on a completely different clock: one company at a time, whenever
  it files. Only that company's file changes, so these CAN be committed — git only
  stores the handful of blobs that actually changed — and rebuilding them the
  moment a results workflow lands keeps the page as fresh as the feed. Folding
  them into the daily price push instead would have left the quarterly table up to
  24 h stale in the middle of results season.

WHAT IT REPLACES
  stock.html used to pull sf_fundamentals.json (3.2 MB) + sf_revop.json (3.9 MB) +
  shareholding.json (0.9 MB) — 8 MB of whole-market data — to fill one company's
  three tables. A fin slice is ~2 KB.

  fund   point-in-time quarterly net profit, OWNERS-attributable
         [[qEndYYYYMMDD, npStd, annStd, npCon, annCon], …]  (sf_fundamentals.json)
  revop  {qEnd: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]}
         (sf_revop.json — op = EBITDA, fin=1 marks banks/NBFCs; idx4/idx5 are a PAT
         MIRROR only — incomplete, never rendered; PAT authority is `fund`, runbook §70)
  shpQ   quarter-end dates, newest first ] the stock's row of the quarterly
  shp    the matching holding cells       ] shareholding-pattern feed
  shpH   FULL shareholding history, oldest first (scripts/shp_history.json —
         back to 2019-09-30): [[qEndISO, prom%, fii%, dii%, mf%, ins%,
         subDate, nShareholders], …]. shpQ/shp (8 quarters) stay for readers
         that predate it; the page prefers shpH when present.
  x      DEEP quarter detail from the XBRL re-parse (scripts/xbrl_extra.json[.gz],
         built by build_xbrl_extra.py): {qEnd: {s:{...}, c:{...}}} — EPS, interest/
         depreciation/tax/exceptional, balance sheet, cash flow (+cf_d period days),
         segments, bank NPA/CET1/ROA, audited flag. ₹ crore / ₹ per share / %.

RENAMES
  Fundamentals are keyed by a company's CURRENT ticker while its price history
  keeps trading under the name of the day (TATAMOTORS→TMPV, PVR→PVRINOX, …), so a
  slice is also written under every OLD symbol that resolves into a live one —
  the same fallback fundFor()/FUND_ALIAS does in backtest-engine.js. Without it
  every renamed stock's page would show "no quarterly earnings on file".

Run: python scripts/build_stock_fin.py [--out DIR]   (--out: local verification
     builds that must not touch the committed docs/fin/)
"""
import argparse
import gzip
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "fin")

FUND_J = os.path.join(DOCS, "sf_fundamentals.json")
REVOP_J = os.path.join(DOCS, "sf_revop.json")
SHP_J = os.path.join(DOCS, "shareholding.json")
SHPH_J = os.path.join(HERE, "shp_history.json")
GOV_J = os.path.join(DOCS, "shp_gov.json")  # Government holding sidecar {SYM:{QE:[gov%,sub]}}
XTRA_J = os.path.join(HERE, "xbrl_extra.json")  # local build output…
XTRA_GZ = XTRA_J + ".gz"  # …the committed copy CI reads
RENAME = os.path.join(HERE, "_rename_map.json")
BSEFUND_J = os.path.join(DOCS, "bse_fundamentals.json")  # BSE-ONLY rev/PAT, keyed by scripcode
BSESCRIP_J = os.path.join(HERE, "bse_scrips.json")  # {by_id:{SYM:scripcode}} → sym lookup

# per-quarter detail fields the PAGE consumes — the rest of the ledger stays local-only
XTRA_KEEP = {
    "eps_b",
    "eps_d",
    "oi",
    "fc",
    "dep",
    "tax",
    "exc",
    "pbt",
    "emp",
    "mat",
    "assoc",
    "nci",
    "assets",
    "eq",
    "sc",
    "oeq",
    "borr",
    "blt",
    "bst",
    "cash",
    "invnt",
    "rec",
    "pay",
    "ppe",
    "cwip",
    "iuad",
    "gw",
    "intg",
    "invst",
    "cfo",
    "cfi",
    "cff",
    "capex",
    "divp",
    "cf_tax",
    "cf_d",
    "seg",
    "gnpa_pct",
    "nnpa_pct",
    "cet1",
    "car",
    "roa",
    "dep_amt",
    "adv",
    "int_exp",
    "aud",
    "qual",
}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def slug(sym):
    """Filename for a symbol. Mirrored by slugSym() in docs/stock.html."""
    return _UNSAFE.sub("_", sym)


def load(path, what):
    if not os.path.exists(path):
        print(f"WARN: {os.path.basename(path)} missing — {what} will be absent from every slice")
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT, help="output dir (default docs/fin — CI path)")
    args = ap.parse_args()
    out_dir = args.out

    fund = load(FUND_J, "net profit")
    revop = load(REVOP_J, "revenue/margins")
    shpj = load(SHP_J, "shareholding")
    shph = load(SHPH_J, "shareholding history")
    govj = load(GOV_J, "government holding")
    # {SYM: {QE: gov%}} — the sidecar stores [gov%, sub]; the page only needs the percentage
    gov_rows = {}
    for sym, qmap in (govj or {}).items():
        if sym.startswith("_") or not isinstance(qmap, dict):
            continue
        g = {
            qe: (v[0] if isinstance(v, list) else v)
            for qe, v in qmap.items()
            if (v[0] if isinstance(v, list) else v) is not None
        }
        if g:
            gov_rows[sym] = g
    if not fund and not revop:
        sys.exit("ABORT: neither sf_fundamentals.json nor sf_revop.json could be read")
    if fund and len(fund) < 2000:
        sys.exit("ABORT: sf_fundamentals.json has only %d symbols — refusing to publish truncated slices" % len(fund))

    shp_q = shpj.get("quarters") or []
    shp_rows = {r[0]: r for r in (shpj.get("rows") or []) if r}

    # full history, oldest first: {SYM:{QE:[prom,fii,dii,mf,ins,subDate,nsh?]}} → [[QE,…7 fields], …]
    hist_rows = {}
    for sym, qmap in shph.items():
        if sym.startswith("_") or not isinstance(qmap, dict):
            continue
        rows = [[qe, *list((qmap[qe] or [])[:7])] for qe in sorted(qmap)]
        if rows:
            hist_rows[sym] = rows

    # deep XBRL detail — prefer the local build output, fall back to the committed .gz (CI path)
    xtra = {}
    src = XTRA_J if os.path.exists(XTRA_J) else (XTRA_GZ if os.path.exists(XTRA_GZ) else None)
    if src:
        try:
            raw = open(src, "rb").read()
            if src.endswith(".gz"):
                raw = gzip.decompress(raw)
            for sym, qs in json.loads(raw).items():
                keep = {}
                for qe, cell in qs.items():
                    kc = {}
                    for b in ("s", "c"):
                        d = cell.get(b)
                        if d:
                            kd = {k: v for k, v in d.items() if k in XTRA_KEEP}
                            if kd:
                                kc[b] = kd
                    if kc:
                        keep[qe] = kc
                if keep:
                    xtra[sym] = keep
            print("deep XBRL detail: %d symbols (from %s)" % (len(xtra), os.path.basename(src)))
        except Exception as e:
            print(f"WARN: could not read {os.path.basename(src)} ({e}) — deep detail absent from every slice")
    else:
        print("WARN: xbrl_extra.json[.gz] missing — deep detail absent from every slice")

    # Annual balance-sheet / cash-flow fills read from each company's OWN audited-result PDF
    # (scripts/annual_bscf.json, built by fetch_annual_bscf.py; every filer holdout-gated against the
    # years we already hold from XBRL). GAP-FILL ONLY — never overwrites an XBRL value; the cell is
    # marked 'pdf' so the page can attribute it to the annual report rather than the XBRL filing.
    abscf_p = os.path.join(HERE, "annual_bscf.json")
    if os.path.exists(abscf_p):
        try:
            abscf = json.load(open(abscf_p))
            PDF_FIELDS = {
                "assets",
                "sc",
                "oeq",
                "borr",
                "blt",
                "bst",
                "ppe",
                "cwip",
                "gw",
                "intg",
                "invst",
                "rec",
                "pay",
                "invnt",
                "cfo",
                "cfi",
                "cff",
                "capex",
                "cf_tax",
            }
            nfill = 0
            for sym, qs in abscf.items():
                if sym.startswith("_") or not isinstance(qs, dict):
                    continue
                for qe, cell in qs.items():
                    if not isinstance(cell, dict):
                        continue
                    b = cell.get("b") or "c"
                    tgt = xtra.setdefault(sym, {}).setdefault(qe, {}).setdefault(b, {})
                    added = False
                    for k, v in cell.items():
                        if k in PDF_FIELDS and v is not None and tgt.get(k) is None:
                            tgt[k] = v
                            added = True
                    if added:
                        tgt["pdf"] = 1
                        nfill += 1
            print("annual BS/CF PDF fills: %d cells gap-filled (from %s)" % (nfill, os.path.basename(abscf_p)))
        except Exception as e:
            print(f"WARN: annual_bscf.json unreadable ({e}) — skipped")

    # Insights card — operating KPIs read from the company's own presentations (runbook §137).
    # scripts/kpi_insights/<SLUG>.json is the ledger; the slice carries it compacted, verbatim
    # values, with the per-cell provenance [attachment, page, label, as_printed] the ⓘ shows.
    kpi = {}
    kpi_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_insights")
    if os.path.isdir(kpi_dir):
        for fn in sorted(os.listdir(kpi_dir)):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            try:
                L = json.load(open(os.path.join(kpi_dir, fn), encoding="utf-8"))
            except Exception as e:
                print(f"WARN: kpi ledger {fn} unreadable ({e}) — skipped")
                continue
            mets = []
            for m in L.get("metrics") or []:
                if not (m.get("y") or m.get("q")):
                    continue
                mets.append(
                    {
                        "n": m.get("name", ""),
                        "u": m.get("unit", ""),
                        "k": m.get("kind", "level"),
                        "y": m.get("y") or {},
                        "q": m.get("q") or {},
                        "src": m.get("src") or {},
                    }
                )
            if not mets or not L.get("sym"):
                continue
            docs = {}
            for att, d in (L.get("docs") or {}).items():
                e = {"d": d.get("date"), "t": d.get("title", ""), "k": d.get("kind")}
                if d.get("url"):
                    e["u"] = d["url"]
                docs[att] = e
            kpi[L["sym"]] = {"fy": L.get("fy_end_month", 3), "u": L.get("updated"), "m": mets, "docs": docs}
        print("insights (kpi): %d symbols" % len(kpi))

    aliases = {}
    if os.path.exists(RENAME):
        try:
            aliases = json.load(open(RENAME, encoding="utf-8"))
        except Exception as e:
            print(f"WARN: could not read _rename_map.json ({e}) — renamed tickers will show no financials")

    # --- BSE-ONLY names: fold docs/bse_fundamentals.json (keyed by scripcode) into fund/revop so a
    #     fin slice is emitted for them too. build_bse_slices.py cuts their PRICE slice; without this
    #     their page shows a chart but "no quarterly earnings on file". Rev+PAT only (the BSE OCR route
    #     has no EBITDA/EPS); basis S|C routes pat into the std or con slot; ann is the announce date
    #     (0 → unknown). Never overwrites a symbol that already has NSE data, and skips any ticker whose
    #     slug clashes with an existing name (recycled tickers) so the collision guard never trips. ----
    bse_added = 0
    if os.path.exists(BSEFUND_J) and os.path.exists(BSESCRIP_J):
        try:
            bfin = json.load(open(BSEFUND_J, encoding="utf-8")).get("px", {})
            code2sym = {str(v): k for k, v in json.load(open(BSESCRIP_J, encoding="utf-8")).get("by_id", {}).items()}
            taken = {slug(s) for s in (set(fund) | set(revop) | set(shp_rows) | set(hist_rows))}
            for code, qmap in bfin.items():
                sym = code2sym.get(str(code))
                if not sym or sym in fund or sym in revop or not isinstance(qmap, dict):
                    continue  # already have real data, or unmappable
                if slug(sym) in taken:
                    continue  # ticker-string clash with an NSE name
                frows, rv = [], {}
                for qe, cell in qmap.items():
                    if not isinstance(cell, dict) or not qe.isdigit():
                        continue
                    pat, rev = cell.get("pat"), cell.get("rev")
                    ann = cell.get("ann") or None  # 0 → unknown announce date
                    con = cell.get("basis") == "C"
                    qei = int(qe)
                    if pat is not None:  # fund: [qEnd, npStd, annStd, npCon, annCon]
                        frows.append([qei, None, None, pat, ann] if con else [qei, pat, ann, None, None])
                    # revop: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
                    rv[qe] = (
                        [None, rev, None, None, None, pat, 0, None, None]
                        if con
                        else [rev, None, None, None, pat, None, 0, None, None]
                    )
                if frows:
                    fund[sym] = sorted(frows, key=lambda r: r[0])
                if rv:
                    revop[sym] = rv
                if frows or rv:
                    taken.add(slug(sym))
                    bse_added += 1
            print("BSE-only fundamentals folded in: %d symbols" % bse_added)
        except Exception as e:
            print(f"WARN: could not fold bse_fundamentals.json ({e}) — BSE-only names get no fin slice")

    # every symbol that has data, plus each old name that resolves into one
    syms = set(fund) | set(revop) | set(shp_rows) | set(hist_rows)
    for old, new in aliases.items():
        if new in syms:
            syms.add(old)

    def resolve(src, sym):
        v = src.get(sym)
        if v:
            return v
        alias = aliases.get(sym)
        return src.get(alias) if alias else None

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)  # drop slices for symbols that left the feeds
    os.makedirs(out_dir, exist_ok=True)

    seen, written, total = {}, 0, 0
    for sym in sorted(syms):
        sl = slug(sym)
        if sl in seen:
            sys.exit(f"ABORT: slug collision {sl!r}: {seen[sl]} and {sym}")
        seen[sl] = sym

        payload = {"sym": sym}
        f = resolve(fund, sym)
        if f:
            payload["fund"] = f
        r = resolve(revop, sym)
        if r:
            payload["revop"] = r
        row = resolve(shp_rows, sym)
        if row and row[4]:
            payload["shpQ"] = shp_q
            payload["shp"] = row[4]
        h = resolve(hist_rows, sym)
        if h:
            payload["shpH"] = h
        gv = resolve(gov_rows, sym)
        if gv:
            payload["shpGov"] = gv  # {QE: gov%} — Screener's separate Government row
        xt = resolve(xtra, sym)
        if xt:
            payload["x"] = xt
        kp = resolve(kpi, sym)
        if kp:
            payload["kpi"] = kp
        if len(payload) == 1:
            continue  # nothing on file for this ticker

        blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with open(os.path.join(out_dir, sl + ".json"), "w", encoding="utf-8") as fh:
            fh.write(blob)
        written += 1
        total += len(blob.encode())

    print(
        "fin slices: %d symbols (%d with profit, %d with revenue, %d with SHP, %d with SHP history), "
        "%.1f MB raw, avg %.1f KB"
        % (written, len(fund), len(revop), len(shp_rows), len(hist_rows), total / 1e6, total / max(written, 1) / 1024)
    )


if __name__ == "__main__":
    main()

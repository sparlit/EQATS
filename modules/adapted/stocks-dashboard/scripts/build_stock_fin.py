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
         that predate it; the page prefers shpH when present. A re-filed quarter
         (§142k, scripts/shp_revisions.json) shows the re-filing's percentages and
         adds [8] its date + [9] the original five, which a Rewind before [8] shows.
  x      DEEP quarter detail from the XBRL re-parse (scripts/xbrl_extra.json[.gz],
         built by build_xbrl_extra.py): {qEnd: {s:{...}, c:{...}}} — EPS, interest/
         depreciation/tax/exceptional, balance sheet, cash flow (+cf_d period days),
         segments, bank NPA/CET1/ROA, audited flag. ₹ crore / ₹ per share / %.
         pm = 6: the cell's P&L lines are a PROVEN half-year's (runbook §213).
  pd     {qEnd: 3|6|12} — result rows whose length the filings PROVE: 6 (or 12) for a
         half-year (an SME half-yearly filer's Sep row is Apr-Sep, its Mar row Oct-Mar),
         3 for a quarter inside a year that also holds a half-year (a filer of Q1 + H1 +
         Q3 + H2, QMSMEDI). Proven by scripts/build_row_periods.py (scripts/row_periods.json)
         and kept here only while the revenue the row publishes is still the proven one.
         Absent = every row is a quarter. The page counts a year only when its rows
         tile the 12 months (runbook §191); the TTM cards and the backtest engines read
         any other row of a year that holds a half-year as UNKNOWN length (§198).
  pp     [qEnd, …] — the rows of pd whose PROFIT is proven too (it equals what the proving
         filing prints); a pd row's profit counts toward a TTM only when listed here (§198).
  docs/fund_months.json (one whole-market file, for the backtest engines, which read
         sf_fundamentals and never load a slice): {SYM: {qEnd: m}} — the same marks,
         m = the row's length when its profit is proven, -m when only its revenue is.

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
REVS_J = os.path.join(
    HERE, "shp_revisions.json"
)  # §142k re-filings {SYM:{QE:[prom,fii,dii,mf,ins,revDate,nsh,src]}}
XTRA_J = os.path.join(HERE, "xbrl_extra.json")  # local build output…
XTRA_GZ = XTRA_J + ".gz"  # …the committed copy CI reads
RENAME = os.path.join(HERE, "_rename_map.json")
BSEFUND_J = os.path.join(DOCS, "bse_fundamentals.json")  # BSE-ONLY rev/PAT, keyed by scripcode
BSESCRIP_J = os.path.join(HERE, "bse_scrips.json")  # {by_id:{SYM:scripcode}} → sym lookup
ROWP_J = os.path.join(
    HERE, "row_periods.json"
)  # rows proven to cover 6/12 months (build_row_periods.py)
COLLIDE_J = os.path.join(
    DOCS, "bse_alias_collisions.json"
)  # BSE tickers the NSE rename aliases must not touch (§197)

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
    "invprop",
    "bio",
    "prodprop",
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
    "pm",
}  # 6 = the cell's P&L lines cover a PROVEN half-year (fill_sme_halfyear_pnl.py, runbook §213)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def slug(sym):
    """Filename for a symbol. Mirrored by slugSym() in docs/stock.html."""
    return _UNSAFE.sub("_", sym)


def nse_tape_isin():
    """{NSE symbol: ISIN} from the committed docs/sf_stock_data.bin — only its trailing "meta" object is decoded
    (0.5 s; bars never parsed). Empty if absent. Used to prove a BSE scrip and an NSE key are one company."""
    try:
        b = gzip.decompress(open(os.path.join(DOCS, "sf_stock_data.bin"), "rb").read())
        m, _ = json.JSONDecoder().raw_decode(b[b.rfind(b'"meta":') + 7 :].decode("utf-8"))
        return {k: v["isin"] for k, v in m.items() if isinstance(v, dict) and v.get("isin")}
    except (OSError, ValueError):
        return {}


def load(path, what):
    if not os.path.exists(path):
        print(f"WARN: {os.path.basename(path)} missing — {what} will be absent from every slice")
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT, help="output dir (default docs/fin — CI path)")
    ap.add_argument(
        "--months",
        default=None,
        help="engines' row-length file (default: fund_months.json beside the output dir → docs/)",
    )
    args = ap.parse_args()
    out_dir = args.out
    months_path = args.months or os.path.join(
        os.path.dirname(os.path.abspath(out_dir)), "fund_months.json"
    )

    fund = load(FUND_J, "net profit")
    revop = load(REVOP_J, "revenue/margins")
    rowp = {
        k: v
        for k, v in load(
            ROWP_J, "half-year row marks (SME half-years will read as quarters)"
        ).items()
        if not k.startswith("_")
    }
    shpj = load(SHP_J, "shareholding")
    shph = load(SHPH_J, "shareholding history")
    govj = load(GOV_J, "government holding")
    revs = load(REVS_J, "shareholding re-filings")
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
        sys.exit(
            "ABORT: sf_fundamentals.json has only %d symbols — refusing to publish truncated slices"
            % len(fund)
        )

    shp_q = shpj.get("quarters") or []
    shp_rows = {r[0]: r for r in (shpj.get("rows") or []) if r}

    # full history, oldest first: {SYM:{QE:[prom,fii,dii,mf,ins,subDate,nsh?]}} → [[QE,…7 fields], …]
    hist_rows = {}
    for sym, qmap in shph.items():
        if sym.startswith("_") or not isinstance(qmap, dict):
            continue
        rows = [[qe] + list((qmap[qe] or [])[:7]) for qe in sorted(qmap)]
        # §142k: the page shows a quarter's LATEST re-filing — the same overlay docs/shareholding.json applies
        # (re-filing's five percentages, the original's date and holder count). The row also carries
        # [8] the re-filing's date and [9] the original five, so a Rewind before that date shows the original.
        rv = (revs or {}).get(sym) or {}
        for r in rows:
            rc = rv.get(r[0])
            c = r[1:]
            if not (isinstance(rc, list) and len(rc) > 5 and len(c) >= 6 and rc[5]):
                continue
            try:
                if all(
                    abs(float(x) - float(y)) <= 0.0100001
                    for x, y in zip(rc[:5], c[:5], strict=False)
                ):
                    continue  # same numbers re-published: nothing to show
            except (TypeError, ValueError):
                continue
            orig = list(c[:5])
            r[1:6] = list(rc[:5])
            while len(r) < 8:
                r.append(None)
            r[8:] = [str(rc[5])[:10], orig]
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
            xall = json.loads(raw)
            # §214a F3: serve-time re-assert of the proven single cells (filer XBRL slips), so a ledger copy
            # from before a heal cannot put the slip back on the page
            try:
                if HERE not in sys.path:
                    sys.path.insert(0, HERE)
                import xtra_cell_fix

                nc = xtra_cell_fix.reassert(xall)
                if nc:
                    print("xtra_cell_fix: re-asserted %d cells at serve time" % nc)
            except Exception as e:  # a broken fix ledger must never drop the whole detail
                print(f"::warning::xtra_cell_fix not applied at serve time ({e})")
            for sym, qs in xall.items():
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
            print(
                f"WARN: could not read {os.path.basename(src)} ({e}) — deep detail absent from every slice"
            )
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
            # iuad: the page shows CWIP as cwip + iuad (Screener's convention) — without it every
            # PDF year's CWIP read low against the XBRL years beside it (BEL, AUROPHARMA, 2026-09-26)
            PDF_FIELDS = {
                "assets",
                "sc",
                "oeq",
                "borr",
                "blt",
                "bst",
                "ppe",
                "cwip",
                "iuad",
                "gw",
                "intg",
                "invprop",
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
            nfill = nover = 0
            for sym, qs in abscf.items():
                if sym.startswith("_") or not isinstance(qs, dict):
                    continue
                for qe, cell in qs.items():
                    if not isinstance(cell, dict):
                        continue
                    b = cell.get("b") or "c"
                    tgt = xtra.setdefault(sym, {}).setdefault(qe, {}).setdefault(b, {})
                    added = False
                    # 'xo' = fields whose PRINTED value is proven over the XBRL tag (the statement's own cash identity
                    # closes with the print and not with the tag — CYIENT FY22 tagged CFO 1,060.7 against a printed
                    # 634.5; runbook §168l). Only those fields override; everything else stays gap-fill.
                    xo = set(cell.get("xo") or ())
                    for k, v in cell.items():
                        if k in PDF_FIELDS and v is not None and (tgt.get(k) is None or k in xo):
                            if tgt.get(k) is not None and k in xo and tgt[k] != v:
                                nover += 1
                            tgt[k] = v
                            added = True
                    if added:
                        tgt["pdf"] = 1
                        nfill += 1
            print(
                "annual BS/CF PDF fills: %d cells gap-filled, %d XBRL values overridden by proven prints (from %s)"
                % (nfill, nover, os.path.basename(abscf_p))
            )
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
            kpi[L["sym"]] = {
                "fy": L.get("fy_end_month", 3),
                "u": L.get("updated"),
                "m": mets,
                "docs": docs,
            }
        print("insights (kpi): %d symbols" % len(kpi))

    aliases = {}
    if os.path.exists(RENAME):
        try:
            aliases = json.load(open(RENAME, encoding="utf-8"))
        except Exception as e:
            print(
                f"WARN: could not read _rename_map.json ({e}) — renamed tickers will show no financials"
            )
    # §197: a BSE-only ticker that is also a FORMER NSE ticker of another company (WORTH = Worth Investment on BSE,
    # WORTH -> WORTHPERI on NSE) is the BSE company on this site. The NSE alias stays true for the NSE namespace but
    # is never applied to it here: no fallback to the other company's rows, and no folding into its page as a former.
    try:
        collide = set(json.load(open(COLLIDE_J, encoding="utf-8")).get("collisions") or {})
    except Exception as e:
        sys.exit(
            f"ABORT: {os.path.basename(COLLIDE_J)} unreadable ({e}) — refusing to build slices that could alias a BSE ticker onto another "
            "company"
        )
    dropped = sorted(o for o in collide if o in aliases)
    aliases = {o: n for o, n in aliases.items() if o not in collide}
    print(
        "rename aliases: %d (%d BSE-ticker collisions not aliased: %s)"
        % (len(aliases), len(dropped), ", ".join(dropped))
    )

    # --- BSE-ONLY names: fold docs/bse_fundamentals.json (keyed by scripcode) into fund/revop so a
    #     fin slice is emitted for them too. build_bse_slices.py cuts their PRICE slice; without this
    #     their page shows a chart but "no quarterly earnings on file". Rev+PAT only (the BSE OCR route
    #     has no EBITDA/EPS); basis S|C routes pat into the std or con slot; ann is the announce date
    #     (0 → unknown). Never overwrites a symbol that already has NSE data, and skips any ticker whose
    #     slug clashes with an existing name (recycled tickers) so the collision guard never trips. ----
    bse_added, bse_filled = 0, 0
    if os.path.exists(BSEFUND_J) and os.path.exists(BSESCRIP_J):
        try:
            bfin = json.load(open(BSEFUND_J, encoding="utf-8")).get("px", {})
            bsj = json.load(open(BSESCRIP_J, encoding="utf-8"))
            code2sym = {str(v): k for k, v in bsj.get("by_id", {}).items()}
            code2isin = {str(v): k for k, v in bsj.get("by_isin", {}).items()}
            tape_isin = nse_tape_isin()  # NSE symbol -> ISIN (committed tape meta)
            sys.path.insert(0, HERE)
            import bse_resolve  # §203: whose page a ticker is, by ISIN

            bse_resolve.identities(tape_isin)
            not_this_page = {}  # ticker -> why a BSE scrip is kept off its page
            isin2nse = {}
            for s_, i_ in tape_isin.items():
                isin2nse.setdefault(i_, set()).add(s_)
            taken = {slug(s) for s in (set(fund) | set(revop) | set(shp_rows) | set(hist_rows))}
            # §180b: a BSE-only ticker now carries its OWN shareholding rows (shp_fill_allstocks ledger, keyed by the same
            # ticker and scrip code). Those rows claim its slug, which used to block the fundamentals fold below and would
            # have left the page with holdings but no results. Allow the fold when the slug is claimed by nothing except
            # this very ticker AND the ledger records this ticker for this scrip code.
            owners = {}
            for s_ in set(fund) | set(revop) | set(shp_rows) | set(hist_rows):
                owners.setdefault(slug(s_), set()).add(s_)
            bse_shp_keys = {}
            try:
                with gzip.open(
                    os.path.join(HERE, "shp_fill_allstocks.json.gz"), "rt", encoding="utf-8"
                ) as fh_:
                    bse_shp_keys = json.load(fh_).get("_bse_keys") or {}
            except Exception as e:
                print(
                    f"WARN: shp_fill_allstocks.json.gz unreadable ({e}) — BSE-only SHP keys not exempted"
                )
            for code, qmap in bfin.items():
                if not isinstance(qmap, dict):
                    continue
                isin = code2isin.get(str(code), "")
                targets = []
                sym = code2sym.get(str(code))
                # §203: the ticker string is also the NSE symbol of ANOTHER company whose page this is (ZEAL = Zeal
                # Global on NSE SME, BSE 539963 = Zeal Aqua). The tape ISIN check below never saw it: the committed
                # tape carries no SME symbol, so `ti` was None and the other company's quarters were folded in.
                why = bse_resolve.bse_blocked_under(sym, isin, code) if sym else None
                if why:
                    not_this_page[sym] = why
                    sym = None
                if sym:
                    ti = tape_isin.get(sym)
                    if sym in fund or sym in revop:
                        # §174: this used to SKIP the whole scrip, freezing 343 BSE-only pages at whatever an older
                        # campaign had written under the ticker (DHINDIA stopped at Mar-2026 though Jun-2026 was read,
                        # ABATEAS at Mar-2024). Now fill-only — but only when the ticker is provably this company: not
                        # an NSE tape key at all (a BSE-ticker key), or an NSE key whose ISIN issuer matches the scrip.
                        if ti is None or (isin and ti[:7] == isin[:7]):
                            targets.append(sym)
                    elif slug(sym) not in taken or (
                        bse_shp_keys.get(sym) == str(code) and owners.get(slug(sym), set()) <= {sym}
                    ):
                        targets.append(sym)  # brand-new BSE-only slice (the original behaviour)
                for s_ in sorted(
                    isin2nse.get(isin, ())
                ):  # the NSE listing of the same ISIN (a BSE->NSE migrant
                    if s_ not in targets:  # whose BSE quarters sit under its scripcode)
                        targets.append(s_)
                for tsym in targets:
                    fresh = tsym not in fund and tsym not in revop
                    have = {r[0] for r in fund.get(tsym, [])}
                    rvt = revop.setdefault(tsym, {})
                    frows = fund.setdefault(tsym, [])
                    added = 0
                    for qe, cell in qmap.items():
                        if not isinstance(cell, dict) or not qe.isdigit():
                            continue
                        pat, rev = cell.get("pat"), cell.get("rev")
                        ann = cell.get("ann") or None  # 0 → unknown announce date
                        con = cell.get("basis") == "C"
                        qei = int(qe)
                        if (
                            pat is not None and qei not in have
                        ):  # fund: [qEnd, npStd, annStd, npCon, annCon]
                            frows.append(
                                [qei, None, None, pat, ann] if con else [qei, pat, ann, None, None]
                            )
                            added += 1
                        # revop: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
                        cur = rvt.get(qe)
                        if cur is None:
                            rvt[qe] = (
                                [None, rev, None, None, None, pat, 0, None, None]
                                if con
                                else [rev, None, None, None, pat, None, 0, None, None]
                            )
                            added += 1
                        elif rev is not None and cur[0] is None and cur[1] is None:
                            cur = list(cur)
                            cur[1 if con else 0] = rev
                            rvt[qe] = cur  # revenue-only fill
                            added += 1
                    if not rvt:
                        del revop[tsym]
                    if frows:
                        frows.sort(key=lambda r: r[0])
                    else:
                        del fund[tsym]
                    if added:
                        taken.add(slug(tsym))
                        if fresh:
                            bse_added += 1
                        else:
                            bse_filled += 1
            print(
                "BSE fundamentals folded in: %d new symbols, %d existing symbols gap-filled (fill-only)"
                % (bse_added, bse_filled)
            )
            print(
                "BSE scrips kept off another company's page (§203): %d — %s"
                % (len(not_this_page), ", ".join(sorted(not_this_page)[:12]))
            )
        except Exception as e:
            print(
                f"WARN: could not fold bse_fundamentals.json ({e}) — BSE-only names get no fin slice"
            )

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

    # §176 FORMER SYMBOLS: resolve() above only falls back to another key when this symbol has NOTHING, so once a
    # renamed company files under its new ticker every quarter stored under the old one vanished from its page
    # (360ONE's 2019-20 detail sits under IIFLWAM, ABREL's under CENTURYTEX: 1,649 of 4,538 NSE point-in-time
    # detail gaps). Quarters of every former symbol that resolves (rename chain) to this one are now merged in
    # FILL-ONLY — own data always wins. Guard: a former key that filed ANY quarter this symbol also filed was a
    # concurrently listed company (merger partner, not a rename) and is never merged.
    # §220c: ... unless every shared quarter carries the SAME numbers — the same company's filing stored under both keys
    # (HEXT holds 23 of HEXAWARE's 2015-20 quarters, identical or rounded: 120.0 vs 119.63; CURAA 2 of CURATECH's), so
    # the old guard kept their other 57 / 11 quarters off the page. Two companies filing the same quarter disagree.
    def _chain(s0):
        seen_ = set()
        while s0 in aliases and s0 not in seen_ and aliases[s0] != s0:
            seen_.add(s0)
            s0 = aliases[s0]
        return s0

    formers = {}
    for old_ in aliases:
        new_ = _chain(old_)
        if new_ != old_:
            formers.setdefault(new_, []).append(old_)

    def fq(s0):
        return {r[0] for r in (fund.get(s0) or [])}

    def _agree(
        a, b
    ):  # one company's figure stored twice (or rounded to 1 decimal) — 1%, floor Rs 0.05 cr
        return abs(a - b) <= max(0.01 * max(abs(a), abs(b)), 0.05)

    def _same_filings(
        o, n
    ):  # every shared quarter that both keys valued on a common basis agrees (§220c)
        ro = {r[0]: r for r in (fund.get(o) or [])}
        rn = {r[0]: r for r in (fund.get(n) or [])}
        seen_any = False
        for q in set(ro) & set(rn):
            for i in (1, 3):
                a = ro[q][i] if len(ro[q]) > i else None
                b = rn[q][i] if len(rn[q]) > i else None
                if a is not None and b is not None:
                    seen_any = True
                    if not _agree(a, b):
                        return False
        return seen_any

    ok_formers = {}
    for new_, olds in formers.items():
        mine = fq(new_)
        ok_formers[new_] = sorted(o for o in olds if not (fq(o) & mine) or _same_filings(o, new_))

    def merged(src, sym, kind):
        base = resolve(src, sym)
        olds = [o for o in ok_formers.get(sym, ()) if src.get(o)]
        if not olds:
            return base
        if kind == "dict":
            out = dict(base or {})
            for o in olds:
                for q, v in src[o].items():
                    out.setdefault(q, v)
            return out or None
        rows = list(base or [])  # list of rows keyed by row[0] (fund / shp history)
        have_ = {r[0] for r in rows}
        for o in olds:
            for r in src[o]:
                if r[0] not in have_:
                    rows.append(r)
                    have_.add(r[0])
        rows.sort(key=lambda r: r[0])
        return rows or None

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)  # drop slices for symbols that left the feeds
    os.makedirs(out_dir, exist_ok=True)

    def same(a, b):
        return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-9)

    seen, written, total = {}, 0, 0
    pd_rows = pd_syms = pd_stale = pp_off = 0
    months = {}  # docs/fund_months.json for the backtest engines (§198)
    for sym in sorted(syms):
        sl = slug(sym)
        if sl in seen:
            sys.exit(f"ABORT: slug collision {sl!r}: {seen[sl]} and {sym}")
        seen[sl] = sym

        payload = {"sym": sym}
        f = merged(fund, sym, "list")
        if f:
            payload["fund"] = f
        r = merged(revop, sym, "dict")
        if r:
            payload["revop"] = r
        # row lengths (runbook §191): a mark is published only while the row still carries the revenue it was proven on
        # — a row another writer changed afterwards reads as a quarter again (its year goes blank, never wrong)
        pd, pp = {}, []
        fq = {str(x[0]): x for x in (f or [])}
        for qe, e in (resolve(rowp, sym) or {}).items():
            row = (r or {}).get(qe) or []
            if (
                row
                and same(row[0], e.get("s"))
                and same(row[1] if len(row) > 1 else None, e.get("c"))
            ):
                pd[qe] = e["m"]
                # §198: the row's PROFIT counts for that length only while every profit stored on it is the proven one
                fr = fq.get(qe) or [None] * 5
                if all(v is None or same(v, e.get(k)) for k, v in (("ps", fr[1]), ("pc", fr[3]))):
                    pp.append(qe)
                else:
                    pp_off += 1
            else:
                pd_stale += 1
        if pd:
            payload["pd"] = pd
            if pp:
                payload["pp"] = pp
            months[sym] = {qe: (m if qe in pp else -m) for qe, m in pd.items()}
            pd_rows += len(pd)
            pd_syms += 1
        row = resolve(shp_rows, sym)
        if row and row[4]:
            payload["shpQ"] = shp_q
            payload["shp"] = row[4]
        h = merged(hist_rows, sym, "list")
        if h:
            payload["shpH"] = h
        gv = merged(gov_rows, sym, "dict")
        if gv:
            payload["shpGov"] = gv  # {QE: gov%} — Screener's separate Government row
        xt = merged(xtra, sym, "dict")
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
        % (
            written,
            len(fund),
            len(revop),
            len(shp_rows),
            len(hist_rows),
            total / 1e6,
            total / max(written, 1) / 1024,
        )
    )
    print(
        "row periods (half-year / full-year rows, §191): %d rows on %d slices; %d marks dropped because the row's "
        "revenue changed since it was proven" % (pd_rows, pd_syms, pd_stale)
    )
    # §198: the backtest engines read sf_fundamentals, not the slices — give them the same marks in one small file.
    # m = the row's length when its profit is proven, -m when only its revenue is (its profit then counts toward nothing).
    doc = {
        "_note": "Result rows of proven length (runbook §191/§198) — built by scripts/build_stock_fin.py from "
        "scripts/row_periods.json; never edit by hand. {SYM: {qEnd: m}}: m = 3|6|12 months with the "
        "row's profit proven, -m = length proven on revenue only. Any other row of a year that holds a "
        "6/12-month row is of unknown length."
    }
    doc.update({s: months[s] for s in sorted(months)})
    blob = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    with open(months_path, "w", encoding="utf-8") as fh:
        fh.write(blob + "\n")
    print(
        "fund_months.json: %d symbols, %d rows (%d with profit not proven) -> %s"
        % (
            len(months),
            sum(len(v) for v in months.values()),
            pp_off,
            os.path.relpath(months_path, ROOT),
        )
    )


if __name__ == "__main__":
    main()

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
"""§108 PASS 2b — the DECISIVE structured test: NSE's archive keeps BOTH vintages of a quarter.

THE FIND (2026-08-24). NSE's `corporates-financial-results` list returns MORE THAN ONE ROW for the
same (period, basis) when a company re-filed that period — the original filing and, a year later,
the Ind-AS transition RESTATEMENT, each with its own `filingDate`, `indAs` flag and its own detail
page. Measured on the known §108 case:

    SYNGENE Dec-2015 std, row filed 29-Apr-2016, indAs="Non-Ind-AS" -> Net Profit 58.80 cr
    SYNGENE Dec-2015 std, row filed 27-Jan-2017, indAs="Ind-AS"     -> Net Profit 66.70 cr
                                                    ^ the value our store held, to the paisa

So the restated comparative — the thing §108 says only the year-later filing carries — is available
as STRUCTURED DATA, with its filing date attached. No PDF, no OCR, no vision rung (and this machine
has neither tesseract nor an approved vision budget: feedback-vision-reads-last-ask-first).

THE RULE: for one (period, basis), the AS-FILED vintage is the row with the EARLIEST filingDate.
Any later-filed row for the same period is a restatement. `indAs` usually labels the transition but
is not the discriminator — a restatement can happen within one accounting standard — the DATE is.

VERDICTS
  vintage-confirmed  stored == a LATER-filed vintage and != the earliest -> §108, proven
  store-as-filed     stored == the earliest-filed vintage                -> the store is right,
                                                                            the detres flag is
                                                                            something else
  stored-in-neither  stored matches no vintage NSE holds -> a bad read, not a vintage swap
  single-vintage     NSE holds only one filing of the period -> this test cannot speak
  no-nse-row / err   measured absence of the route, never a conclusion about the data

OUT: scripts/_vintage108_nse.json (resumable, keyed SYM|qe)
MODES
  (default)  the detres FLAGS only.
  --all      EVERY stored npStd cell in the FY16-FY17 window. This is the mode that closes the
             sweep's recall gap: detres has no row at all for a pre-listing or thinly-filed
             quarter (SYNGENE Jun-2015 — one of the four defective cells of the known case — is
             exactly that, so pass 1 could never have flagged it), and a restated value inside
             3% of the as-filed one never flags either. Detail pages are fetched only where the
             LIST already shows more than one filing of the period, or where detres could not
             speak, so the extra reach costs list requests, not 6,000 page reads.

RUN: python3 scripts/vintage108_nse_vintages.py [--all] [--limit N] [--only SYM,SYM]
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _nse_archive_revop as NA  # noqa: E402
import build_fundamentals as BF  # noqa: E402

SCAN = os.path.join(HERE, "_vintage108_scan.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
QS = (20150630, 20150930, 20151231, 20160331, 20160630, 20160930, 20161231, 20170331)
OUT = os.path.join(HERE, "_vintage108_nse.json")
OUT_CON = os.path.join(HERE, "_vintage108_nse_con.json")
DETAIL_CACHE = os.path.join(HERE, "_vintage108_nse_pages")
os.makedirs(DETAIL_CACHE, exist_ok=True)
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}
PAT_ROWS = (
    re.compile(r"net profit\s*/?\s*\(?loss\)?\s+after taxes,? minority", re.IGNORECASE),
    re.compile(r"net profit\s*/?\s*\(?loss\)?\s+for the period", re.IGNORECASE),
    re.compile(r"net profit\s*/?\s*\(?loss\)?\s+from ordinary activities after tax", re.IGNORECASE),
)
ABS_TOL, REL_TOL = 2.0, 0.03  # the same tolerance pass 1 flags on
# "the store IS this vintage" is a NEAREST-match question, not a fixed-epsilon one: our cells are
# stored at 2dp from feeds that round differently (ABFRL: as-filed -73.09, restated -67.88, stored
# -68.00 — unmistakably the restated one, 0.12 away, yet outside any epsilon tight enough to be
# meaningful). Assign the store to its NEAREST vintage, and only when that vintage is both close in
# absolute terms and decisively closer than the runner-up.
NEAR_ABS, NEAR_REL, MARGIN = 0.35, 0.005, 4.0


def dt(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", str(s or ""))
    return int(m.group(3)) * 10000 + MON[m.group(2)] * 100 + int(m.group(1)) if m else None


def qe_of(row):
    d = dt(row.get("toDate"))
    return d if d and d % 100 >= 28 else None


def pick_nonzero(rows, pats):
    """First matching row in preference order, treating an exact 0.0000 as UNFILLED.

    ★ THE FALSY SENTINEL. On a STANDALONE filing there is no minority interest, so filers leave
    "Net Profit after taxes, minority interest and share of profit of associates" blank — and NSE
    stores it as 0.0000, not as empty. Taking the first matching row therefore reports a profit of
    ZERO for a company that made 38.31 cr (GREAVESCOT Mar-2016: owners 0.0000, "for the period"
    0.0000, "from ordinary activities after tax" 38.31 = the stored value; DREDGECORP Sep-2016:
    owners 0.0000, "for the period" -14.37 = the stored value).

    Fall through to the next candidate when a row reads exactly 0 and a later one does not. When
    EVERY candidate is 0 the zero is kept — a dormant company really can earn nothing, and turning
    that into `None` would be a different lie.
    """
    hits = []
    for p in pats:
        for lab, v in rows:
            if p.search(lab.strip()):
                hits.append((lab.strip(), v))
                break
    for lab, v in hits:
        if v != 0:
            return v, lab
    return (hits[0][1], hits[0][0]) if hits else (None, None)


def lines_of(html):
    """PAT, operating profit and operating revenue for one vintage, all scaled to crore.

    Not just PAT: the §108 heal is a ROW heal. SYNGENE's opStd carried the restated figure
    alongside its npStd, sf_revop mirrors the PAT in slot 4 and holds op in slot 2, and the Ind-AS
    transition moved revenue itself (excise duty came INSIDE revenue). Reading all three from the
    same page costs nothing extra and keeps a second fetch pass off the table.
    """
    meta, rows = NA.parse_detail(html)
    out = {
        "unit": meta.get("unit"),
        "fmt": meta.get("fmt"),
        "basis": meta.get("Consolidated / Non-Consolidated"),
        "period": meta.get("Period Ended"),
    }
    pat, prow = pick_nonzero(rows, PAT_ROWS)
    out["pat"], out["pat_row"] = pat, (prow or "")[:70]
    out["op"], _ = pick_nonzero(rows, (NA.R_OP_IND, NA.R_OP_BANK))
    out["rev"], _ = pick_nonzero(rows, (NA.R_REV_IND, NA.R_REV_IND2, NA.R_REV_IND3, NA.R_REV_BANK, NA.R_REV_IND5))
    return out


def reparse():
    """Re-extract every vintage from the CACHED pages — no network at all.

    The pages were kept precisely so a reader fix could be applied to work already done
    (memory: feedback-persist-raw-rows-for-offline-rematch). Verdicts are recomputed after.
    """
    import glob

    idx = {}
    for f in glob.glob(os.path.join(DETAIL_CACHE, "*.html")):
        m = re.search(r"_(\d+)\.html$", f)
        if m:
            idx[m.group(1)] = f
    for path in (OUT, OUT_CON):
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        n = changed = nofile = 0
        for v in d.values():
            for x in v.get("vintages", []):
                seq = str(x.get("seq") or "")
                f = idx.get(seq)
                if not f:
                    nofile += 1
                    continue
                new = lines_of(open(f, encoding="utf-8", errors="replace").read())
                n += 1
                for fld in ("pat", "op", "rev"):
                    if new.get(fld) != x.get(fld):
                        changed += 1
                        x[fld] = new.get(fld)
                if new.get("pat_row"):
                    x["pat_row"] = new["pat_row"]
        json.dump(d, open(path, "w"), indent=1)
        print(
            "  %s: %d vintage rows re-parsed, %d field values changed, %d pages not cached"
            % (os.path.basename(path), n, changed, nofile)
        )


def verdict_of(got, stored):
    """Assign the store to a vintage. `got` is ordered EARLIEST-FILED FIRST.

    The earliest filing is the as-filed vintage and gets FIRST REFUSAL: when the store matches it,
    the cell is right no matter how many later re-filings also happen to match (an unchanged
    re-filing is the common case — AARTIIND filed Jun-2015 at 60.9 in 2015 and again at 60.9 in
    2016). An earlier version of this ranked by distance alone and called those ties
    "stored-in-neither", turning 60-odd clean cells into a fake adjudication queue.
    """
    first = got[0]
    out = {"as_filed": first["pat"], "restated": [x["pat"] for x in got[1:]]}

    def near(v):
        return abs(stored - v) <= max(NEAR_ABS, abs(v) * NEAR_REL)

    if near(first["pat"]):
        out["verdict"] = "single-vintage-matches-store" if len(got) == 1 else "store-as-filed"
        out["nearest"] = {"filed": first["filed"], "pat": first["pat"], "gap": round(abs(stored - first["pat"]), 4)}
        return out
    hits = [x for x in got[1:] if near(x["pat"])]
    if hits:
        best = min(hits, key=lambda x: abs(stored - x["pat"]))
        out["verdict"] = "vintage-confirmed"
        out["nearest"] = {
            "filed": best["filed"],
            "pat": best["pat"],
            "gap": round(abs(stored - best["pat"]), 4),
            "as_filed_gap": round(abs(stored - first["pat"]), 4),
        }
        return out
    out["verdict"] = "single-vintage-mismatch" if len(got) == 1 else "stored-in-neither"
    out["nearest"] = {"gap_to_as_filed": round(abs(stored - first["pat"]), 4)}
    return out


def reverdict():
    """Recompute every verdict from the PERSISTED vintage rows — no network. Rule changes
    re-adjudicate offline (memory: feedback-persist-raw-rows-for-offline-rematch)."""
    out = json.load(open(OUT, encoding="utf-8"))
    changed = 0
    for v in out.values():
        got = [x for x in v.get("vintages", []) if x.get("pat") is not None and x.get("cumulative") != "Cumulative"]
        if not got:
            continue
        before = v.get("verdict")
        v.update(verdict_of(got, v["stored"]))
        changed += before != v["verdict"]
    json.dump(out, open(OUT, "w"), indent=1)
    print("re-verdicted %d cells offline, %d changed" % (len(out), changed))
    from collections import Counter

    for kk, n in Counter(x.get("verdict") for x in out.values()).most_common():
        print("   %-30s %d" % (kk, n))


def main():
    args = sys.argv[1:]
    # CON basis. detres serves standalone only (§42), so the consolidated half of this class has
    # no detres route at all — NSE is the ONLY structured reader for it, and the anchor-refusal
    # ledger already shows 26 con refusals inside this window. Same test, slot 3 of the store and
    # NSE's "Consolidated" rows.
    global OUT, SLOT, BASIS_ROW
    con = "--con" in args
    if con:
        OUT = OUT_CON
    SLOT = 3 if con else 1
    BASIS_ROW = "Consolidated" if con else "Non-Consolidated"
    if "--reparse" in args:
        reparse()
        for tgt in ("std", "con"):
            globals()["OUT"] = OUT_CON if tgt == "con" else os.path.join(HERE, "_vintage108_nse.json")
            reverdict()
        return None
    if "--reverdict" in args:
        return reverdict()
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None

    NA.JAR = BF.nse_jar()
    scan = json.load(open(SCAN, encoding="utf-8"))["cells"] if os.path.exists(SCAN) else {}
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    # Transport failures are NOT results: drop them on load so a re-run retries them instead of
    # inheriting a "no rows" that was really a 403 (runbook 61a mode 4).
    for k in [k for k, v in out.items() if v.get("verdict") in ("list-failed", "no-readable-vintage")]:
        del out[k]
    # Entries written before this pass captured op/rev hold PAT only; redo them rather than let a
    # partial record pass for a complete one.
    for k in [k for k, v in out.items() if v.get("vintages") and not any("op" in x for x in v["vintages"])]:
        del out[k]
    print("basis: %s (store slot %d)" % (BASIS_ROW, SLOT))
    every = "--all" in args

    # The candidate set comes from the STORE, not from pass 1's ledger, so this route does not
    # inherit detres's reach: it runs to completion on its own and covers the cells detres has no
    # row for. detres, where pass 1 has reached it, is carried along as a cross-check.
    if every:
        fund = json.load(open(FUND, encoding="utf-8"))
        cand = {}
        for sym, rowset in fund.items():
            if only and sym not in only:
                continue
            for r in rowset:
                if r[0] in QS and len(r) > SLOT and r[SLOT] is not None:
                    cand["%s|%d" % (sym, r[0])] = {"sym": sym, "qe": r[0], "stored": r[SLOT], "state": "done"}
        if not con:
            for k, v in scan.items():
                if k in cand:
                    cand[k] = dict(v)
    else:
        cand = {k: v for k, v in scan.items() if v.get("verdict") == "FLAG"}
    if only:
        cand = {k: v for k, v in cand.items() if v["sym"] in only}

    # PRIORITY. Impact first, so the valuable half of a multi-hour scan is on disk early:
    #   1 detres FLAGs           — the biggest stored-vs-as-filed gaps;
    #   2 cells detres is BLIND to (no row / not a quarter / no NP line) — SYNGENE Jun-2015's
    #     class, where a defect can be any size because nothing else screens it;
    #   3 the rest — where a restatement, if any, is inside max(2 cr, 3%) by construction.
    def prio(k):
        v = cand[k].get("verdict")
        return (0 if v == "FLAG" else 1 if v not in ("match", None) else 2, k)

    targets = sorted((k for k, v in cand.items() if v.get("state") == "done" and k not in out), key=prio)[:limit]
    scan = cand
    print("cells to test: %d (ledger holds %d)%s" % (len(targets), len(out), "  [--all]" if every else ""))

    # The per-symbol LIST call is the bottleneck — measured ~15 s each (it is the cookie-gated
    # www.nseindia.com API, and it is fetched once per symbol plus once per rename alias), while
    # the static archive pages are fast. Prefetch the next symbols' lists in a small pool so that
    # latency overlaps the page reads instead of serialising in front of them.
    lists, n = {}, 0
    order = []
    for key in targets:
        symk = scan[key]["sym"]
        if symk not in order:
            order.append(symk)

    def get_list(symk):
        try:
            return NA.list_rows(symk)
        except Exception as ex:
            print(f"  ! {symk} list failed: {type(ex).__name__}")
            return None  # TRANSPORT failure — never "this company has no rows"

    pool = ThreadPoolExecutor(max_workers=3)
    pending = {}
    cursor = 0
    for _ in range(6):
        if cursor < len(order):
            pending[order[cursor]] = pool.submit(get_list, order[cursor])
            cursor += 1

    for key in targets:
        c = scan[key]
        sym, qe = c["sym"], c["qe"]
        if sym not in lists:
            if sym not in pending:
                pending[sym] = pool.submit(get_list, sym)
            lists[sym] = pending.pop(sym).result()
            while len(pending) < 6 and cursor < len(order):
                pending[order[cursor]] = pool.submit(get_list, order[cursor])
                cursor += 1
        if lists[sym] is None:
            out[key] = {"verdict": "list-failed", "sym": sym, "qe": qe, "stored": c["stored"]}
            n += 1
            continue
        rows = [
            r
            for r in lists[sym]
            if qe_of(r) == qe and (r.get("consolidated") or "") == BASIS_ROW and r.get("resultDetailedDataLink")
        ]
        # In --all mode a period NSE filed once, whose detres already matched the store, has
        # nothing this test can add — the list alone settles it, at no page-read cost.
        if every and len(rows) < 2 and c.get("verdict") == "match":
            out[key] = {
                "verdict": "single-vintage-list-only",
                "sym": sym,
                "qe": qe,
                "stored": c["stored"],
                "detres": c.get("detres"),
                "n_rows": len(rows),
            }
            n += 1
            continue
        if not rows:
            out[key] = {
                "verdict": "no-nse-row",
                "sym": sym,
                "qe": qe,
                "stored": c["stored"],
                "detres": c.get("detres"),
                "n_rows": 0,
            }
            n += 1
            continue
        # The detail pages are STATIC files on nsearchives (a CDN), not the cookie-gated,
        # rate-limited www.nseindia.com API the list comes from — so a small pool here is safe
        # and is the difference between a 6-hour scan and a 2-hour one. The list calls stay
        # strictly serial.
        ordered = sorted(rows, key=lambda x: (dt(x.get("filingDate")) or 0, x.get("seqNumber") or ""))

        def read(r):
            link = r["resultDetailedDataLink"]
            # CACHE the page: re-extracting a different row later must never mean re-fetching
            # 6,000 pages (memory: feedback-persist-raw-rows-for-offline-rematch).
            path = os.path.join(DETAIL_CACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link.rsplit("/", 1)[-1]))
            try:
                html = NA.get_detail(link, sym, path)
            except Exception as ex:
                return {"filed": dt(r.get("filingDate")), "err": type(ex).__name__}
            d = lines_of(html)
            d.update(
                filed=dt(r.get("filingDate")),
                indAs=r.get("indAs"),
                audited=r.get("audited"),
                cumulative=r.get("cumulative"),
                seq=r.get("seqNumber"),
            )
            return d

        with ThreadPoolExecutor(max_workers=4) as ex:
            vints = list(ex.map(read, ordered))
        got = [x for x in vints if x.get("pat") is not None and x.get("cumulative") != "Cumulative"]
        rec = {
            "sym": sym,
            "qe": qe,
            "stored": c["stored"],
            "detres": c.get("detres"),
            "n_rows": len(rows),
            "vintages": vints,
        }
        if not got:
            rec["verdict"] = "no-readable-vintage"
        else:
            rec.update(verdict_of(got, c["stored"]))
            af = rec.get("as_filed")
            rec["detres_matches_as_filed"] = (
                c.get("detres") is not None
                and af is not None
                and abs(c["detres"] - af) <= max(ABS_TOL, abs(af) * REL_TOL)
            )
        out[key] = rec
        n += 1
        print(
            "  %-22s %-20s stored %9.2f  as-filed %9s  later %s"
            % (key, rec["verdict"], c["stored"], rec.get("as_filed"), rec.get("restated"))
        )
        if n % 10 == 0:
            json.dump(out, open(OUT, "w"), indent=1)
    json.dump(out, open(OUT, "w"), indent=1)
    print("done: %d cells" % n)
    return None


if __name__ == "__main__":
    main()

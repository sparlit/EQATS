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
"""REVISION SWEEP — find every stored SHP cell superseded by a BSE-side revised filing.

The class (runbook §22h, found 2026-08-09): companies file, then REVISE; BSE's SHPQNewFormat row
gets a `revised_date_time` and its XbrlFile becomes the revised document, while NSE's master keeps
serving the ORIGINAL. Our NSE-driven pipeline can never see those. 35 stale documents were found by
re-checking cells the SITES had contested — this sweep asks the question nobody asked: how many
more are there among cells no site ever flagged?

Design (parameters measured by the coverage session, not guessed):
  * one quarter-list call per symbol covers EVERY quarter — the sweep is ~2,600 requests total;
  * 5 worker threads — their gap sweep did 1,649 full XBRL fetch+parses in 3 min at 5 threads with
    zero 429s, so the list-only pass lands in ~5 minutes;
  * per-scrip lists cached under _shp_bse_cache/q_<code>.json within a run (fresh each run).

DENOMINATOR IS LOGGED EXPLICITLY: symbols with no scripcode (the NSE-only §22e cohort and
delisted names) silently drop out of enumeration otherwise — and a sweep that quietly skips 104
symbols looks identical to one that checked them. That distinction is the §22h carve-out.

Output: a dry-run report of every stored cell whose BSE row carries a revision NEWER than our
stored submission date AND whose revised document parses to different values. Site corroboration
is attached from the Phase-4 sweep extractions where the quarter overlaps (no refetch).
Healing stays a separate, deliberate step through shp_cell_fix.json.

  python3 -X utf8 scripts/shp_revision_sweep.py --out sweep.jsonl [--threads 5] [--limit 0]

★ OUTPUT SHAPE IS A CONTRACT WITH A SECOND CONSUMER. refresh-shareholding.yml (Sunday-evening
step, added 4fe9e6e3) parses the --out file as JSONL — one record per verified revision, a
non-empty "diffs" meaning stale — and emits the ::warning:: summary from it. Its first version
assumed a dict with a "stale" key and would have thrown on every Sunday run INSIDE
continue-on-error: a guard that appears to run weekly and never reports. If this record shape
ever changes, update the workflow summariser in the same commit.
"""
import argparse
import collections
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_shareholding as F  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MON = {"March": "03-31", "June": "06-30", "September": "09-30", "December": "12-31"}
TOL = {"prom": 0.06, "fii": 0.06, "dii": 0.06, "mf": 0.06, "ins": 0.06}


def get(u, timeout=45):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.bseindia.com/"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def qlist(code, cachedir):
    p = os.path.join(cachedir, f"q_{code}.json")
    if os.path.exists(p):
        return json.load(open(p))
    try:
        rows = json.loads(
            get(f"https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode={code}&qtrid=0.00&QryType=0")
        ).get("Table", [])
    except Exception:
        rows = None
    if rows is not None:
        json.dump(rows, open(p, "w"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="symbols cap, 0 = all")
    ap.add_argument("--p4dir", default="", help="Phase-4 extraction dir for site corroboration")
    a = ap.parse_args()

    HIST = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))
    by = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    try:
        ov = json.load(open(os.path.join(HERE, "_shp_scripcode_override.json")))
        by = dict(by, **{k: v for k, v in ov.items() if not k.startswith("_")})
    except Exception:
        pass

    try:
        ADJ = json.load(open(os.path.join(HERE, "_shp_revision_adjudicated.json")))
        ADJ = {(sym, qe) for sym, qs in ADJ.items() if not sym.startswith("_") for qe in qs}
    except Exception:
        ADJ = set()

    syms = sorted(s for s in HIST if not s.startswith("_"))
    with_code = [s for s in syms if by.get(s)]
    no_code = [s for s in syms if not by.get(s)]
    print("DENOMINATOR — logged so a silent skip cannot pass as a check:")
    print("  symbols in store            : %d" % len(syms))
    print("  with a BSE scripcode        : %d  <- sweepable" % len(with_code))
    print("  WITHOUT (NSE-only §22e +    : %d  <- STRUCTURALLY UNCHECKABLE by this route" % len(no_code))
    print("    delisted-from-master)")
    if a.limit:
        with_code = with_code[: a.limit]

    cachedir = os.path.join(HERE, "_shp_bse_cache")
    os.makedirs(cachedir, exist_ok=True)

    lock = threading.Lock()
    stats = collections.Counter()
    flagged = []  # (sym, qe, row) — revision newer than our stored sub-date

    def scan(sym):
        code = by[sym]
        rows = qlist(code, cachedir)
        with lock:
            if rows is None:
                stats["list_failed"] += 1
                return
            stats["list_ok"] += 1
        held = HIST.get(sym, {})
        for r in rows or []:
            rev = (r.get("revised_date_time") or "")[:10]
            xf = (r.get("XbrlFile") or "").strip()
            if not rev or not xf:
                continue
            q = str(r.get("qtr") or "")
            qe = None
            for m, dd in MON.items():
                if q.startswith(m):
                    qe = f"{q.rsplit(maxsplit=1)[-1]}-{dd}"
            if not qe or qe not in held:
                continue
            sub = str(held[qe][5])
            if rev > sub:
                with lock:
                    if (sym, qe) in ADJ:
                        stats["adjudicated_skip"] += 1  # printed below; never re-flagged
                    else:
                        flagged.append((sym, qe, r))
                        stats["flagged"] += 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        list(ex.map(scan, with_code))
    print(
        "\nlist pass: %d ok, %d failed, %.1f min — %d cells flagged (revision newer than our sub-date)"
        % (stats["list_ok"], stats["list_failed"], (time.time() - t0) / 60, stats["flagged"])
    )
    if stats["adjudicated_skip"]:
        print(
            "  (+%d previously adjudicated cells skipped — see _shp_revision_adjudicated.json)"
            % stats["adjudicated_skip"]
        )

    # site corroboration index from the Phase-4 extractions (already on disk, no refetch)
    sites_idx = collections.defaultdict(dict)
    if a.p4dir:
        for site in ("screener", "stockedge", "tickertape"):
            fp = os.path.join(a.p4dir, site, f"{site}_p4.jsonl")
            if not os.path.exists(fp):
                continue
            for line in open(fp, encoding="utf-8"):
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                sites_idx[(e.get("sym"), e.get("asof"))][site] = e.get("rows")

    out, verify_stats = [], collections.Counter()

    def verify(item):
        sym, qe, r = item
        try:
            body = get("https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + r["XbrlFile"].strip(), timeout=60)
            if len(body) < 5000:
                raise RuntimeError("blocked/stub %d bytes" % len(body))
            cell = F.parse_shp(body.decode("utf-8", "ignore"), qe)
        except Exception:
            with lock:
                verify_stats["fetch_or_parse_failed"] += 1
            return
        stored = HIST[sym][qe]
        if not isinstance(cell, dict):
            with lock:
                verify_stats["revised_doc_refused"] += 1
            return
        diffs = {}
        for i, fld in enumerate(("prom", "fii", "dii", "mf", "ins")):
            sv, bv = stored[i], cell.get(fld)
            if sv is None or bv is None:
                continue
            if abs(float(bv) - float(sv)) > TOL[fld]:
                diffs[fld] = [sv, bv]
        n_s = stored[6] if len(stored) > 6 else None
        if n_s and cell.get("nsh") and abs(cell["nsh"] - n_s) > max(500, 0.01 * n_s):
            diffs["nsh"] = [n_s, cell["nsh"]]
        rec = {
            "sym": sym,
            "qe": qe,
            "revised": (r.get("revised_date_time") or "")[:19],
            "stored_sub": stored[5],
            "xbrl": r["XbrlFile"].strip(),
            "diffs": diffs,
            "revised_cell": cell,
            "sites": sites_idx.get((sym, qe)) or None,
        }
        with lock:
            verify_stats["match_after_revision" if not diffs else "STALE_STORED"] += 1
            out.append(rec)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        list(ex.map(verify, flagged))
    print("verify pass: %.1f min" % ((time.time() - t0) / 60))
    for k, v in verify_stats.most_common():
        print("  %-24s %4d" % (k, v))

    with open(a.out, "w", encoding="utf-8") as f:
        f.writelines(
            json.dumps(rec, separators=(",", ":")) + "\n"
            for rec in sorted(out, key=lambda r: (not r["diffs"], r["sym"], r["qe"]))
        )
    stale = [r for r in out if r["diffs"]]
    print("\n%d records -> %s" % (len(out), a.out))
    if stale:
        print("STALE STORED CELLS (%d) — our value predates the revision AND differs:" % len(stale))
        for r in stale[:20]:
            corro = ",".join(r["sites"].keys()) if r.get("sites") else "-"
            print("   %-12s %s  rev=%s  %s  sites:%s" % (r["sym"], r["qe"], r["revised"][:10], r["diffs"], corro))
    print("\nDRY RUN — healing is a separate step through shp_cell_fix.json.")


if __name__ == "__main__":
    main()

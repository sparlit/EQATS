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
"""§108 RESTATED-COMPARATIVE VINTAGE SWEEP — detres (as-filed) vs stored npStd, FY16-FY17.

WHY. Runbook §108: a stored quarter can hold the LATER-vintage Ind-AS RESTATED figure (published
as a comparative in the NEXT fiscal year's filings) while its ann date claims the original filing
date. Every value is "real", so no scale gate, FY-identity or aggregator comparison that mixes
vintages can see it. SYNGENE's whole FY16 row was that; the class is open for every other
transition-era company whose 2015-17 cells came from aggregator scrapes or comparative-column reads.

WHAT THIS DOES. For every stored npStd cell with qe in 20150630..20170331, fetch the BSE
detailed-results JSON (§42 — AS-ORIGINALLY-FILED by construction, Rs MILLION -> /10) and flag
|detres - stored| > max(2 cr, 3%).

GATES / DISCIPLINE
  * Date Begin/End must span 3 months and END on the target quarter (§42: the same id space also
    holds annual and H1 rows).
  * Scrip codes come through bse_resolve (ISIN-guarded, §76) — a scrip_id equal to our ticker is a
    coincidence to be disproved. Unresolvable symbols are RECORDED as a measured gap, never dropped.
  * A 162-byte body is BSE's rate-limit stub (§0) and every network failure is TRANSIENT: retried
    with backoff, and left `pending` (never `done`) if it still fails, so a re-run picks it up.
  * Raw field dicts are persisted so any rule tweak re-matches OFFLINE without re-fetching.
  * SERIES-REPRODUCTION identity check (post-pass, in the report): if EVERY compared quarter of a
    symbol mismatches, that is a mapping suspect, not a vintage finding.

LEDGERS (resumable):
    scripts/_vintage108_scan.json  — per-cell verdicts + progress
    scripts/_vintage108_raw.json   — raw detres rows, for offline re-adjudication

RUN:  python3 scripts/vintage108_sweep.py [--limit N] [--only SYM,SYM] [--sleep 2.0]
      Read-only against the data files; it writes only its own two ledgers.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import bse_resolve  # noqa: E402

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SCAN = os.path.join(HERE, "_vintage108_scan.json")
RAW = os.path.join(HERE, "_vintage108_raw.json")

API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd=%s&qtr=%s"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

QS = [20150630, 20150930, 20151231, 20160331, 20160630, 20160930, 20161231, 20170331]
ABS_TOL, REL_TOL = 2.0, 0.03  # flag when |detres - stored| > max(2 cr, 3%)

NP_NAMES = (
    "Net Profit",
    "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax",
    "Net Profit (+)/ Loss (-) from Ordinary Activities after Ta",
    "Net Profit/(Loss) for the period",
)

# Delisted/merged symbols absent from the ACTIVE-equity scrape. Both maps carry an ISIN identity
# gate in their own files (bse_scrips_delisted.json `_identity_gate`, overrides `gate`).
EXTRA_SCRIP_FILES = [
    (os.path.join(HERE, "bse_scrips_delisted.json"), "scrips", "bse_code"),
    (os.path.join(HERE, "fill2020_tools", "_delisted_scrip_overrides.json"), None, "scrip"),
    # This sweep's own ISIN-gated resolution of the survivorship gap — 134 delisted/renamed
    # symbols the ACTIVE-equity scrape cannot carry (vintage108_resolve_extra.py).
    (os.path.join(HERE, "_vintage108_scrips_extra.json"), "resolved", "scrip"),
]
SCRIP_OVERRIDE = {"ADVANTA": "532840", "DISHMAN": "532526", "CAPF": "532938"}  # §52b, ISIN-gated


def qid(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return "%d.00" % (85 + (y - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m])


def parse_dt(s):
    try:
        d, mo, y = (s or "").split("-")
        return (2000 + int(y)) * 10000 + MONTHS[mo] * 100 + int(d)
    except Exception:
        return None


def fnum(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v), n
            except ValueError:
                pass
    return None, None


def scrip_map():
    m = dict(bse_resolve.by_id())  # ISIN-conflicting symbols already removed
    for path, key, field in EXTRA_SCRIP_FILES:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        d = d.get(key) if key else d
        for sym, e in (d or {}).items():
            if sym.startswith("_") or not isinstance(e, dict):
                continue
            code = e.get(field)
            if code and sym not in m:
                m[sym] = code
    for sym, code in SCRIP_OVERRIDE.items():
        m.setdefault(sym, code)
    for sym in list(m):
        if bse_resolve.blocked(sym):
            del m[sym]
    return {k: str(v) for k, v in m.items()}


def fetch(scrip, q, tries=4):
    """Returns (fields_dict, note). Raises RuntimeError only after every retry is spent."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                API % (scrip, q), headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
            if len(raw) <= 200:  # §0: the 162-byte body is the rate-limit stub
                last = "stub-%db" % len(raw)
                time.sleep(8 * (i + 1))
                continue
            js = json.loads(raw.decode("utf-8", "replace"))
            out = {}
            for row in js.get("table1") or []:
                out.setdefault((row.get("fld_desc") or "").strip(), row.get("Value"))
            return out, "ok"
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as ex:
            last = f"{type(ex).__name__}:{str(ex)[:60]}"
            time.sleep(6 * (i + 1))
    raise RuntimeError(last or "unknown")


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    # --cells SYM|QE,... : fetch exactly these, ahead of everything else. The full sweep is the
    # §108 recipe and keeps running for completeness, but the HEAL only needs detres as a second
    # reader on the cells NSE has already confirmed, and those are a few hundred, not 5,472.
    cells_only = None
    if "--cells" in args:
        cells_only = {x.strip() for x in args[args.index("--cells") + 1].split(",") if x.strip()}
    if "--cells-file" in args:
        cells_only = set(json.load(open(args[args.index("--cells-file") + 1], encoding="utf-8")))
    sleep = float(args[args.index("--sleep") + 1]) if "--sleep" in args else 2.0

    fund = json.load(open(FUND, encoding="utf-8"))
    codes = scrip_map()

    scan = load(SCAN, {})
    scan.setdefault(
        "_doc",
        "runbook 108 restated-comparative vintage sweep: detres (as-filed) vs "
        "stored npStd for FY16-FY17. Resumable; cells keyed SYM|qe.",
    )
    scan.setdefault(
        "params",
        {
            "window": QS,
            "abs_tol_cr": ABS_TOL,
            "rel_tol": REL_TOL,
            "source": "BSE Corp_detailedResult_Transpose_ng (runbook 42)",
        },
    )
    scan.setdefault("cells", {})
    if not (only or cells_only):
        scan["no_scrip"] = {}  # re-derived on a FULL run: a symbol resolved since last time
        # must not stay recorded as an unmeasured gap. A targeted run
        # sees only part of the universe and must not rewrite it.
    scan.setdefault("no_scrip", {})
    raw = load(RAW, {})

    todo = []
    for sym in sorted(fund):
        if only and sym not in only:
            continue
        stored = {r[0]: r[1] for r in fund[sym] if r[0] in QS and len(r) > 1 and r[1] is not None}
        if not stored:
            continue
        code = codes.get(sym)
        if not code:
            scan["no_scrip"][sym] = {
                "cells": len(stored),
                "reason": bse_resolve.blocked(sym) or "absent from ISIN-guarded map",
            }
            continue
        for qe in sorted(stored):
            k = "%s|%d" % (sym, qe)
            if cells_only is not None and k not in cells_only:
                continue
            if scan["cells"].get(k, {}).get("state") == "done":
                continue
            todo.append((sym, code, qe, stored[qe], k))

    print(
        "candidates pending: %d  (ledger holds %d done)  no-scrip syms: %d"
        % (len(todo), sum(1 for v in scan["cells"].values() if v.get("state") == "done"), len(scan["no_scrip"]))
    )
    todo = todo[:limit]
    if not todo:
        save(SCAN, scan)
        return

    t0, n_flag, n_err = time.time(), 0, 0
    last = 0.0
    for i, (sym, code, qe, st, k) in enumerate(todo, 1):
        # PACING: one request per `sleep` seconds measured start-to-start, so a slow response
        # does not stack on top of the throttle (and a fast one does not undercut it).
        wait = sleep - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.time()
        try:
            f, _ = fetch(code, qid(qe))
        except RuntimeError as ex:
            scan["cells"][k] = {"state": "pending", "err": str(ex)}
            n_err += 1
            print("  PENDING %-12s %d  %s" % (sym, qe, ex))
            if n_err >= 12:
                print("  ! 12 unrecovered fetches — stopping so a human looks (runbook 0)")
                break
            continue

        rec = {"state": "done", "sym": sym, "qe": qe, "scrip": code, "stored": st}
        if not f:
            rec["verdict"] = "empty"
        else:
            raw[k] = f
            b, e = parse_dt(f.get("Date Begin")), parse_dt(f.get("Date End"))
            np_mn, np_field = fnum(f, *NP_NAMES)
            rec["dbeg"], rec["dend"] = b, e
            if b is None or e is None:
                rec["verdict"] = "no-dates"
            elif e != qe:
                rec["verdict"] = f"dateend={e}"
            elif (e // 10000 * 12 + (e // 100) % 100) - (b // 10000 * 12 + (b // 100) % 100) != 2:
                rec["verdict"] = "span-not-quarter"
            elif np_mn is None:
                rec["verdict"] = "no-np-row"
            else:
                cr = round(np_mn / 10.0, 4)
                rec["detres"] = cr
                rec["np_field"] = np_field
                rec["diff"] = round(cr - st, 4)
                rec["verdict"] = "FLAG" if abs(cr - st) > max(ABS_TOL, abs(st) * REL_TOL) else "match"
                if rec["verdict"] == "FLAG":
                    n_flag += 1
                    print("  FLAG %-12s %d  stored %10.2f  detres %10.2f  d=%+.2f" % (sym, qe, st, cr, cr - st))
        scan["cells"][k] = rec

        if i % 20 == 0 or i == len(todo):
            save(SCAN, scan)
            save(RAW, raw)
            el = time.time() - t0
            print(
                "  .. %d/%d  flags %d  pending %d  %.0fs  (eta %.0f min)"
                % (i, len(todo), n_flag, n_err, el, (el / i) * (len(todo) - i) / 60)
            )

    save(SCAN, scan)
    save(RAW, raw)
    print("batch done: %d fetched, %d flags, %d pending" % (len(todo), n_flag, n_err))


if __name__ == "__main__":
    main()

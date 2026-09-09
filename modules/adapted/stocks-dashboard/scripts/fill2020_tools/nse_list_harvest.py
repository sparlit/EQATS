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
"""FILL-2020 rev track: harvest NSE's quarterly filing INDEX for every target company.

`https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=X&period=Quarterly`
returns EVERY quarterly result the company ever filed with NSE, one row per (quarter, basis), each
carrying `consolidated` ("Consolidated" / "Non-Consolidated") and — for ~2018+ filings — an `xbrl`
URL to the filed XBRL instance. Pre-2018 rows instead carry `resultDetailedDataLink` (the archive
HTML that scripts/_nse_archive_revop.py reads).

Two things this index gives the campaign that nothing else does:
  1. the XBRL for a quarter our cache simply never held -> a real fetch route (nse_xbrl_rev.py);
  2. NEGATIVE evidence: a company with 79 filings and ZERO consolidated rows (CUB) demonstrably
     never filed a consolidated quarterly result, which is what makes the con=std identity a
     documented fact rather than an inference from our own (possibly derived) PAT cells.

Symbols are chased through the rename chain the same way _nse_archive_revop.aliases() does it —
NSE keys the archive by the symbol that traded THEN (GMRAIRPORT's 2018 rows live under GMRINFRA).

Cache: scripts/_nselist/<SYM>.json (gitignored; re-runs are free and skip fetched symbols).
Run:   python -X utf8 scripts/fill2020_tools/nse_list_harvest.py [--only SYM,SYM] [--refresh]
"""
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import build_fundamentals as BF  # noqa: E402  (nse_jar / _get / UA)

CACHE = os.path.join(SCRIPTS, "_nselist")
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
H = {"User-Agent": BF.UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}


def iso_qe(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    if not m or m.group(2).title() not in MON:
        return None
    return int(m.group(3)) * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))


def aliases(sym):
    """Era symbols for `sym` (transitive, oldest last) — copied from _nse_archive_revop.py."""
    edges = {}
    try:
        for old, new in json.load(open(os.path.join(SCRIPTS, "_rename_map.json"))).items():
            edges.setdefault(new.upper(), set()).add(old.upper())
    except Exception:
        pass
    try:
        import csv as _csv

        with open(os.path.join(SCRIPTS, "symchg.csv"), encoding="utf8", errors="replace") as fh:
            for row in _csv.reader(fh):
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


def cache_path(sym):
    return os.path.join(CACHE, re.sub(r"[^A-Z0-9]", "_", sym.upper()) + ".json")


def fetch_list(sym, jar):
    """Rows for sym AND every era symbol, merged. Raises only if EVERY variant failed."""
    rows, errs = [], []
    for s in [sym, *aliases(sym)]:
        url = (
            "https://www.nseindia.com/api/corporates-financial-results"
            "?index=equities&symbol={}&period=Quarterly".format(urllib.parse.quote(s, safe=""))
        )
        got = None
        for _ in (1, 2):
            try:
                raw = BF._get(url, headers=H, jar=jar)
                got = json.loads(raw if isinstance(raw, str) else raw.decode("utf8", "replace"))
                break
            except Exception as e:
                errs.append(f"{s}:{type(e).__name__}")
                time.sleep(1.5)
        if isinstance(got, list):
            for r in got:
                r["_era"] = s
            rows.extend(got)
        time.sleep(0.4)
    # The classic index stops at Dec-2024: SEBI's integrated-filing regime replaced it, and 2025+
    # results live only under /api/integrated-filing-results (rows carry qe_Date + the same
    # per-basis xbrl). Normalize those into the classic row shape so every consumer of this cache
    # (con_nofile_identity's E-gates, nse_xbrl_rev) sees one continuous filing record.
    for s in [sym, *aliases(sym)]:
        url = "https://www.nseindia.com/api/integrated-filing-results?index=equities&period=Quarterly&symbol={}".format(
            urllib.parse.quote(s, safe="")
        )
        got = None
        for _ in (1, 2):
            try:
                raw = BF._get(url, headers=H, jar=jar)
                jb = json.loads(raw if isinstance(raw, str) else raw.decode("utf8", "replace"))
                got = jb.get("data", jb if isinstance(jb, list) else [])
                break
            except Exception as e:
                errs.append(f"{s}:intg:{type(e).__name__}")
                time.sleep(1.5)
        for r in got or []:
            basis = r.get("consolidated")
            qd = (r.get("qe_Date") or "").strip()
            m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})$", qd.title())
            if basis not in ("Consolidated", "Standalone") or not m:
                continue  # governance / non-financial integrated rows
            rows.append(
                {
                    "_era": s,
                    "_integrated": True,
                    "symbol": r.get("symbol"),
                    "toDate": m.group(0),
                    "consolidated": "Consolidated" if basis == "Consolidated" else "Non-Consolidated",
                    "audited": r.get("audited"),
                    "xbrl": r.get("xbrl"),
                    "pdf_attach": r.get("pdf_attach"),
                    "ixbrl": r.get("ixbrl"),
                    "filingDate": r.get("creation_Date"),
                    "relatingTo": None,
                    "period": "Quarterly",
                }
            )
        time.sleep(0.4)
    if not rows and errs:
        raise RuntimeError(",".join(errs[:4]))
    return rows


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    refresh = "--refresh" in argv
    os.makedirs(CACHE, exist_ok=True)
    syms = sorted(json.load(open(TARGETS)))
    if only:
        syms = [s for s in syms if s in only]
    jar = BF.nse_jar()
    got = miss = cached = 0
    for i, sym in enumerate(syms, 1):
        p = cache_path(sym)
        if os.path.exists(p) and not refresh:
            cached += 1
            continue
        try:
            rows = fetch_list(sym, jar)
        except Exception as e:
            print("  %-14s LIST FAIL %s" % (sym, e), flush=True)
            miss += 1
            continue
        json.dump(rows, open(p, "w", encoding="utf8"))
        ncon = sum(1 for r in rows if r.get("consolidated") == "Consolidated")
        nxb = sum(1 for r in rows if r.get("xbrl"))
        got += 1
        print("  %-14s %4d rows (%d con, %d xbrl)" % (sym, len(rows), ncon, nxb), flush=True)
        if i % 25 == 0:
            jar = BF.nse_jar()  # refresh the cookie jar periodically
    print("\nharvested %d, cached %d, failed %d (of %d)" % (got, cached, miss, len(syms)))


if __name__ == "__main__":
    main()

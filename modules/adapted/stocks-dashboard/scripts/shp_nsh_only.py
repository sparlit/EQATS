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
"""Extract ONLY the shareholder count from filings whose percentage parse is refused.

Why this exists: `parse_shp` reads NumberOfShareholders off the whole-company
(ShareholdingPatternMember) context correctly — and then throws it away, because it returns None
whenever the FII/DII percentage gates fail. The count and the percentages are bundled into one
all-or-nothing result. For ~600 cells (micro-caps, mostly 2025-2026) the percentages are
unanchorable but the count sits right there, properly tagged. 21STCENMGM Sep-2025 is the worked
example: parse_shp -> None, while the XBRL carries ShareholdingPatternMember = 8,266.

This reads the count and NOTHING else, so a refused percentage parse can never leak into our data:
  * ShareholdingPatternMember context ONLY — the same context parse_shp uses. Category contexts
    carry per-bucket counts (a filing showing "6 promoters" is not a company with 6 shareholders),
    and typedMember contexts are the named >1% holders. Reading either would be catastrophic, so
    both are excluded explicitly rather than by ordering luck.
  * emits a ledger, never touches shp_history — the fill goes through _shp_merge_nsh.py, which
    fills slot 6 only and refuses any cell whose percentages differ.

  python3 -X utf8 scripts/shp_nsh_only.py --quarters 2025-09-30,2025-12-31 --symbols A,B,C \
      --out scripts/shp_fill_nsh_refused.json.gz
"""
import argparse
import collections
import gzip
import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_shareholding as F  # noqa: E402

sys.path.insert(0, "/Users/dhruvan/stocks-dashboard/scripts")
import contextlib

import build_fundamentals as B  # noqa: E402


def nsh_of(xml_text):
    """Whole-company shareholder count, or None. Category/typed contexts are never used."""
    root = ET.fromstring(xml_text)

    def strip(t):
        return t.split("}", 1)[-1]

    whole = set()
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        mems, typed = [], False
        for m in c.iter():
            st = strip(m.tag)
            if st == "explicitMember":
                mems.append((m.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                typed = True
        if not typed and len(mems) == 1 and mems[0] == "ShareholdingPatternMember":
            whole.add(c.get("id"))
    if not whole:
        return None
    vals = set()
    for f in root.iter():
        if strip(f.tag) != "NumberOfShareholders":
            continue
        if f.get("contextRef") in whole:
            with contextlib.suppress(TypeError, ValueError):
                vals.add(int(float(str(f.text).strip())))
    if len(vals) != 1:  # 0 = absent; >1 = ambiguous, refuse rather than pick
        return None
    v = vals.pop()
    return v if v > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarters", required=True)
    ap.add_argument("--symbols", default="", help="restrict to these (default: all in the quarter)")
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    only = {s.strip().upper() for s in a.symbols.split(",") if s.strip()} or None
    jar = B.nse_jar()
    counts, tally = collections.defaultdict(dict), collections.Counter()

    for qe in [q.strip() for q in a.quarters.split(",") if q.strip()]:
        rows = F.fetch_master(jar, qe)
        best = {}
        for r in rows:
            sym = str(r.get("symbol") or "").strip().upper()
            xb = str(r.get("xbrl") or "").strip()
            sub = F.iso_date(r.get("submissionDate")) or F.iso_date(r.get("broadcastDate"))
            if not sym or not xb.lower().startswith("http") or not sub:
                continue
            if only and sym not in only:
                continue
            if sym not in best or sub > best[sym][0]:  # newest submission wins
                best[sym] = (sub, xb)
        done = 0
        for sym, (sub, xb) in sorted(best.items()):
            if a.limit and done >= a.limit:
                break
            done += 1
            try:
                txt = F.fetch_xbrl(xb, jar)
            except Exception:
                tally["fetch_error"] += 1
                continue
            full = F.parse_shp(txt, qe)
            n = nsh_of(txt)
            if isinstance(full, dict):
                tally["parse_ok_already"] += 1  # normal pipeline handles these
                continue
            if n is None:
                tally["no_count"] += 1
                continue
            counts[sym][qe] = n
            tally["RECOVERED"] += 1
        print("%s: %d symbols examined" % (qe, done), flush=True)

    for k, v in tally.most_common():
        print("  %-18s %5d" % (k, v))
    cells = sum(len(v) for v in counts.values())
    print("recovered %d counts across %d symbols" % (cells, len(counts)))
    for sym in list(counts)[:8]:
        print("   %-12s %s" % (sym, counts[sym]))
    if a.out and cells:
        doc = {
            "_meta": {
                "source": "NSE SHP XBRL, ShareholdingPatternMember context only",
                "note": "filings whose percentage parse parse_shp refuses; count only",
                "cells": cells,
            },
            "counts": dict(counts.items()),
        }
        blob = json.dumps(doc, separators=(",", ":")).encode()
        (gzip.open(a.out, "wb") if a.out.endswith(".gz") else open(a.out, "wb")).write(blob)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()

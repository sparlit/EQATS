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
"""Compute the attributable-to-owners switch from the LOCAL XBRL cache (no network). PRECISE tag
matching (exact tag via \b, value anchored before </, OneD = current quarter) + a garbage guard
(owners must be within reason of total PAT). Collects owners' share for every CONSOLIDATED quarter
and reports where it differs from the live npCon (total PAT).

DRY-RUN: writes _reattr_owners.json + _reattr_changes.json + a summary. Does NOT modify live data.
Run: python -X utf8 apply_reattr_cache.py
"""
import contextlib
import glob
import json
import os
import re

import build_fundamentals as B

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
live = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))

RX_SYM = re.compile(r"<[a-z\-]+:Symbol\b[^>]*>\s*([A-Z][A-Z0-9&\-]{1,14})\s*</")
RX_NAT = re.compile(r"<[a-z\-]+:NatureOfReportStandaloneConsolidated\b[^>]*>\s*([^<]+?)\s*</")
RX_QE = re.compile(r"<[a-z\-]+:DateOfEndOfReportingPeriod\b[^>]*>\s*(\d{4})-(\d{2})-(\d{2})")
RX_TOT = re.compile(r'<[a-z\-]+:ProfitLossFor(?:The)?Period\b[^>]*contextRef="OneD"[^>]*>\s*([-0-9.eE+]+)\s*</')
RX_ATTR = re.compile(
    r'<[a-z\-]+:ProfitOrLossAttributableToOwnersOfParent\b[^>]*contextRef="OneD"[^>]*>\s*([-0-9.eE+]+)\s*</'
)
RX_NCI = re.compile(
    r'<[a-z\-]+:ProfitOrLossAttributableToNonControllingInterests\b[^>]*contextRef="OneD"[^>]*>\s*([-0-9.eE+]+)\s*</'
)


def main():
    files = [f for f in glob.glob(os.path.join(B.CACHE, "*")) if os.path.isfile(f)]
    print("cache files: %d" % len(files), flush=True)
    best = {}
    con = 0
    rejected = 0
    for i, f in enumerate(files):
        if i % 20000 == 0:
            print("  ...%d/%d, con-with-owners=%d rejected=%d" % (i, len(files), con, rejected), flush=True)
        try:
            xml = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        nat = RX_NAT.search(xml)
        if not nat or "consol" not in nat.group(1).lower():
            continue
        sm = RX_SYM.search(xml)
        qm = RX_QE.search(xml)
        am = RX_ATTR.search(xml)
        tm = RX_TOT.search(xml)
        if not (sm and qm and am and tm):
            continue
        try:
            attr = float(am.group(1)) / 1e7
            total = float(tm.group(1)) / 1e7
        except Exception:
            continue
        ncm = RX_NCI.search(xml)
        nci = 0.0
        if ncm:
            with contextlib.suppress(Exception):
                nci = float(ncm.group(1)) / 1e7
        # ONLY trust the split when owners + minority reconciles to total PAT — rejects filers that
        # tag owners=0 (artifact, no minority) and any mis-parse. Such quarters keep total PAT.
        if abs((attr + nci) - total) > max(1.0, abs(total) * 0.02):
            rejected += 1
            continue
        qe = int(qm.group(1) + qm.group(2) + qm.group(3))
        best[(sm.group(1), qe)] = round(attr, 2)
        con += 1
    print("consolidated quarters with a clean owners' figure: %d  (rejected %d)" % (len(best), rejected), flush=True)
    changed = []
    for sym, arr in live.items():
        for row in arr:
            a = best.get((sym, row[0]))
            if a is not None and row[3] is not None and abs(a - row[3]) > 0.5:
                changed.append([sym, row[0], row[3], a, round(row[3] - a, 2)])
    json.dump(
        {"%s|%d" % (k[0], k[1]): v for k, v in best.items()}, open(os.path.join(HERE, "_reattr_owners.json"), "w")
    )
    json.dump(changed, open(os.path.join(HERE, "_reattr_changes.json"), "w"))
    changed.sort(key=lambda c: abs(c[4]), reverse=True)
    recent = [c for c in changed if c[1] >= 20250101]
    print("\n=== IMPACT (dry-run) ===")
    print(
        "con quarters changing: %d  across %d stocks  (2025+: %d quarters, %d stocks)"
        % (len(changed), len({c[0] for c in changed}), len(recent), len({c[0] for c in recent}))
    )
    # validation against known-good examples
    bm = {"%s|%d" % (k[0], k[1]): v for k, v in best.items()}
    print("\nVALIDATION (should match Trendlyne examples):")
    for k, exp in [("REDINGTON|20250331", 665.62), ("ADANIPOWER|20260331", 4017.1), ("VEDL|20260331", 6698.0)]:
        print("  %-22s owners=%s  (expected ~%s)" % (k, bm.get(k), exp))
    print("\nTop 25 changes by minority size (sym, qe, total -> owners):")
    for c in changed[:25]:
        print("  %-12s %d  %9.1f -> %9.1f   minority %8.1f" % (c[0], c[1], c[2], c[3], c[4]))


if __name__ == "__main__":
    main()

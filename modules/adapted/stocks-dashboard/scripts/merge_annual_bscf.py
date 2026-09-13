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
"""Land a Claude reader's annual BS/CF reads into scripts/annual_bscf.json, GATE-ENFORCED.

The no-key vision loop is: fetch_annual_bscf.py --prep renders each vision-needed filer's
balance-sheet + cash-flow pages and writes a manifest -> a Claude routine READS the PNGs with
native vision (no API key, the repo's proven pattern) and writes back the numbers per manifest
entry -> this script lands them.

The holdout gate is enforced HERE, not on trust: each symbol's manifest carries a 'validate'
entry for a year we DO hold from XBRL, with that year's XBRL 'key' (Total Assets + PP&E). A
symbol's FILL years are landed ONLY if the reader's numbers for the validate year match the key
to <=1%. A symbol whose read is wrong (or whose reader hallucinated) fails and lands NOTHING.

Input (arg1): the reader's output — a JSON list of the manifest entries with the read fields added:
  [{"sym","fy","role":"validate"|"fill","basis":"c|s","key":{...}(validate only),
    "assets","sc","oeq","borr","blt","bst","ppe","cwip","gw","intg","invst","rec","pay","invnt",
    "cfo","cfi","cff","capex","cf_tax"}]   — ₹ crore, null a field the statement doesn't print.
Run: python -X utf8 scripts/merge_annual_bscf.py <reader_output.json>
"""
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "annual_bscf.json")
FIELDS = {
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


def asat_ok(e):
    """A fill's balance sheet must be the FISCAL-YEAR-END audited statement, not an interim or
    off-cycle one. Calendar-year filers (e.g. Ambuja pre-2022) print an "as at 30-Jun" interim BS
    that locate() can mistake for the March year-end. If the reader reported the statement date
    (asat), require it within a few days of <fy>-03-31; if it didn't, fall back to trusting it."""
    a = e.get("asat")
    if not a:
        return True
    m = re.search(r"(\d{4})\D(\d{1,2})\D(\d{1,2})", str(a)) or re.search(r"(\d{1,2})\D(\d{1,2})\D(\d{4})", str(a))
    if not m:
        return True
    g = [int(x) for x in m.groups()]
    y, mo, d = g if g[0] > 31 else [g[2], g[1], g[0]]
    try:
        return abs((date(y, mo, d) - date(int(e["fy"]), 3, 31)).days) <= 5
    except Exception:
        return True


def gate_ok(read, key):
    """(ok, add_rou). Anchor on Total Assets + PP&E vs the validate year's XBRL key.
    Filers split Right-of-use assets onto their own PDF line, but many tag ROU INSIDE the
    XBRL PropertyPlantAndEquipment tag (Ambuja FY25: PP&E 24656.29 + ROU 1464.76 = key 26121.05).
    So accept the ppe anchor if key matches the PP&E line alone OR PP&E+ROU, and report which,
    so the SAME convention is applied when landing that symbol's fill years."""
    key = key or {}
    ka, kp = key.get("assets"), key.get("ppe")
    ra, rp = read.get("assets"), read.get("ppe")
    if ra is None or not ka or abs(ra - ka) / abs(ka) > 0.01:
        return False, False  # Total Assets is the mandatory anchor
    if kp is not None and abs(kp) < 1e-9:
        # ZERO-PP&E holding/investment company (JSWHL): the PP&E anchor is degenerate (0 == 0
        # tells us nothing). Fall back to Total-Assets-only, but require the reader's PP&E to be
        # consistently ~0 (tiny vs assets) so a reader that hallucinated a real PP&E is still caught.
        if rp is None:
            return False, False
        return (abs(rp) <= max(1.0, 0.005 * abs(ka))), False
    if not kp or rp is None:
        return False, False
    if abs(rp - kp) / abs(kp) <= 0.01:
        return True, False
    rou = read.get("rou") or 0
    if abs((rp + rou) - kp) / abs(kp) <= 0.01:
        return True, True
    return False, False


def main():
    reads = json.load(open(sys.argv[1], encoding="utf-8"))
    bysym = {}
    for e in reads:
        bysym.setdefault(e["sym"], []).append(e)
    ledger = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    landed = 0
    trusted = 0
    rejected = []
    offcycle = []
    basismix = []
    for sym, entries in sorted(bysym.items()):
        val = next((e for e in entries if e.get("role") == "validate"), None)
        ok, add_rou = gate_ok(val, val.get("key")) if val else (False, False)
        if not ok:
            rejected.append(sym)
            continue
        trusted += 1
        for e in entries:
            if e.get("role") != "fill":
                continue
            if e.get("basis") != val.get("basis"):
                # never mix bases in one symbol's series — a standalone year among consolidated
                # ones (or vice-versa) reads as a false step-change. Skip; leave the year a gap.
                basismix.append("{} {}({})".format(sym, e.get("fy"), e.get("basis")))
                continue
            if not asat_ok(e):
                offcycle.append("{} {}".format(sym, e.get("fy")))
                continue
            if add_rou and e.get("ppe") is not None:
                e = dict(e)
                e["ppe"] = e["ppe"] + (e.get("rou") or 0)
            cell = {"b": e.get("basis", "c"), "m": "vision", "src": e.get("src", "")}
            cell.update({f: e[f] for f in FIELDS if e.get(f) is not None})
            if cell.get("assets") is None:
                continue
            ledger.setdefault(sym, {})["%d0331" % int(e["fy"])] = cell
            landed += 1
    json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"), sort_keys=True)
    print(
        "trusted %d symbols, landed %d fill-years. gate-rejected %d: %s | off-cycle skipped %d: %s | basis-mix skipped %d: %s"
        % (trusted, landed, len(rejected), rejected[:12], len(offcycle), offcycle[:12], len(basismix), basismix[:12])
    )


if __name__ == "__main__":
    main()

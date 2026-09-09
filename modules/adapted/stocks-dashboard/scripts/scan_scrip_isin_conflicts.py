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
"""SCAN for the wrong-company ticker trap: NSE symbols whose bse_scrips `by_id` match points at a
BSE scrip with a DIFFERENT ISIN.  Regenerates scripts/bse_scrip_isin_conflicts.json.

This is the detector behind `bse_resolve.py` (runbook §76). It is a SCAN, not a one-off: BSE adds
scrips continuously, and every new `scrip_id` is a fresh chance to collide with an NSE ticker.
Re-run it after any bse_scrips.json refresh.

Method — three identifiers, two exchanges:
  NSE  EQUITY_L.csv        SYMBOL -> "ISIN NUMBER"      (what the symbol REALLY is)
  BSE  _bse_master_all.json SCRIP_CD -> ISIN_NUMBER      (what the mapped code really is)
  ours bse_scrips.json      by_id[SYMBOL] -> SCRIP_CD    (the claim under test)
A symbol is CONFLICTING when both ISINs are known and differ. Symbols absent from EQUITY_L
(delisted/renamed) cannot be checked here and are counted separately, never silently passed.

Run:  python3 scripts/scan_scrip_isin_conflicts.py [--write] [--quiet]
Exit 1 if any conflict is found that is not already recorded (so CI can fail loudly).
"""
import contextlib
import csv
import gzip
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "bse_scrip_isin_conflicts.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NSE_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
CSV_CACHE = os.path.join(HERE, "_equity_l.csv")


def nse_symbol_isin():
    """{SYMBOL: ISIN} from NSE's own equity master. Cached locally; the cache is only used when
    the download fails, so a stale copy can never silently drive a heal."""
    raw = None
    try:
        req = urllib.request.Request(NSE_CSV_URL, headers={"User-Agent": UA, "Accept": "*/*"})
        raw = urllib.request.urlopen(req, timeout=60).read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        if len(raw) < 100000:
            raise RuntimeError("EQUITY_L.csv too small (%d bytes) — rate limited?" % len(raw))
        open(CSV_CACHE, "wb").write(raw)
    except Exception as e:
        print(f"  [EQUITY_L download failed: {e}]")
        if not os.path.exists(CSV_CACHE):
            return {}
        print(f"  [falling back to cached {CSV_CACHE}]")
        raw = open(CSV_CACHE, "rb").read()
    out = {}
    for row in csv.DictReader(raw.decode("utf-8", "replace").splitlines()):
        row = {k.strip(): (v or "").strip() for k, v in row.items()}
        if row.get("SYMBOL") and row.get("ISIN NUMBER"):
            out[row["SYMBOL"].upper()] = row["ISIN NUMBER"]
    return out


def main():
    write = "--write" in sys.argv
    quiet = "--quiet" in sys.argv

    nse = nse_symbol_isin()
    if not nse:
        print("NSE master unavailable — cannot scan. (Not a pass: nothing was checked.)")
        return 1
    scrips = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))
    by_id = scrips.get("by_id") or {}
    master = json.load(open(os.path.join(HERE, "_bse_master_all.json"), encoding="utf-8"))
    rec = {}
    for m in master:
        c = str(m.get("SCRIP_CD") or "").strip()
        if c:
            rec[c] = m

    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    universe = sorted(s for s in fund if not s.startswith("_"))

    conflicts, agreed, unmapped, uncheckable = {}, 0, 0, 0
    for sym in universe:
        code = by_id.get(sym)
        if code is None:
            unmapped += 1
            continue
        nisin = nse.get(sym.upper())
        if not nisin:
            uncheckable += 1
            continue
        bisin = (rec.get(str(code), {}).get("ISIN_NUMBER") or "").strip()
        if not bisin:
            uncheckable += 1
            continue
        if bisin == nisin:
            agreed += 1
            continue
        conflicts[sym] = {
            "nse_isin": nisin,
            "bse_code": str(code),
            "bse_isin": bisin,
            "bse_name": (rec.get(str(code), {}).get("Scrip_Name") or "").strip(),
            "isin_maps_to": (scrips.get("by_isin") or {}).get(nisin),
        }

    if not quiet:
        print(
            "checked %d symbols: agree %d | conflicts %d | no BSE code %d | uncheckable %d"
            % (len(universe), agreed, len(conflicts), unmapped, uncheckable)
        )
        for s in sorted(conflicts):
            e = conflicts[s]
            print(
                "  CONFLICT %-12s ours=%s  mapped->%s %s (ISIN %s)  ISIN-derived code=%s"
                % (s, e["nse_isin"], e["bse_code"], e["bse_name"], e["bse_isin"], e["isin_maps_to"])
            )

    prev = {}
    with contextlib.suppress(Exception):
        prev = json.load(open(OUT, encoding="utf-8")).get("conflicts") or {}
    new = sorted(set(conflicts) - set(prev))
    if new:
        print("  ★ NEW conflicts not yet recorded: {}".format(", ".join(new)))

    if write:
        merged = dict(prev)
        for k, v in conflicts.items():
            e = dict(merged.get(k) or {})
            e.update(v)
            merged[k] = e
        json.dump(
            {
                "_README": (
                    "NSE symbols whose bse_scrips by_id / BSE scrip_id match points at a "
                    "DIFFERENT company (ISINs disagree). Consumed by bse_resolve.py, which "
                    "refuses to resolve these symbols to a BSE scrip. Regenerate with "
                    "scan_scrip_isin_conflicts.py --write. Runbook §76."
                ),
                "conflicts": merged,
            },
            open(OUT, "w", encoding="utf-8"),
            indent=1,
            sort_keys=True,
        )
        print("wrote %s (%d conflicts)" % (OUT, len(merged)))

    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())

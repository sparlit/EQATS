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
"""Per-stock PRICE slices for the BSE-ONLY universe → the same stk/ dir the NSE slices go to.

WHY
  stock.html loads docs/stk/<SLUG>.json (the sf-data host) for one stock's price series; with no
  slice it boots the 17 MB whole-market engine, which has no BSE-only names → "not found". BSE-only
  names (not on NSE, so absent from sf_stock_data.bin) therefore had no page at all. This cuts them a
  slice from docs/bse_prices.bin (BSE bhavcopy closes+delivery, keyed by scripcode) in the EXACT
  format build_stock_slices.py emits — by reusing its build_slice() — so the client's installStockSlice
  reads them with zero new code and the two paths cannot drift.

  Runs AFTER build_stock_slices.py into the SAME --out dir and NEVER overwrites an existing (NSE) slice
  — a BSE ticker string that collides with a live NSE symbol is skipped, so NSE data always wins.

Store read:  docs/bse_prices.bin  {"end":YYYYMMDD,"px":{"<scripcode>":{"d":[…],"c":[…],"v":[…],"dv":[…]}}}
  dv is a 2-dp % (0 = unavailable, 0.01 = a true 0.00% day). sf_stock_data.bin stores dv x10 and the
  client divides by 10, so we pass dv*10 to build_slice to match that convention exactly.

Run:  python -X utf8 scripts/build_bse_slices.py [--out DIR] [--only SYM,…] [--limit N] [--min-days N]
      (default --out mirrors build_stock_slices.py: scripts/_sfsplit/stk ; use --out docs/stk to test
       locally, where stock.html serves ./stk/.)
"""
import argparse
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_stock_slices as bss  # reuse build_slice(), _days(), SCHEMA, TAIL — one source of truth

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
TS = 820454400  # engine START_TS — same base build_stock_slices/dash_slim use
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def slug(sym):
    return _UNSAFE.sub("_", sym)


def iso(ymd):
    s = str(ymd)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=os.path.join(HERE, "_sfsplit", "stk"),
        help="stk/ dir (default: build_stock_slices staging; use docs/stk to test locally)",
    )
    ap.add_argument("--only", default="", help="comma-separated BSE symbols (debugging)")
    ap.add_argument("--limit", type=int, default=0, help="cap number of slices (0 = all)")
    ap.add_argument("--min-days", type=int, default=20, help="skip scrips with fewer price days")
    args = ap.parse_args()
    only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    prices = json.loads(gzip.decompress(open(os.path.join(DOCS, "bse_prices.bin"), "rb").read()))["px"]
    univ = {str(r[0]): r for r in json.load(open(os.path.join(DOCS, "bse_universe.json")))["rows"]}
    by_id = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]  # SYM -> scripcode
    code2sym = {str(v): k for k, v in by_id.items()}

    # exclude names already on NSE (they have a real sf slice) — match by SYMBOL, the slice key
    sf = json.loads(gzip.decompress(open(os.path.join(DOCS, "sf_stock_data.bin"), "rb").read()))
    nse_syms = {s.upper() for s in sf["data"]}

    os.makedirs(args.out, exist_ok=True)
    written = skipped_nse = skipped_collide = skipped_thin = 0
    for code, s in prices.items():
        d = s.get("d") or []
        if len(d) < args.min_days:
            skipped_thin += 1
            continue
        sym = code2sym.get(str(code))
        row = univ.get(str(code))
        if not sym or not row:
            continue
        if only and sym.upper() not in only:
            continue
        if sym.upper() in nse_syms:  # dual-listed / on NSE → NSE slice owns it
            skipped_nse += 1
            continue
        sl = slug(sym)
        dst = os.path.join(args.out, sl + ".json")
        if os.path.exists(dst):  # never clobber an NSE slice written first
            skipped_collide += 1
            continue

        c = s.get("c") or []
        v = s.get("v") or []
        dv = s.get("dv") or []
        # build_slice reads o["d"]/["c"]/["v"]/["dv"]; dv passed x10 (client divides by 10)
        o = {"d": d, "c": c}
        if v and len(v) == len(d):
            o["v"] = v
        if dv and len(dv) == len(d):
            o["dv"] = [round(x * 10) for x in dv]
        # row: [scrip, sym, name, isin, group, faceval, mcap, sector]
        name = row[2] if len(row) > 2 and row[2] else sym
        sector = row[7] if len(row) > 7 and row[7] else ""
        mcap = row[6] if len(row) > 6 and isinstance(row[6], (int, float)) else None
        last = c[-1] if c else None
        m = {"name": name, "ind": sector, "alive": True, "raw": last}
        core = {}
        if mcap:
            core[sym + ".NS"] = {"mcap": round(mcap, 2), "latest": last}

        out = bss.build_slice(sym, o, m, iso(d[-1]), TS, None, False, core)
        out["bse"] = 1  # marks a BSE-only slice (informational)
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
        written += 1
        if args.limit and written >= args.limit:
            break

    print(
        "BSE stk slices: wrote %d → %s  (skipped: %d on NSE, %d slug-collision, %d <%d days)"
        % (written, args.out, skipped_nse, skipped_collide, skipped_thin, args.min_days)
    )


if __name__ == "__main__":
    main()

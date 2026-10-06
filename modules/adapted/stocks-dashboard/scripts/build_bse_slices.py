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

  Runs AFTER build_stock_slices.py into the SAME --out dir. A BSE ticker that is also a tape (NSE) symbol is
  skipped — the NSE slice stays — UNLESS the site gives that ticker's page to the BSE company.

  WHOSE PAGE (§203/§207, 2026-09-28, user: "BSE prices on all 76"). docs/stock_data.bin meta decides:
  SYM.NS -> the NSE company's page, only SYM.BO -> the BSE company's (bse_resolve.page_company). The old rule
  "NSE data always wins" handed 76 BSE companies' pages the tape's series of the SAME ticker: 5 another company's
  (KEL = Kotia Enterprises showed Kundan Edifice's prices, "last traded 2026-08-05", no name, no market cap;
  DRL, INNOVATIVE, BRIGHT, SIIL likewise) and 71 a dead NSE listing (SPICEJET "DELISTED ₹31.70, 2023-04-28"
  while BSE printed ₹9.85 on 2026-09-25). For those tickers the BSE company's own series now REPLACES the NSE
  slice. The tape itself (backtests) is untouched.

Store read:  docs/bse_prices.bin  {"end":YYYYMMDD,"px":{"<scripcode>":{"d":[…],"c":[…],"v":[…],"dv":[…]}}}
  dv is a 2-dp % (0 = unavailable, 0.01 = a true 0.00% day). sf_stock_data.bin stores dv x10 and the
  client divides by 10, so we pass dv*10 to build_slice to match that convention exactly.

Run:  python -X utf8 scripts/build_bse_slices.py [--out DIR] [--only SYM,…] [--limit N] [--min-days N]
      (default --out mirrors build_stock_slices.py: scripts/_sfsplit/stk ; use --out docs/stk to test
       locally, where stock.html serves ./stk/.)  SF_BIN=<path> reads a tape other than docs/sf_stock_data.bin
      (the committed copy is frozen; point it at the release asset to test locally, as build_stock_slices does).
"""
import argparse
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_resolve as BR  # page_company(): whose page a ticker is (§203)
import build_stock_slices as bss  # reuse build_slice(), _days(), SCHEMA, TAIL — one source of truth

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
SF_BIN = os.environ.get("SF_BIN") or os.path.join(DOCS, "sf_stock_data.bin")
TS = 820454400  # engine START_TS — same base build_stock_slices/dash_slim use
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def slug(sym):
    return _UNSAFE.sub("_", sym)


def iso(ymd):
    s = str(ymd)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def owner_takeovers(tape_syms, prices, code2sym, min_days, tape_isin=None):
    """{SYM: (code, same)} — tape symbols whose PAGE is the BSE company (docs/stock_data.bin meta lists SYM.BO and
    no SYM.NS, bse_resolve.page_company) and whose BSE scrip has >= min_days price sessions: the BSE series replaces
    the tape's in the stock page's slice (§207). `same` = ISIN says the tape series is the same issuer (True), another
    one (False) or cannot tell (None) — reported only; the page is the BSE company's either way. build_search_index
    imports this so the search row and the slice can never name two different owners."""
    I = BR.identities(tape_isin)
    out = {}
    for code, s in prices.items():
        sym = code2sym.get(str(code))
        if not sym or len(s.get("d") or ()) < min_days:
            continue
        S = sym.upper()
        if S not in tape_syms:
            continue
        own, bis = BR.page_company(S)
        if own != "bse":
            continue
        nis = {BR.issuer(i) for i in I["nse"].get(S, ()) if BR.issuer(i)}
        out[S] = (str(code), (bool(nis & bis) if (nis and bis) else None))
    return out


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

    prices = json.loads(gzip.decompress(open(os.path.join(DOCS, "bse_prices.bin"), "rb").read()))[
        "px"
    ]
    univ = {str(r[0]): r for r in json.load(open(os.path.join(DOCS, "bse_universe.json")))["rows"]}
    by_id = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]  # SYM -> scripcode
    code2sym = {str(v): k for k, v in by_id.items()}

    # exclude names already on NSE (they have a real sf slice) — match by SYMBOL, the slice key
    sf = json.loads(gzip.decompress(open(SF_BIN, "rb").read()))
    nse_syms = {s.upper() for s in sf["data"]}
    # ...except where the site gives the ticker's page to the BSE company (§207): its own series replaces the tape's.
    take = owner_takeovers(
        nse_syms,
        prices,
        code2sym,
        args.min_days,
        {
            k: v["isin"]
            for k, v in (sf.get("meta") or {}).items()
            if isinstance(v, dict) and v.get("isin")
        },
    )
    del sf

    os.makedirs(args.out, exist_ok=True)
    written = skipped_nse = skipped_collide = skipped_thin = replaced = 0
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
        owner = take.get(sym.upper(), (None,))[0] == str(code)
        if sym.upper() in nse_syms and not owner:  # dual-listed / on NSE → NSE slice owns it
            skipped_nse += 1
            continue
        sl = slug(sym)
        dst = os.path.join(args.out, sl + ".json")
        if os.path.exists(dst) and not owner:  # never clobber an NSE slice written first
            skipped_collide += 1
            continue
        replaced += owner and os.path.exists(dst)

        c = s.get("c") or []
        v = s.get("v") or []
        dv = s.get("dv") or []
        # build_slice reads o["d"]/["c"]/["v"]/["dv"]; dv passed x10 (client divides by 10)
        o = {"d": d, "c": c}
        if v and len(v) == len(d):
            o["v"] = v
        if dv and len(dv) == len(d):
            o["dv"] = [int(round(x * 10)) for x in dv]
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
    other = sorted(k for k, v in take.items() if v[1] is False)
    print(
        "  §207 page owner: %d BSE companies' pages took their own BSE series over the tape's slice of the same "
        "ticker (%d replaced here; the tape series is another company's for %d: %s; same issuer %d, unproven %d)"
        % (
            len(take),
            replaced,
            len(other),
            ", ".join(other) or "-",
            sum(1 for v in take.values() if v[1]),
            sum(1 for v in take.values() if v[1] is None),
        )
    )


if __name__ == "__main__":
    main()

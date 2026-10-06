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
"""Fill docs/bse_prices.bin (the BSE-ONLY price store) back to 2020 from the local BSE bhavcopy cache (runbook §149).

The store is what BSE-only stock pages chart (build_bse_slices.py → stk/<SYM>.json). It began in 2023; the nightly
refresh-bse.yml walks it back 90 calendar days per run toward --backfill-floor 20200101, store-wide (the frontier is
the EARLIEST date across all scrips). scripts/_bse_bhav_cache/ already holds every BSE daily bhavcopy 2020-01-01 →
today (build_bse_sme_backfill.py --fetch), so this fills every BSE-only scrip from it in one pass — ALL scrips, not
only SME ones, because filling only some would move the store-wide frontier to 2020 and strand the rest at 2023.

Conventions = fetch_bse_bhav.day_closes exactly: close = the file's close rounded to 2 dp (RAW, no adjustment),
volume = traded shares (int), dv = 0 (delivery unknown; the nightly heal_delivery fills it from SCBSEALL).
FILL-ONLY: a (scrip, date) already stored is never touched. `--check` compares the cache against every overlapping
stored (scrip, date) and refuses to write unless the closes agree.

Run: python3 -X utf8 scripts/merge_bse_px_from_cache.py [--store PATH] [--check-only]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_bse_sme_backfill as C  # rows_of(): date-checked parser for both bhavcopy formats
import fetch_bse_bhav as F  # save_prices(): sorts + pads dv exactly as the nightly does


def main():
    a = sys.argv[1:]
    store = a[a.index("--store") + 1] if "--store" in a else F.OUT
    F.OUT = store
    data = F.load_prices()
    px = data["px"]
    codes = F.bse_only_codes()
    have = {c: set(s["d"]) for c, s in px.items()}
    files = sorted(f for f in os.listdir(C.CACHE) if f[:8].isdigit() and int(f[:8]) >= 20200101)
    agree = differ = added = days_used = 0
    ex = []
    for f in files:
        k = int(f[:8])
        rs = C.rows_of(k, os.path.join(C.CACHE, f))
        if rs is None:
            continue
        days_used += 1
        for code, _g, c, _pc, v, _isin, _tk in rs:
            if code not in codes or c <= 0:
                continue
            c2 = round(c, 2)
            if k in have.get(code, ()):
                s = px[code]
                i = s["d"].index(k)
                if abs(s["c"][i] - c2) <= 0.005:
                    agree += 1
                else:
                    differ += 1
                    if len(ex) < 8:
                        ex.append((code, k, s["c"][i], c2))
                continue
            if "--check-only" in a:
                continue
            s = px.setdefault(code, {"d": [], "c": [], "v": [], "dv": []})
            F.ensure_dv(s)
            s["d"].append(k)
            s["c"].append(c2)
            s["v"].append(int(v))
            s["dv"].append(0)
            have.setdefault(code, set()).add(k)
            added += 1
    print(
        "cache days %d | overlap closes agree %d, differ %d %s | added %d (scrip,date) rows"
        % (days_used, agree, differ, ex, added)
    )
    if differ > max(10, agree * 0.001):
        print(
            "REFUSED: cache disagrees with the store on %d overlapping closes — not writing"
            % differ
        )
        sys.exit(2)
    if "--check-only" not in a and added:
        F.save_prices(data)
        first = min(s["d"][0] for s in px.values() if s["d"])
        print("wrote %s | earliest stored date now %d | scrips %d" % (store, first, len(px)))


if __name__ == "__main__":
    main()

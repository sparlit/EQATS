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
"""Apply the 5 cells the screener ANNUAL-DERIVATION sweep produced for the 2020+ window (§60d).

Route: `annual_total - sum(the other three stored quarters of that FY)`. This is arithmetic on a
published total, not an estimate — but the total is CRORE-ROUNDED on screener, so every value here
carries ±0.5cr of inherited rounding and is journalled `precision: "derived-crore-rounded"` (§60e).
A later filing read may refine it; nothing may mistake it for a filing-precision figure.

GATES the sweep already applied per company (screener_annual_sweep.py):
  A   our own 4-quarter sums reproduce screener's annual for >=3 other FYs, >=60% agreement —
      this is what proves the ENTITY and the BASIS match (the TMPV/JLR failure mode), and for
      INDIANB/MAHABANK it also proves the BANK revenue convention matches (screener's "Revenue"
      row against our Interest-Earned-based series) rather than assuming it.
  A2  years disagreeing with our sums are rejected individually — those are restatement/demerger
      years where screener carries the RESTATED total against our as-reported quarters; the
      residual would be garbage that passes every plausibility check. Adjacent years go too.
  B   the derived value must be > 0 and within 0.2x-5x its sibling quarters — this catches the
      case where one of the three STORED quarters is itself the wrong cell.

85 company/basis pairs were REJECTED by those gates and are deliberately not here (64 on Gate A,
19 on Gate A2, 2 on Gate B). Fill-only, revenue slot only.

  python -X utf8 scripts/fill2020_tools/apply_screener_derived_2020.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "screener_derived_rev_fills.json")

# (sym, qe, slot, value, FY total, the three stored quarters that were subtracted)
CELLS = [
    ("HBLENGINE", "20200331", 1, 262.99, 1092.0, "FY2020 Sales; siblings 264.12/305.85/259.04"),
    ("INDIANB", "20210630", 1, 9650.04, 38888.0, "FY2022 Revenue; siblings 9476.10/9927.36/9834.50"),
    ("MAHABANK", "20210630", 1, 3103.39, 13019.0, "FY2022 Revenue; siblings 3207.29/3282.12/3426.20"),
    ("SHRIRAMCIT", "20200331", 0, 1488.58, 5884.0, "FY2020 Sales; siblings 1437.16/1489.23/1469.03"),
    ("TITAGARH", "20220331", 0, 440.11, 1496.0, "FY2022 Sales; siblings 338.23/333.04/384.62"),
]


def main():
    dry = "--apply" not in sys.argv
    applied = []
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        for sym, qe, slot, val, fy, note in CELLS:
            row = d.get(sym, {}).get(qe)
            if not row:
                print("%-26s %s %s no row" % (os.path.basename(path), sym, qe))
                continue
            while len(row) < 9:
                row.append(None)
            if row[slot] is not None:
                print("%-26s %s %s already filled: %s" % (os.path.basename(path), sym, qe, row[slot]))
                continue
            row[slot] = val
            d[sym][qe] = row
            applied.append((sym, qe, slot, val, fy, note))
            print(
                "%-26s %s %s %s %s=%s"
                % (os.path.basename(path), sym, qe, "would fill" if dry else "filled", "revC" if slot else "revS", val)
            )
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
    if not dry:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        for sym, qe, slot, val, fy, note in applied:
            led["{}|{}|{}".format(sym, qe, "revC" if slot else "revS")] = {
                "value": val,
                "fy_total": fy,
                "src": "screener.in annual - 3 stored quarters (§60d)",
                "evidence": note,
                "precision": "derived-crore-rounded",
                "applied": "2026-08-11 screener route, 2020+ window",
            }
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled %d -> %s" % (len(applied), os.path.basename(LEDGER)))
    else:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()

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
"""FILL-2020: MCX 2026-03 consolidated revenue = 888.94, read by VISION from the filing image.

Why every automated route missed it, and why the first manual pass missed it too:
  * BSE detailed-results has no row for the quarter; the NSE archive list does not reach 2026.
  * The announcement PDF DOES contain the consolidated statement -- but as an IMAGE. Page 2 of
    the 08-May-2026 filing ("Financial Results (Consolidated And Standalone)") extracts as 11
    characters of text ("Annexure A") with one embedded image. Every text-layer scan therefore
    reported "no consolidated statement", including mine, even though the filing's own TITLE says
    it has one. Rendering the page and reading it (route ladder rung 10, §57b) shows the full
    "AUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER AND YEAR ENDED MARCH 31, 2026".

THE READ (₹ in crores, as declared on the page):
    columns:            Q 31-03-2026 | Q 31-12-2025 | Q 31-03-2025 | FY26 | FY25
    Income from operations   888.94   |   665.62     |   291.33
    Net profit after tax     529.77   |   401.12     |   135.46
    Net profit attributable to Owner of the Company: same figures (NCI is nil)

COLUMN ANCHOR (§58) -- the Dec-2025 column reproduces BOTH of our stored consolidated values for
that quarter, so the column mapping AND the revenue row are proven, not just the document:
    page con PAT 401.12   == stored MCX 20251231 patC 401.12   (exact)
    page con revenue 665.62 == stored MCX 20251231 revC 665.62 (exact)
and the target column's own PAT 529.77 == stored 20260331 patC 529.77 (exact).
Sanity: revC 888.94 > revS 828.72, as expected for a group whose subsidiary adds revenue.

Fill-only, revenue slot (1) only.
Run: python -X utf8 scripts/fill2020_tools/apply_mcx_mar26.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills.json")

SYM, QE, VAL = "MCX", "20260331", 888.94
EV = (
    "vision read of the image-only page 2 of the 08-May-2026 filing; anchors: Dec-2025 column "
    "reproduces stored con PAT 401.12 AND stored con revenue 665.62 exactly, target column PAT "
    "529.77 == stored con PAT"
)


def main():
    dry = "--apply" not in sys.argv
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        row = d.get(SYM, {}).get(QE)
        if not row:
            print("%-30s no row" % os.path.basename(path))
            continue
        while len(row) < 9:
            row.append(None)
        if row[1] is not None:
            print("%-30s already filled: %s" % (os.path.basename(path), row[1]))
            continue
        row[1] = VAL
        d[SYM][QE] = row
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s %s revC=%s" % (os.path.basename(path), "would fill" if dry else "filled", VAL))
    if not dry:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led[f"{SYM}|{QE}"] = {
            "revC": VAL,
            "src": "bse-filing-pdf-VISION",
            "evidence": EV,
            "applied": "2026-08-06 Mar-2026 sweep",
        }
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print(f"journalled -> {os.path.basename(LEDGER)}")
    else:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()

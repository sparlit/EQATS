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
"""VADILALIND 2025-12-31, and re-write the suspect ledger with a per-cell abstain reason.

VADILALIND was flagged because npCon -0.15 sits far below its ~14 cr family median. Three sources
now say the flag was a FALSE ALARM and the quarter really is near zero:
  * the Dec-2025 consolidated page prints period -0.15, NCI 0.01 at the Dec-25 column,
  * screener independently reports con ~-0.0 (and std -14.0, matching our npStd -14.28),
  * so owners = -0.15 - 0.01 = -0.16, and the mirror's 2.49 is the wrong value here.
Both files go to -0.16.

The other 17 are NOT written. Three automated passes could not place them, and the failure is per
cell, not one fixable gap -- the reasons are recorded below so the next attempt starts from a
diagnosis instead of from scratch.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
SUSPECTS = os.path.join(SCRIPTS, "_fund_suspect_cells.json")

SYM, QE, WAS_FUND, WAS_REVOP, NOW = "VADILALIND", 20251231, -0.15, 2.49, -0.16

# per-cell first-rung-that-broke, from the instrumented pass
WHY = {
    "3IINFOLTD|20251231": "no NCI row on the page carrying the target quarter (46 con pages, 18 with the header)",
    "ARIHANTCAP|20260331": "no profit-for-period row co-occurring with the target column",
    "AXISCADES|20181231": "rows found but period - NCI != owners; wrong rows picked",
    "BANCOINDIA|20190331": "no profit-for-period row co-occurring with the target column",
    "BODALCHEM|20230930": "no profit-for-period row co-occurring with the target column",
    "CENTUM|20240930": "no profit-for-period row co-occurring with the target column",
    "DCXINDIA|20260331": "no profit-for-period row co-occurring with the target column",
    "DELTAMAGNT|20220331": "no NCI row on the page carrying the target quarter",
    "IFCI|20241231": "rows found but the identity fails; revop 741.53 vs fund -8.74 is a wide gap, needs the document",
    "IRB|20200930": "target quarter appears in NO header row across 54 consolidated pages",
    "JHS|20180930": "no consolidated page at all in 3 fetched PDFs -- likely scanned; VISION rung",
    "LANCORHOL|20250331": "rows found but the identity fails; wrong rows picked",
    "NAZARA|20240331": "no NCI row on the page carrying the target quarter (material NCI company)",
    "STLTECH|20250930": "no profit-for-period row co-occurring with the target column",
    "SUBCAPCITY|20200331": "NO SCRIPCODE in scrip_map -> the BSE announcement stream is unreachable",
    "SUBCAPCITY|20210331": "NO SCRIPCODE in scrip_map -> the BSE announcement stream is unreachable",
    "TRF|20231231": "no NCI row on the page carrying the target quarter",
}


def main():
    dry = "--apply" not in sys.argv
    n = 0
    for paths, idx, keyed in ((FUND, 3, False), (REVOP, 5, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            row = (d.get(SYM) or {}).get(str(QE)) if keyed else next((r for r in d.get(SYM, []) if r[0] == QE), None)
            if not row or len(row) <= idx:
                continue
            cur = row[idx]
            if cur is None or abs(cur - NOW) < 0.005:
                continue
            exp = WAS_REVOP if keyed else WAS_FUND
            if abs(cur - exp) > 0.005:
                sys.exit(f"GUARD {SYM} in {os.path.basename(path)}: {cur} expected {exp}")
            print("  %-24s %-26s %s -> %s" % ("%s|%d" % (SYM, QE), os.path.basename(path), cur, NOW))
            row[idx] = NOW
            n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    sus = json.load(open(SUSPECTS, encoding="utf-8"))
    sus["cells"] = [
        dict(c, abstain_reason=WHY.get("%s|%d" % (c["sym"], c["qe"]), "?"))
        for c in sus["cells"]
        if not (c["sym"] == SYM and c["qe"] == QE)
    ]
    sus["_README"].append(
        "2026-08-09 pass 3: VADILALIND settled and removed -- its flag was a FALSE ALARM (the "
        "quarter really is near zero; screener con ~-0.0 agrees with the filing's -0.15/-0.16). "
        "17 remain, each now carrying `abstain_reason` from an instrumented pass. Three of them are "
        "structural rather than reader gaps: SUBCAPCITY x2 have NO SCRIPCODE so the BSE stream "
        "cannot be reached at all, and JHS 20180930 returned no consolidated page in any fetched "
        "PDF (scanned -- that is the VISION rung, which needs the user's go-ahead)."
    )
    json.dump(sus, open(SUSPECTS, "w", encoding="utf-8"), indent=1)
    print("suspect ledger: %d open, each with an abstain_reason" % len(sus["cells"]))


if __name__ == "__main__":
    main()

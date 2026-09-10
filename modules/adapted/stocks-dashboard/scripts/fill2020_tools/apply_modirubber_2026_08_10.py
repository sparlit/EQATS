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
"""MODIRUBBER 2025-09-30 STANDALONE PAT: 4.56 -> -4.36. Unlocked by the §71l page_basis fix.

This is the MIRROR defect (§65b): the std slot holding the con value. It sat in
`_std_slot_holds_con.json` as OUT-OF-RESOLUTION because three passes could not read the filing --
the reader kept skipping the only page that had the numbers, since that page names both bases
(§71k). With `page_shows` in place `read_con_copies --basis std` reads it on the first attempt.

Three independent supports, none of them each other:
  1. the filing, column-anchored: a second column on the same rows reproduces screener's STANDALONE
     figure for a different quarter, which is what identifies the column (§58);
  2. screener's standalone for this quarter is -4.39 against the read's -4.36;
  3. family: every neighbouring npStd is NEGATIVE -- Dec-24 -3.17, Mar-25 -4.93, Jun-25 -3.79,
     Dec-25 -2.05, Mar-26 -9.19 -- while the stored 4.56 is positive AND exactly equals npCon,
     which is the copy fingerprint itself.

npCon stays 4.56: screener's consolidated for the quarter is 5.0, so the CON slot is right and only
the STANDALONE one was overwritten.

  python -X utf8 scripts/fill2020_tools/apply_modirubber_2026_08_10.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
RESIDUE = os.path.join(SCRIPTS, "_std_slot_holds_con.json")

SYM, QE, WAS, NOW = "MODIRUBBER", 20250930, 4.56, -4.36
FUND_STD, REVOP_STD = 1, 4  # npStd / patStd -- the CON slots are correct and untouched


def main():
    dry = "--apply" not in sys.argv
    n = 0
    for paths, idx, keyed in ((FUND, FUND_STD, False), (REVOP, REVOP_STD, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            row = (d.get(SYM) or {}).get(str(QE)) if keyed else next((r for r in d.get(SYM, []) if r[0] == QE), None)
            if not row or len(row) <= idx or row[idx] is None:
                continue
            if abs(row[idx] - NOW) < 0.005:
                continue
            if abs(row[idx] - WAS) > 0.005:
                sys.exit(f"GUARD {SYM} in {os.path.basename(path)}: {row[idx]} expected {WAS}")
            print("  %-22s %-26s npStd %s -> %s" % ("%s|%d" % (SYM, QE), os.path.basename(path), row[idx], NOW))
            row[idx] = NOW
            n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print(
        "\n%d slot(s) %s   (npCon left at 4.56 -- screener con 5.0 agrees)"
        % (n, "would change (dry run)" if dry else "changed")
    )
    if dry:
        print("(pass --apply)")
        return
    r = json.load(open(RESIDUE, encoding="utf-8"))
    c = r["cells"].get("%s|%d|patC" % (SYM, QE))
    if c:
        c["status"] = "RESOLVED"
        c["resolved"] = (
            "2026-08-10: npStd 4.56 -> -4.36 after the §71l page_basis fix made the "
            "statement page visible. Filing read column-anchored on screener's "
            "standalone for another quarter; screener std -4.39; every neighbouring "
            "npStd is negative while 4.56 equalled npCon exactly. npCon unchanged."
        )
        json.dump(r, open(RESIDUE, "w", encoding="utf-8"), indent=1)
    import collections

    print("residue ledger:", dict(collections.Counter(v["status"] for v in r["cells"].values())))


if __name__ == "__main__":
    main()

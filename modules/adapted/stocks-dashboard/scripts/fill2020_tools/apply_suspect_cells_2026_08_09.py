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
"""The fundamentals-suspect cells (§71b) that now have decisive evidence. 5 of 23.

Two evidence shapes, both requiring a source OUTSIDE our own dataset:

A. FOUR cells where screener -- independent, and quoting TOTAL PAT -- agrees with the sf_revop
   mirror while sf_fundamentals sits wildly out of the company's own family. The std side of the
   same quarter already agrees between our two files, so the defect is isolated to npCon:

     NUCLEUS    2025-12-31  npCon 250.20  -> 20.70     screener 21    (npStd 17.42, both files agree)
     OSWALAGRO  2023-06-30  npCon   0.30  ->  4.28     screener 4.28  (npCon was a copy of npStd)
     RELCAPITAL 2023-03-31  npCon 2436.50 -> -1502.57  screener -1499 (npStd -4.35, both agree)
     ZEAL       2026-03-31  npCon 4114.27 ->  6.53     screener 7     -- and npStd 4114.27 -> 7.15,
                            because BOTH bases carry the same junk against a series running
                            6.31 / 10.06 / 1.54 / 3.00 / 10.06 in the five prior quarters.

B. ONE cell settled by the filing itself, which is stronger than screener because screener's
   1-decimal display cannot separate 0.17 from 0.00:

     SURANAT&P  2025-09-30  the Sep-2025 consolidated page prints, at the Sep-25 column,
                            period 0.17, non-controlling interest -0.59, owners 0.76
                            -- and 0.17 - (-0.59) = 0.76 exactly. We store OWNERS, so npCon
                            should be 0.76 (which is what the mirror already held).

WHAT IS NOT FIXED HERE, and why: the other 18. screener quotes TOTAL PAT, so "screener agrees with
sf_fundamentals" tells us fundamentals holds the TOTAL -- it does NOT tell us whether that is right
under our owners convention. For a company with material NCI the owners figure differs and the
mirror may be the correct one. Settling those needs one number per cell from the filing (the NCI
line), and guessing instead is precisely what produced TATACOFFEE and the §71 near-miss.

  python -X utf8 scripts/fill2020_tools/apply_suspect_cells_2026_08_09.py [--apply]
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
LEDGER = os.path.join(SCRIPTS, "owners_basis_heals.json")
NPCON, NPSTD = 3, 1
PATC, PATS = 5, 4

# (sym, qe) -> {con:(was,now), std:(was,now)|None, why}
FIX = {
    ("NUCLEUS", 20251231): {
        "con": (250.2, 20.7),
        "std": None,
        "why": "screener 21 agrees with the mirror; fund 250.2 vs a 26.8 family median",
    },
    ("OSWALAGRO", 20230630): {
        "con": (0.3, 4.28),
        "std": None,
        "why": "screener 4.28 agrees with the mirror; npCon was an exact copy of npStd 0.3",
    },
    ("RELCAPITAL", 20230331): {
        "con": (2436.5, -1502.57),
        "std": None,
        "why": "screener -1499 agrees with the mirror; fund +2436.5 has the wrong sign AND magnitude",
    },
    ("ZEAL", 20260331): {
        "con": (4114.27, 6.53),
        "std": (4114.27, 7.15),
        "why": "BOTH bases carry 4114.27 against a series of 6.31/10.06/1.54/3.00/10.06; screener 7 on both",
    },
    ("SURANAT&P", 20250930): {
        "con": (0.17, 0.76),
        "std": None,
        "why": "filing Sep-25 column: period 0.17 - NCI (-0.59) = owners 0.76, exactly",
    },
}


def main():
    dry = "--apply" not in sys.argv
    print("%-12s %-10s %-5s %11s %11s  %s" % ("sym", "quarter", "slot", "was", "now", "why"))
    for (sym, qe), f in sorted(FIX.items()):
        print("%-12s %-10d %-5s %11s %11s  %s" % (sym, qe, "npCon", f["con"][0], f["con"][1], f["why"]))
        if f["std"]:
            print("%-12s %-10d %-5s %11s %11s" % ("", qe, "npStd", f["std"][0], f["std"][1]))

    n = 0
    for path in FUND:
        d = json.load(open(path, encoding="utf-8"))
        for (sym, qe), f in FIX.items():
            row = next((r for r in d.get(sym, []) if r[0] == qe), None)
            if not row or len(row) <= NPCON:
                continue
            for idx, pair in ((NPCON, f["con"]), (NPSTD, f["std"])):
                if not pair:
                    continue
                was, now = pair
                cur = row[idx]
                if cur is not None and abs(cur - now) < 0.005:
                    continue
                if cur is None or abs(cur - was) > 0.005:
                    sys.exit(
                        "GUARD %s %d slot%d in %s: %s expected %s" % (sym, qe, idx, os.path.basename(path), cur, was)
                    )
                row[idx] = now
                n += 1
        if not dry:
            json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    # keep the mirror in step (ZEAL's std side is the only one it does not already hold)
    for path in REVOP:
        d = json.load(open(path, encoding="utf-8"))
        for (sym, qe), f in FIX.items():
            row = (d.get(sym) or {}).get(str(qe))
            if not row or len(row) <= PATC:
                continue
            for idx, pair in ((PATC, f["con"]), (PATS, f["std"])):
                if not pair:
                    continue
                if row[idx] is not None and abs(row[idx] - pair[1]) > 0.005:
                    row[idx] = pair[1]
                    n += 1
        if not dry:
            json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return

    # shrink the suspect ledger to what is genuinely still open, and record what screener settled
    sus = json.load(open(SUSPECTS, encoding="utf-8"))
    done = {("%s|%d" % (s, q)) for (s, q) in FIX}
    sus["cells"] = [c for c in sus["cells"] if "%s|%d" % (c["sym"], c["qe"]) not in done]
    sus["_README"].append(
        "2026-08-09 pass 2: 5 of the 23 settled (NUCLEUS, OSWALAGRO, RELCAPITAL, ZEAL, SURANAT&P) "
        "and removed. For 10 of the remaining 18, screener AGREES with sf_fundamentals -- but "
        "screener quotes TOTAL PAT, so that only establishes fundamentals holds the TOTAL, not that "
        "it is right on our owners basis. Each of those needs exactly one number from the filing: "
        "the non-controlling-interest line. 5 more have no screener coverage at all (AXISCADES, "
        "BANCOINDIA, DELTAMAGNT, IRB, JHS) and 3 are ambiguous (3IINFOLTD, ARIHANTCAP, "
        "SUBCAPCITY 20210331)."
    )
    json.dump(sus, open(SUSPECTS, "w", encoding="utf-8"), indent=1)
    led = json.load(open(LEDGER, encoding="utf-8"))
    for (sym, qe), f in FIX.items():
        led["cells"]["%s|%d|patC" % (sym, qe)] = {
            "owners": f["con"][1],
            "stored_before": f["con"][0],
            "note": f["why"],
            "also_npStd": f["std"],
        }
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print("suspect ledger now %d open; owners_basis_heals updated" % len(sus["cells"]))


if __name__ == "__main__":
    main()

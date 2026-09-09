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
"""Close the last 16 fund-vs-revop divergences by resyncing the MIRROR. Writes only sf_revop.

These were held back by §71b because sf_fundamentals looked out of family. Working them one by one
showed the screen was a FALSE ALARM for the whole population, and that they are all one thing:

    sf_fundamentals holds the XBRL's TOTAL      (ProfitLossForPeriod)
    sf_revop        holds the XBRL's OWNERS tag (ProfitOrLossAttributableToOwnersOfParent)

and in these filings that owners tag is incoherent -- the identity `owners + NCI == total` fails in
14 of 16, sometimes absurdly (NAZARA: owners 8.35 + NCI 8.70 against a total of 0.18; IFCI: owners
741.53 + NCI 719.26 against -8.74). Where the NCI tag reads 0.0, total IS owners anyway.

THE INDEPENDENT CHECK THAT SETTLED IT. screener, which quotes TOTAL PAT, was asked for all 16:
**it agrees with sf_fundamentals in 9 and with sf_revop in ZERO** -- BODALCHEM, CENTUM, DCXINDIA,
IFCI (-9.0 vs -8.74), LANCORHOL, NAZARA, STLTECH, SUBCAPCITY 2020-03, TRF. Four have no screener
coverage and three are ambiguous, but not one cell supports the mirror.

So the authoritative file is right and the mirror is the corrupted copy. Resyncing the mirror to it
cannot introduce a new error -- worst case the mirror carries an error the site already displays --
and it removes the class. **sf_fundamentals is not touched; that is asserted byte-for-byte after.**

The 7 without independent confirmation (AXISCADES, BANCOINDIA, DELTAMAGNT, IRB, 3IINFOLTD,
ARIHANTCAP, SUBCAPCITY 2021-03) are resynced on the structural argument but recorded in
`_fund_unconfirmed_cells.json` so "no divergence" is never mistaken for "verified".

  python -X utf8 scripts/fill2020_tools/resync_last16_2026_08_09.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUNDP = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
SUSPECTS = os.path.join(SCRIPTS, "_fund_suspect_cells.json")
UNCONF = os.path.join(SCRIPTS, "_fund_unconfirmed_cells.json")
REVOP_IDX = 5

# screener (TOTAL basis) reproduced sf_fundamentals on these
CONFIRMED = {
    ("BODALCHEM", 20230930),
    ("CENTUM", 20240930),
    ("DCXINDIA", 20260331),
    ("IFCI", 20241231),
    ("LANCORHOL", 20250331),
    ("NAZARA", 20240331),
    ("STLTECH", 20250930),
    ("SUBCAPCITY", 20200331),
    ("TRF", 20231231),
}


def main():
    dry = "--apply" not in sys.argv
    fu = json.load(open(FUNDP, encoding="utf-8"))
    auth = {}
    for sym, rows in fu.items():
        for r in rows:
            if len(r) > 3 and r[3] is not None:
                auth[(sym, r[0])] = r[3]
    cells = json.load(open(SUSPECTS, encoding="utf-8"))["cells"]
    before = open(FUNDP, "rb").read()

    print("%-12s %-9s %10s %10s  %s" % ("sym", "quarter", "mirror", "-> auth", "independent check"))
    unconf, n = [], 0
    for c in sorted(cells, key=lambda z: (z["sym"], z["qe"])):
        sym, qe = c["sym"], c["qe"]
        a = auth.get((sym, qe))
        if a is None:
            print("%-12s %-9d  no authoritative value -- skipped" % (sym, qe))
            continue
        tag = "screener confirms fundamentals" if (sym, qe) in CONFIRMED else "UNCONFIRMED (structural resync)"
        if (sym, qe) not in CONFIRMED:
            unconf.append(
                {
                    "sym": sym,
                    "qe": qe,
                    "value": a,
                    "was_mirror": c["revop"],
                    "why": "resynced to the authoritative file, but no independent source "
                    "reached this cell -- verify before relying on it",
                }
            )
        print("%-12s %-9d %10s %10s  %s" % (sym, qe, c["revop"], a, tag))
        for path in REVOP:
            d = json.load(open(path, encoding="utf-8"))
            row = (d.get(sym) or {}).get(str(qe))
            if (
                row
                and len(row) > REVOP_IDX
                and row[REVOP_IDX] is not None
                and abs(row[REVOP_IDX] - a) > max(0.02, abs(a) * 0.002)
            ):
                row[REVOP_IDX] = a
                n += 1
                if not dry:
                    json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))

    assert open(FUNDP, "rb").read() == before, "sf_fundamentals was modified -- it must not be"
    print(
        "\n%d mirror slot(s) %s   (sf_fundamentals byte-identical: OK)"
        % (n, "would change (dry run)" if dry else "changed")
    )
    if dry:
        print("(pass --apply)")
        return
    json.dump(
        {
            "_README": [
                "Cells resynced mirror<-authoritative in the §71g pass WITHOUT an independent source having",
                "reached them. sf_fundamentals is authoritative and the resync introduces no new error, but",
                "'no longer divergent' is NOT 'verified'. Each still deserves a filing read.",
            ],
            "generated": "2026-08-09",
            "cells": unconf,
        },
        open(UNCONF, "w", encoding="utf-8"),
        indent=1,
    )
    s = json.load(open(SUSPECTS, encoding="utf-8"))
    s["cells"] = []
    s["_README"].append(
        "2026-08-09 CLOSED. All 23 resolved: 6 corrected from documents, 17 shown to be a FALSE "
        "ALARM of the out-of-family screen -- sf_fundamentals held the XBRL TOTAL (screener agrees "
        "with it in 9 cells and with the mirror in ZERO) while sf_revop held an incoherent owners "
        "tag. The mirror was resynced to the authoritative file; sf_fundamentals untouched. The 7 "
        "with no independent confirmation are listed in _fund_unconfirmed_cells.json."
    )
    json.dump(s, open(SUSPECTS, "w", encoding="utf-8"), indent=1)
    print("suspect ledger closed; %d cells recorded as unconfirmed" % len(unconf))


if __name__ == "__main__":
    main()

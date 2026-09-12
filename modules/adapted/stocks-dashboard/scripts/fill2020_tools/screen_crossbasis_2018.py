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
"""§76b SCREEN: did a PAT-anchored reader hand us the STANDALONE column of a combined page?

THE FINGERPRINT is `con == std to the paisa`. 2018-19 filings routinely print both statements under
one "Standalone and Consolidated" heading, so a page qualifies for either basis, and a PAT anchor
CANNOT separate two bases sitting ~0.1% apart — `close()`'s 0.4% band admits both. CORPBANK 2019-03
landed 3,643.37 that way in the 2019 campaign (its anchored PAT was the stored STANDALONE one) and
was caught by exactly this screen.

Run it over every cell this campaign writes, not just the ones that look suspicious.

**A hit is not a defect.** Legitimate con == std exists and has to be confirmed rather than assumed:
MOIL's consolidated revenue equals standalone in all 11 stored neighbouring quarters (an associate
is equity-accounted, so con PAT differs by exactly the pickup), same for CHENNPETRO in 26 of 31 and
PETRONET. The test is the company's OWN neighbouring quarters: if con == std there too, the
identity is the company's real convention; if the neighbours diverge, this cell is a cross-basis
misread and must be retracted.

  python -X utf8 scripts/fill2020_tools/screen_crossbasis_2018.py [--qe 20180331,...]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
Q2018 = [20180331, 20180630, 20180930, 20181231]


def main():
    qes = {int(q) for q in sys.argv[sys.argv.index("--qe") + 1].split(",")} if "--qe" in sys.argv else set(Q2018)
    targets = json.load(open(TARGETS))
    revop = json.load(open(REVOP))
    fund = {
        s: {int(r[0]): (r[1], r[3] if len(r) > 3 else None) for r in rows} for s, rows in json.load(open(FUND)).items()
    }

    hits, clean = [], 0
    for sym, v in sorted(targets.items()):
        for qe in v.get("revC", []):
            if qe not in qes:
                continue
            row = (revop.get(sym) or {}).get(str(qe))
            if not row or row[1] is None:
                continue  # still open
            clean += 1
            s, c = row[0], row[1]
            if s is None or abs(c - s) > 0.005:
                continue  # bases differ -> not the fingerprint
            # con == std to the paisa. Confirm against the company's OWN neighbouring quarters.
            # RELATIVE, not absolute. An absolute 0.005 threshold splits "equal" from "different"
            # on rounding noise — SCI prints 875.35/875.39 in one quarter and 1,438.23/1,438.23 in
            # another, and calling the first pair DIFFERENT turned a clean company-convention
            # verdict into "mixed neighbours — read the filing". Measured properly, SCI has 30
            # quarters with both bases stored and ZERO differing by >1%.
            nb_eq = nb_diff = 0
            for q, r2 in (revop.get(sym) or {}).items():
                if int(q) == qe or r2[0] is None or r2[1] is None or r2[0] == 0:
                    continue
                if abs(r2[1] - r2[0]) / abs(r2[0]) <= 0.01:
                    nb_eq += 1
                else:
                    nb_diff += 1
            ps, pc = fund.get(sym, {}).get(qe, (None, None))
            pat_sep = None
            if ps is not None and pc is not None and abs(ps) > 1e-9:
                pat_sep = abs(pc - ps) / abs(ps) * 100
            hits.append((sym, qe, c, nb_eq, nb_diff, pat_sep))

    print("cells filled in scope: %d   con==std fingerprint: %d\n" % (clean, len(hits)))
    for sym, qe, c, eq, df, sep in sorted(hits):
        verdict = (
            "company convention (neighbours agree)"
            if eq and not df
            else "★ INVESTIGATE — neighbours DIVERGE"
            if df and not eq
            else "mixed neighbours — read the filing"
            if df
            else "no neighbours to compare — read the filing"
        )
        print(
            "  %-12s %d  rev %12.2f   neighbours con==std %d / differ %d   PAT sep %s   %s"
            % (sym, qe, c, eq, df, (f"{sep:.2f}%") if sep is not None else "n/a", verdict)
        )
    if not hits:
        print("  (none)")


if __name__ == "__main__":
    main()

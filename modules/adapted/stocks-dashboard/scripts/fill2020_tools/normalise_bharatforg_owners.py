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
"""BHARATFORG: put the whole consolidated PAT series on the OWNERS convention, then unblock 4 fills.

WHY THIS EXISTS. conpat_filing_fills.json carries the key
"BHARATFORG|contriad|REFUSED-SERIES-INCONSISTENT" from the 2026-08-17 con-triad pass, whose verdict
is "write NOTHING until the series is normalized to one convention". It was right: our stored
consolidated PAT alternates between the printed TOTAL and the printed OWNERS figure, and this
company's NCI is material (up to 12 cr a quarter), so the mix is not cosmetic. That refusal blocked
four correctly-read 2018-19 fills, and the only honest way past it is to settle the convention.

THE THREE ROWS THAT MATTER, printed identically on every one of these statements:
   row  9  Profit/(loss) for the period/year (7-8)                             <- the TOTAL
   row 12  Total comprehensive income/(loss) above attributable to: - Owners…  <- NOT profit
   row 13  Of the total comprehensive income/(loss) above, (Loss)/profit for
           the period/year attributable to: - Owners of the parent             <- the OWNERS profit
Unit is "(₹ in Million)" throughout, so /10 to crore.

ROOT CAUSE, measured rather than guessed. A stored cell is on the owners convention exactly when
scripts/_reattr_owners.json holds it, and apply_reattr_cache.py only admits a cell when
abs((owners + nci) - total) <= max(1.0, abs(total)*0.02). Every "total" quarter fails that guard for
one of two reasons, both the filer's:
  * the XBRL omits ProfitOrLossAttributableToOwnersOfParent entirely
    (20190930, 20191231, 20200930, 20201231) — the ledger never saw the cell; or
  * the tag is present but carries ROW 12, the total-comprehensive-income owners
    (20210331 284.58, 20210630 124.19, 20210930 381.42, 20230331 250.62 cr) — owners+NCI then misses
    the total by tens of crore and the guard rejects it; in 20220630 the two owners tags are
    TRANSPOSED outright (the profit tag holds row 12's 119.05 and the comprehensive-income tag holds
    row 13's 164.45), and one quarter later, in 20220930, both are correct again.
Verified by hand on the Q4FY21 page: row 9 = 2,121.23 mn, row 12 = 2,845.78, row 13 = 2,086.06,
NCI 35.17 — and the XBRL tag holds 2,845,780,000.

EVIDENCE PER CELL. Every owners figure below was read from the filed consolidated statement (BSE
announcement attachments, rendered and read), owners + NCI reconciles to the printed total to the
paisa in all of them, and each is arbitrated by the filing's own basic EPS wherever NCI is large
enough to separate the two bases (e.g. Dec-2019 printed EPS 0.90 = 417.92mn/465.635m shares, which
is the owners figure; the total would print 0.87). Full per-cell records, with printed strings,
anchors and EPS arithmetic, are in the campaign reports _BFL_NORMALISE*.json.

THE PIN IS NOT OPTIONAL. apply_owners_full.py runs nightly (refresh-fundamentals.yml) and sets
npCon from _reattr_owners.json, so a bare edit here would be silently reverted for any cell that
ledger holds — the TATACOFFEE lesson recorded in that script. owners_basis_heals.json outranks the
cache there, so every corrected cell is pinned as "SYM|QE|patC" -> {"owners": …}.

SCOPE, stated honestly: all 29 stored consolidated quarters (20190630..20260630) were classified —
10 held the total and are corrected here, 19 already held owners and are untouched. The series has
no consolidated cell before 20190630, so nothing earlier is in question.

Run: python3 -X utf8 scripts/fill2020_tools/normalise_bharatforg_owners.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
SYM = "BHARATFORG"
TOL = 0.011

# qe -> (stored_total_now, owners_to_write, nci, annCon of the filing read)
CORRECT = {
    20190930: (205.48, 207.08, -1.59, 20191108),
    20191231: (40.44, 41.79, -1.35, 20200210),
    20200930: (-1.32, 0.03, -1.35, 20201103),
    20201231: (-210.45, -209.21, -1.24, 20210209),
    20210331: (212.12, 208.61, 3.52, 20210604),
    20210630: (152.75, 153.65, -0.90, 20210813),
    20210930: (270.45, 271.19, -0.74, 20211110),
    20211231: (422.00, 421.19, 0.81, 20220210),
    20220630: (160.37, 164.45, -4.08, 20220811),
    20230331: (127.74, 135.50, -7.76, 20230515),
}
# The 19 quarters NOT listed above already hold the printed owners figure and are left untouched.
# Two of them look like a third convention and are not: 20220930 stores 145.91 where the printed
# owners is 145.915, and 20260331 stores 232.56 where it is 232.565 — both are float artifacts of
# round(x/1e7, 2), reproducible, and the total is 4.36 cr / 0.89 cr away in each case, so the
# attribution is unambiguous.
NOTE = (
    "stored value was the printed TOTAL (row 9); replaced with the printed OWNERS profit "
    "(row 13), which is this project's declared basis for npCon. owners + NCI reproduces the "
    "printed total to the paisa, and the filing's own basic EPS reproduces the owners figure."
)
SRC = (
    "Bharat Forge Ltd consolidated financial results, the company's own filing for each quarter "
    "(BSE announcements, scrip 500493; two quarters sit under the 'Board Meeting' category "
    "because 'Result' returns empty for this scrip). Statements declare '(₹ in Million)'."
)
WHY_XBRL_WRONG = (
    "the filer's XBRL either omits ProfitOrLossAttributableToOwnersOfParent or fills "
    "it with row 12 (total-comprehensive-income owners), so _reattr_owners.json's "
    "reconciliation guard rejected the cell and it kept the total."
)


def load(p):
    return json.load(open(p, encoding="utf-8"))


def main():
    apply = "--apply" in sys.argv
    paths = {
        "fund_d": os.path.join(ROOT, "docs", "sf_fundamentals.json"),
        "fund_s": os.path.join(SCRIPTS, "fundamentals.json"),
        "rev_d": os.path.join(ROOT, "docs", "sf_revop.json"),
        "rev_s": os.path.join(SCRIPTS, "revop_fundamentals.json"),
        "pin": os.path.join(SCRIPTS, "owners_basis_heals.json"),
        "patdef": os.path.join(SCRIPTS, "pat_defects.json"),
    }
    st = {k: load(v) for k, v in paths.items()}

    for qe, (was, owners, nci, ann) in sorted(CORRECT.items()):
        for k in ("fund_d", "fund_s"):
            row = next((r for r in (st[k].get(SYM) or []) if r and r[0] == qe), None)
            if row is None:
                print(f"  .. {k} has no {SYM} row for {qe}")
                continue
            if row[3] is None or abs(row[3] - was) > TOL:
                print(
                    f"  !! {k} {qe} conPAT is {row[3]}, expected the total {was} — stopping, another writer "
                    "has been here"
                )
                return 1
            print("  %-8s %s conPAT %s -> %s   (NCI %s)" % (k, qe, row[3], owners, nci))
            if apply:
                row[3] = owners
        # sf_revop idx 5 is the patC MIRROR of npCon (runbook 70) — move it with the authority.
        for k in ("rev_d", "rev_s"):
            row = (st[k].get(SYM) or {}).get(str(qe))
            if not row or len(row) <= 5 or row[5] is None:
                continue
            if abs(row[5] - was) > TOL:
                print(f"  .. {k} {qe} patC mirror is {row[5]}, not the total {was} — left alone for a human")
                continue
            print("  %-8s %s patC mirror %s -> %s" % (k, qe, row[5], owners))
            if apply:
                row[5] = owners
        # THE PIN — without it apply_owners_full.py can re-assert the cached value nightly.
        st["pin"]["cells"]["%s|%d|patC" % (SYM, qe)] = {
            "owners": owners,
            "stored_before": was,
            "nci": nci,
            "annCon": ann,
            "note": NOTE,
            "source": SRC,
            "why_the_cache_was_wrong": WHY_XBRL_WRONG,
            "campaign": "con-params-L4 / BHARATFORG owners normalisation",
            "when": "2026-08-18",
        }
        st["patdef"].setdefault(SYM, {})[str(qe)] = {
            "correct_pat_con": owners,
            "stored_pat_con": was,
            "defect": NOTE,
            "source": SRC,
        }
        print("  pin      %s|%d|patC" % (SYM, qe))

    if not apply:
        print("\nDRY RUN — re-run with --apply to write")
        return 0
    for k in ("fund_d", "fund_s", "rev_d", "rev_s"):
        json.dump(st[k], open(paths[k], "w"), separators=(",", ":"))
    for k in ("pin", "patdef"):
        json.dump(st[k], open(paths[k], "w"), indent=1, sort_keys=True)
    print("\nWROTE 6 files. The four 2018-19 con fills are now free to land on the same convention.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

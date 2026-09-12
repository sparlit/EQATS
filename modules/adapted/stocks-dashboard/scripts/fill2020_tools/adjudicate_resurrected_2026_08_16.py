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
"""RESURRECTED-CELL ADJUDICATION 2026-08-16 — settle 4 cells FROM THE FILING, which is what the
holds themselves asked for.

WHERE THESE CAME FROM. At 17:00 IST today commit 561ddd75 ("FILL: 100 rev/op/ebit cells from
anchored XBRL re-extraction") wrote consolidated revenue for MINDTREE 2019-03/2020-03 and NESCO
2022-03/2022-06 into sf_revop from the NSE archive XBRL. Those same four cells were HELD in
scripts/mc_history_fills.json — a held cell asserts ABSENCE (§56b) — so the blocking
verify_fills_live.py step in refresh-fundamentals.yml started exiting 1 on RESURRECTED, aborting
the run BEFORE its commit step. Every fundamentals run from 17:15 IST failed, auto-rerun.yml
retried each one 5×, and each attempt mailed a failure notice: ~60 emails in three hours, and no
fundamentals payload published for the whole window. The emails were the symptom; the contradiction
was the cause.

★ TWO LEDGERS, CONTRADICTORY VERDICTS, SAME CELL — the shape §56b's 2026-08-11 pass already named.
nse_xbrl_rev_fills.json claims "this cell MUST equal 1839.4"; mc_history_fills.json claims "this
cell must be ABSENT". Both are registered in verify_fills_live.py, so whichever applier ran last
decided the store and the guard was guaranteed to be red either way. Only a source that outranks
both can settle it.

★★★ THE HOLDS NAMED THEIR OWN EXIT. All four rest on the weak test "MC's consolidated == our
standalone, and this company consolidates differently elsewhere" — which cannot separate the
aggregator repeating standalone from a company whose consolidated genuinely equals its standalone.
MINDTREE 2020-03's hold says so in as many words: "UNRESOLVED, not a proven copy ... Settle from
the filing (§57/§58), not this source." That is exactly what was done here, and the answer is that
a consolidated result WAS filed for every one of these quarters.

MEASURED 2026-08-16 by fetching each filing from the URL the fill journalled (nsearchives, HTTP 200,
parsed with ElementTree — not a render, not a summary):
  * every document self-declares NatureOfReportStandaloneConsolidated = "Consolidated";
  * its OneD context is exactly the target quarter — checked against DateOfStartOfReportingPeriod /
    DateOfEndOfReportingPeriod, NOT assumed. Three of the four are Q4 filings where FourD is the
    full year (70215000000 for MINDTREE FY19 against OneD's 18394000000); reading FourD as "the
    other basis" is this tool's own known bug (§88 head-note, 136 writes refused by its anchor gate
    on 2026-08-16). OneD was taken, and OneD is the quarter;
  * RevenueFromOperations on that context equals the value now live, to the paisa;
  * ProfitLossForPeriod on the SAME context equals the stored consolidated-PAT anchor, to the paisa
    — the anchor validates that the right document and the right context were read (it validates
    THAT field; the revenue is trusted because it shares the context, not because the anchor
    "proves" it).

So the value is right, the basis is right, and the hold is stale. Holds are lifted, no payload cell
changes. Lifting matters as much as retracting: verify_fills_live --repair-held NULLS anything still
flagged, so leaving these four in place arms a tool to delete four verified consolidated figures.

NOT CHANGED HERE: the 19 DRIFT rows the same detector reports are report-only by design (a later
correction may legitimately supersede a backfill) and none of them is what turned CI red.

Run: python3 -X utf8 scripts/fill2020_tools/adjudicate_resurrected_2026_08_16.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER = "mc_history_fills.json"

WHY = (
    "SETTLED FROM THE FILING 2026-08-16 — the route this hold itself named (§57/§58). NSE archive "
    "XBRL %s (filed %s) self-declares NatureOfReportStandaloneConsolidated=Consolidated, and its "
    "OneD context is exactly %s..%s, the target quarter (checked against the filing's own "
    "DateOfStart/EndOfReportingPeriod; the FourD context on the Q4 files is the FULL YEAR and was "
    "NOT used — reading FourD as 'the other basis' is a known bug of this tool). On that context "
    "RevenueFromOperations = %s = Rs %s cr, the value now live, and ProfitLossForPeriod = %s = "
    "Rs %s cr, matching the stored consolidated-PAT anchor %s to the paisa — so the right document "
    "and the right context were read. The earlier hold rested on 'MC consolidated == our "
    "standalone', which cannot tell an aggregator repeating standalone from a company whose "
    "consolidated genuinely equals its standalone; the primary document settles it — a consolidated "
    "result WAS filed for this quarter and its revenue is this number. Hold LIFTED; value stands, "
    "and is guarded from the other side by nse_xbrl_rev_fills.json."
)

# (sym, qe, ledger_rev, xbrl_rev_raw, xbrl_pat_raw, pat_anchor, ctx_start, ctx_end, filed, url)
# xbrl_*_raw are the literal strings in the filing, in rupees; /1e7 = Rs crore.
CELLS = [
    (
        "MINDTREE",
        20190331,
        1839.4,
        "18394000000.00",
        "1984000000.00",
        198.4,
        "2019-01-01",
        "2019-03-31",
        "23-Apr-2019 18:41",
        "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_43578_96014_17042019041708_WEB_2.xml",
    ),
    (
        "MINDTREE",
        20200331,
        2050.5,
        "20505000000.00",
        "2062000000.00",
        206.2,
        "2020-01-01",
        "2020-03-31",
        "08-May-2020 14:31",
        "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_54946_243786_24042020054626_WEB.xml",
    ),
    (
        "NESCO",
        20220331,
        91.07,
        "910655000.00",
        "535210000.00",
        53.52,
        "2022-01-01",
        "2022-03-31",
        "26-May-2022 13:41",
        "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_85494_661289_26052022014106_WEB.xml",
    ),
    (
        "NESCO",
        20220630,
        103.06,
        "1030591000",
        "537028000",
        53.7,
        "2022-04-01",
        "2022-06-30",
        "09-Aug-2022 12:22",
        "https://nsearchives.nseindia.com/corporate/xbrl/INDAS_640104_3242_09082022122211_WEB.xml",
    ),
]
TOL = 0.011


def main():
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP))
    path = os.path.join(SCRIPTS, LEDGER)
    led = json.load(open(path))

    lifted = 0
    for sym, qe, val, rev_raw, pat_raw, anchor, c0, c1, filed, url in CELLS:
        key = "%s|%d|con" % (sym, qe)
        e = led.get(key)
        if not isinstance(e, dict):
            print(f"  !! {key}: absent from {LEDGER} — nothing to lift")
            continue

        # Re-derive from the filing's own raw strings; never trust the summary line above.
        rev_cr = round(float(rev_raw) / 1e7, 2)
        pat_cr = round(float(pat_raw) / 1e7, 2)
        if abs(rev_cr - val) > TOL:
            print(f"  !! {key}: filing rev {rev_cr:.2f} != ledger rev {val:.2f} — NOT lifting")
            continue
        if abs(pat_cr - anchor) > TOL:
            print(f"  !! {key}: filing PAT {pat_cr:.2f} != anchor {anchor:.2f} — NOT lifting")
            continue
        row = (revop.get(sym) or {}).get(str(qe))
        cur = row[1] if row and len(row) > 1 else None
        if cur is None or abs(cur - val) > TOL:
            print(f"  !! {key}: live revC is {cur!r}, not {val} — re-adjudicate")
            continue

        if not e.get("held"):
            print(f"  -- {key}: already lifted")
            continue
        e.pop("held", None)
        e["fallback_check"] = WHY % (url, filed, c0, c1, rev_raw, rev_cr, pat_raw, pat_cr, anchor)
        lifted += 1
        print(
            "  LIFTED  %-10s %d con rev %-8s  filing=%s cr  PAT anchor %s == %s cr"
            % (sym, qe, val, rev_cr, anchor, pat_cr)
        )

    print("\nholds lifted %d  |  payload cells changed 0 (every value was already correct)" % lifted)
    if not apply_it:
        print("(dry run — re-run with --apply)")
        return
    json.dump(led, open(path, "w"), indent=1, sort_keys=True)
    print(f"APPLIED to {LEDGER}")


if __name__ == "__main__":
    main()

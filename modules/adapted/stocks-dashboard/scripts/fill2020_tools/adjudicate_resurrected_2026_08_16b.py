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
"""RESURRECTED-CELL ADJUDICATION 2026-08-16 (second wave) — settle 6 cells FROM THE FILING.

WHERE THESE CAME FROM. The first wave today (adjudicate_resurrected_2026_08_16.py, 18:49 IST) cleared
four held cells and CI went green. At 20:14 and 20:20 IST a sibling session pushed f24388563 ("FILL
MINDTREE con: 3 PAT quarters + 1 revenue, read from the filings") and 6ae9d2a81 ("FILL JUSTDIAL con:
2 PAT quarters from the per-basis XBRL"). Both fills are document-backed and journalled in the new
scripts/conpat_filing_fills.json — but neither lifted the matching `held` flags in
scripts/mc_history_fills.json / scripts/mc_pat_fills.json. A held cell asserts ABSENCE (§56b), so the
blocking verify_fills_live.py step in refresh-fundamentals.yml began exiting 1 on RESURRECTED=6 and
the fundamentals payload stopped publishing again from 20:18 IST. Same shape as the first wave: two
ledgers, contradictory verdicts, same cell.

★ THE HOLDS NAMED THEIR OWN EXIT, AGAIN. All six rest on the weak test "MC's consolidated == our
standalone, and this company consolidates differently elsewhere", which cannot separate an aggregator
repeating standalone from a company whose consolidated genuinely equals its standalone. MINDTREE
2019-12's hold says so in as many words: "Settle from the filing (§57/§58), not this source."

MEASURED 2026-08-16 22:2x IST BY A SECOND READER — I did not take the sibling fill's word for any of
it. Every filing was re-fetched from NSE this session and parsed with ElementTree (not a render, not
a summary), and for each quarter the CONSOLIDATED and the STANDALONE document were fetched
separately and diffed:

  * every consolidated document self-declares NatureOfReportStandaloneConsolidated = "Consolidated";
  * its OneD context is exactly the target quarter, read off the filing's own
    DateOfStartOfReportingPeriod / DateOfEndOfReportingPeriod — NOT assumed. On every one of these
    files FourD is the CUMULATIVE period (H1 or 9M), which is the FourD trap (§88 head-note);
  * ★ the con/std diff REFUTES the holds' premise. These are genuinely different documents, not one
    document filed twice: MINDTREE Q2/Q3 FY20 differ on OtherExpenses sub-contexts and only the
    consolidated file carries ShareOfProfitLossOfAssociates / ProfitOrLossAttributableToOwnersOfParent
    / NonControllingInterests; JUSTDIAL Q3FY24 differs on the 9-month PAT itself (con 247.19 vs std
    247.20). Consolidated equalling standalone AT THE QUARTER is a fact about these companies, not
    an aggregator artefact;
  * ★ and an arithmetic identity closes it. JUSTDIAL's 9M consolidated PAT 247.19 = 83.4 + 71.78 +
    92.01 to the paisa, and 71.78 is our stored Q2 con — which DIFFERS from our stored Q2 std 71.79.
    MINDTREE's H1 consolidated PAT 227.7 - Q2 135.0 = 92.7, and the same identity on revenue
    (3748.5 - 1914.3 = 1834.2) reproduces our stored Q1 con revenue exactly.

Holds are lifted; NO payload cell changes here. Lifting matters as much as retracting:
verify_fills_live --repair-held NULLS whatever is still flagged, so leaving these six in place arms a
tool to delete six verified consolidated figures ([[feedback-held-cell-asserts-absence]]).

NOT CHANGED HERE: the 19 DRIFT rows the same detector reports are report-only by design, and none of
them is what turned CI red.

Run: python3 -X utf8 scripts/fill2020_tools/adjudicate_resurrected_2026_08_16b.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)

SEEN = "SETTLED FROM THE FILING 2026-08-16 (second wave) — the route this hold itself named (§57/§58), re-read this session by a second reader, not taken from the sibling fill. "

# ledger -> key -> (value-key, expected value, evidence)
LIFTS = {
    "mc_history_fills.json": {
        "MINDTREE|20191231|con": (
            "rev",
            1965.3,
            SEEN
            + (
                "NSE per-basis XBRL https://nsearchives.nseindia.com/corporate/xbrl/"
                "INDAS_51419_199804_14012020045531_WEB.xml (filed 14-Jan-2020 16:55) self-declares "
                "NatureOfReportStandaloneConsolidated=Consolidated, and its OneD context is exactly "
                "2019-10-01..2019-12-31 — the target quarter, read off the filing's own "
                "DateOfStart/EndOfReportingPeriod (FourD on this file is 2019-04-01..2019-12-31, the "
                "9-month cumulative, and was NOT used). On OneD, RevenueFromOperations = 19653000000 = "
                "Rs 1965.3 cr, the value now live, and ProfitLossForPeriod = 1970000000 = Rs 197.0 cr, "
                "matching the stored consolidated-PAT anchor to the paisa, so the right document and the "
                "right context were read. The separately filed STANDALONE document "
                "(INDAS_51421_199826_14012020050007_WEB.xml) is a different document, not a copy: its "
                "OtherExpenses sub-contexts differ (2077.0 vs 2082.0 mn among others) and only the "
                "consolidated file carries ProfitOrLossAttributableToOwnersOfParent = 1970000000 with "
                "NonControllingInterests = 0. So con == std at the quarter is a fact about MindTree, not "
                "Moneycontrol repeating standalone — which is all the old hold could ever have shown."
            ),
        ),
    },
    "mc_pat_fills.json": {
        "MINDTREE|20190630|con": (
            "pat",
            92.7,
            SEEN
            + (
                "NO XBRL was filed for this quarter (NSE's index carries the '/-' placeholder URL), so "
                "TWO routes were walked. (1) NSE corporates-financial-results-data, seq_id 1064887, "
                "params 01-Apr-201930-Jun-2019Q1ANNCNEMINDTREE: the row self-declares "
                "conNonCon=Consolidated, periodEndDT=30-Jun-2019, filed 17-Jul-2019 18:37, and reports "
                "re_net_profit = 9270 (Rs lakh) = Rs 92.7 cr with re_net_sale = 183420 = Rs 1834.2 cr, "
                "which is the stored consolidated revenue for the same quarter. ⚠ On its own that row is "
                "weak evidence: NSE's Q1FY20 consolidated and standalone rows are identical apart from "
                "re_seq_num and re_share_associate. (2) The identity that settles it — the Q2FY20 "
                "CONSOLIDATED XBRL (INDAS_48607_151292_16102019045627_WEB_2.xml), a document proven "
                "distinct from its standalone twin, carries FourD = 2019-04-01..2019-09-30 (H1) with "
                "ProfitLossForPeriod = 2277000000 = Rs 227.7 cr; H1 minus its OneD quarter (135.0) = "
                "92.7, the value now live. The same subtraction on revenue (3748.5 - 1914.3 = 1834.2) "
                "reproduces the stored Q1 consolidated revenue exactly, so the identity is sound."
            ),
        ),
        "MINDTREE|20190930|con": (
            "pat",
            135.0,
            SEEN
            + (
                "NSE per-basis XBRL https://nsearchives.nseindia.com/corporate/xbrl/"
                "INDAS_48607_151292_16102019045627_WEB_2.xml (filed 16-Oct-2019 16:56) self-declares "
                "NatureOfReportStandaloneConsolidated=Consolidated, and its OneD context is exactly "
                "2019-07-01..2019-09-30 by the filing's own DateOfStart/EndOfReportingPeriod (FourD is "
                "2019-04-01..2019-09-30, the H1 cumulative, NOT used). On OneD, ProfitLossForPeriod = "
                "1350000000 = Rs 135.0 cr, the value now live, and RevenueFromOperations = 19143000000 = "
                "Rs 1914.3 cr, matching the stored consolidated-revenue anchor. The separately filed "
                "STANDALONE twin (INDAS_48607_151292_16102019045627_WEB.xml) differs on OtherExpenses "
                "sub-contexts and lacks the ShareOfProfitLossOfAssociatesAndJointVentures fact the "
                "consolidated file carries — a real consolidated table."
            ),
        ),
        "MINDTREE|20191231|con": (
            "pat",
            197.0,
            SEEN
            + (
                "NSE per-basis XBRL https://nsearchives.nseindia.com/corporate/xbrl/"
                "INDAS_51419_199804_14012020045531_WEB.xml (filed 14-Jan-2020 16:55), "
                "NatureOfReportStandaloneConsolidated=Consolidated, OneD = 2019-10-01..2019-12-31 by the "
                "filing's own period dates (FourD = the 9-month cumulative, NOT used). On OneD, "
                "ProfitLossForPeriod = 1970000000 = Rs 197.0 cr — and the consolidated file ALONE tags "
                "ProfitOrLossAttributableToOwnersOfParent = 1970000000 with NonControllingInterests = 0, "
                "which is the owners basis this store uses (§profit-basis). Its standalone twin "
                "(INDAS_51421_...) carries neither tag and differs on OtherExpenses, so the two documents "
                "are genuinely different and con == std here is MindTree's own result."
            ),
        ),
        "JUSTDIAL|20230630|con": (
            "pat",
            83.4,
            SEEN
            + (
                "NSE per-basis XBRL https://nsearchives.nseindia.com/corporate/xbrl/"
                "INDAS_94195_885841_14072023105951.xml (filed 14-Jul-2023 22:59) self-declares "
                "NatureOfReportStandaloneConsolidated=Consolidated, and its OneD context is exactly "
                "2023-04-01..2023-06-30 by the filing's own DateOfStart/EndOfReportingPeriod. On OneD, "
                "ProfitLossForPeriod = 834000000 = Rs 83.4 cr, the value now live, with "
                "RevenueFromOperations = 2469800000 = Rs 246.98 cr matching the stored consolidated "
                "revenue. Corroborated by the Q3FY24 consolidated filing's 9-month identity: its FourD "
                "PAT 247.19 = 83.4 + 71.78 + 92.01 to the paisa, where 71.78 is our stored Q2 con and "
                "DIFFERS from our stored Q2 std 71.79 — so Just Dial's consolidated series is real and "
                "this quarter's equality with standalone is a fact, not a fallback."
            ),
        ),
        "JUSTDIAL|20231231|con": (
            "pat",
            92.01,
            SEEN
            + (
                "NSE per-basis XBRL https://nsearchives.nseindia.com/corporate/xbrl/"
                "INDAS_101033_1019709_12012024105158.xml (filed 12-Jan-2024 22:51), "
                "NatureOfReportStandaloneConsolidated=Consolidated, OneD = 2023-10-01..2023-12-31 by the "
                "filing's own period dates. On OneD, ProfitLossForPeriod = 920100000 = Rs 92.01 cr, the "
                "value now live, RevenueFromOperations = 2650500000 = Rs 265.05 cr matching the stored "
                "consolidated revenue. ★ This file's FourD (9-month) PAT is 2471900000 = Rs 247.19 cr "
                "while the separately filed STANDALONE twin (INDAS_101032_...) reports 2472000000 = Rs "
                "247.20 cr on the same context — the consolidated document differs from the standalone "
                "document ON PAT ITSELF, which is exactly what the old hold assumed could not happen. "
                "And 247.19 = 83.4 + 71.78 + 92.01 to the paisa."
            ),
        ),
    },
}


def main():
    apply = "--apply" in sys.argv
    total = 0
    for fname, lifts in LIFTS.items():
        path = os.path.join(SCRIPTS, fname)
        led = json.load(open(path, encoding="utf-8"))
        changed = 0
        for key, (vkey, expect, why) in lifts.items():
            e = led.get(key)
            if e is None:
                print(f"  !! {fname} {key} — NOT IN LEDGER, skipped")
                continue
            if e.get(vkey) != expect:
                # the guard compares this stored value against the payload; if it moved, the
                # adjudication above was written against a different number and must be re-done.
                print(f"  !! {fname} {key} — ledger {vkey}={e.get(vkey)!r}, expected {expect!r}; NOT lifting")
                continue
            if "held" not in e:
                print(f"  == {fname} {key} — already lifted")
                continue
            print(f"  -> {fname} {key}  lift held, {vkey}={expect}")
            if apply:
                e.pop("held")
                e["fallback_check"] = why
                changed += 1
        total += changed
        if apply and changed:
            # same shape the file already has (indent=1, sort_keys, \uXXXX escapes, no trailing
            # newline) so the diff is the lifted entries and nothing else
            json.dump(led, open(path, "w"), indent=1, sort_keys=True)
            print("  WROTE %s (%d lifted)" % (fname, changed))
    print("\n%s: %d holds lifted" % ("APPLIED" if apply else "DRY RUN", total))
    if not apply:
        print("re-run with --apply to write")


if __name__ == "__main__":
    main()

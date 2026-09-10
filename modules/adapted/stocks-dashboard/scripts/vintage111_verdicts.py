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
"""§113 — the 59 verdicts on the §111i cross-campaign dispute, each naming the document and row.

The durable record of the reads. Hand-entered from the geometry row-dumps of the fetched filings
(`vintage111_documents.py` -> `vintage111_read.py`); `vintage111_adjudicate.py` reaches 13 of them
mechanically and agrees on every one. Consumed by `vintage111_land.py`, which writes these as
`confirmed_by_document` annotations onto the retracted entries in fund_cell_fix.json.

Every verdict here reverts to the pre-heal store; none backs the heal. The values were already
reverted by §112 before this finished — what these add is the EVIDENCE (§113a).
"""
import json
import os

SP = os.environ.get("V111_WORK", os.path.dirname(os.path.abspath(__file__)))

# tier: PRIMARY-A  owners row read for the target quarter, column map confirmed by >=1 other
#                  column on the SAME row reproducing a stored cell for a different quarter
#       PRIMARY-B  owners value from the filing via the statement's own identity
#                  (total - NCI, or the after-associates line), map confirmed the same way
#       PRIMARY-C  the company's own results filing/press release states the figure outright
#       XBRL-OWNERS  scripts/_reattr_owners.json (filings' ProfitOrLossAttributableToOwnersOfParent)
#       HEAL-DISQUALIFIED  no readable primary document for this cell; reverted because the heal's
#                  only evidence is disproved, NOT because the store was read
V = {
    "ADANIENT|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-10, consolidated audited statement: 'Net Profit attributable to: Owners of the Company' 188.29 / 350.55 / 220.97 / 757.25 / 987.74 cr. Cols 1-2 are our stored Mar-2018 and Dec-2017 cells exactly, so col 3 is the Mar-2017 quarter: 220.97. Reconciles: 'Profit for the period (9+10)' 218.80 and NCI -2.17 -> 220.97.",
    ),
    "BHARTIARTL|20170331": (
        "PRIMARY-A",
        "The OWN filing, BSE ann 2017-05-09, quarterly report p31 'Consolidated Statement of Comprehensive Income': 'Profit for the period Attributable to: Owners of the Parent 3,734 / Non-controlling interests 972' Rs Mn against a total of 4,706 = 373.4 cr owners. The heal's 219.8 is the archive page's own pre-associates line (219.8 + 250.8 = 470.6 total; 470.6 - 97.2 = 373.4).",
    ),
    "BIOCON|20170331": (
        "PRIMARY-A",
        "The OWN filing, BSE ann 2017-04-27, consolidated P&L (Rs Cr, Ind-AS column): 'NET PROFIT BEFORE MINORITY INTEREST 148 / Minority interest 21 / NET PROFIT FOR THE PERIOD 127'. The same table's Q3FY17 page reads 172/171 = our stored Dec-2016 171.3, so the convention is the after-minority line. 148.4 - 20.9 = 127.5. _reattr_owners agrees.",
    ),
    "CEATLTD|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-04-30 p10, 'Owners of the parent' 7,708 / 6,633 / 23,798 / 36,115 lakh = 77.08 / 66.33 / 237.98 / 361.15 cr. Col 1 is our stored Mar-2018 (77.08) exactly; this Q4 statement carries no Dec quarter, so col 2 is Mar-2017 = 66.33.",
    ),
    "CYIENT|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-04-19 p1 (both bases side by side): 'Shareholders of the Company' con = 118.4 / 87.8 / 78.4 / 405.4 / 343.8 (Rs mn/10). Cols 1-2 are our stored Mar-2018 and Dec-2017 exactly. Reconciles: 'Net Profit for the period' 77.1 and NCI -1.3 -> 78.4. The heal's 73.8 is the archive line before the associate share (73.8 + 3.3 = 77.1).",
    ),
    "DRREDDY|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-07-26 p11: 'Net profit after taxes and share of profit of associates' 4,761 / 2,721 / 666 / 9,468 Rs mn = our stored Jun-2018, Mar-2018 and Jun-2017 cells to the paisa, and its 'Attributable to: Equity holders' row is identical (NCI is nil for this group). So our slot is the after-associates line; for Mar-2017 that is 327.4 + 10.2 = 337.6. MC owners 337.6.",
    ),
    "EIDPARRY|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-09 p12: 'Owners of the Company' 11.33 / 40.12 / 247.68 / ... cr, cols 1-2 our stored Mar-2018 and Dec-2017 exactly; NCI row 29.15 / 67.79 / 52.70. Mar-2017 owners 247.68, total 300.38.",
    ),
    "EROSMEDIA|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-05-23 p11: 'Equity holders of Eros International Media Limited' 6,079 / 6,504 / 3,371 / 22,934 / 25,745 lakh; col 2 = our stored Dec-2017 (65.04) exactly, so col 3 is Mar-2017 = 33.71.",
    ),
    "FCONSUMER|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-08-08 p5: 'Profit/(Loss) for the year attributable to: -Owners of the company' (590.62) / (362.99) / (884.57) lakh = -5.91 / -3.63 / -8.85 = our stored Jun-2018, Mar-2018 and Jun-2017 cells exactly, so this slot holds the owners line. For Mar-2017 the archive page's own components give total -11.38 and NCI -1.29 -> owners -10.09.",
    ),
    "GODREJPROP|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-04 p11: 'Profit after Tax' 141.51 / 25.94 / 62.59 / 234.96 / 206.80 cr with 'Profit attributable to: Equity holders of Parent' on the same figures; col 1 is our stored Mar-2018 (141.51) exactly. Mar-2017 = 62.59. _reattr_owners agrees.",
    ),
    "GRASIM|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-23 p7: 'Owners of the Company' 720.09 / 543.18 / 774.54 / 2,678.58 / 3,167.30 cr; col 1 = our stored Mar-2018 (720.09) exactly, so col 3 is Mar-2017 = 774.54. The OWN filing (BSE ann 2017-05-19 p21) states it as 'Net profit for the quarter ... at 775' beside 757 for Mar-2016 = our stored Mar-2016 cell. Reverting to the stored 775.0; the filing's exact figure is 774.54 (0.06% apart).",
    ),
    "HTMEDIA|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-02 p10: 'Net Profit after tax for the period (5-6)' 8,536 / 13,696 / 4,397 lakh and 'Net Profit after taxes, non-controlling interest and share of associates' 7,504 / 12,436 / 2,555 lakh. Cols 1-2 of the second row are our stored Mar-2018 (75.04) and Dec-2017 (124.36) exactly. Mar-2017 owners 25.55; the heal's 43.97 is the row ABOVE it, before NCI.",
    ),
    "JKTYRE|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-17 p6: 'Owners of the Parent' 145.37 / 10.97 / 88.80 / 66.04 / 375.40 cr; cols 1-2 are our stored Mar-2018 (145.37) and Dec-2017 (10.97) exactly. Mar-2017 owners 88.80.",
    ),
    "MAHLIFE|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-07-30 p10: 'Profit for the period attributable to: Owners of the parent' 2,670 / 4,775 / 1,381 lakh = our stored Jun-2018 (26.70), Mar-2018 (47.6) and Jun-2017 (13.81), and p13 states 'consolidated PAT, post minority interest' 26.7 — so this slot is the post-minority line. For Mar-2017 the archive page's components give total 19.46 and NCI 2.06 -> owners 17.40, exactly the stored value.",
    ),
    "MOTHERSON|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-05-23 p10: 'Profit/(loss) for the period' 757.50 / 561.71 / 705.86 cr and '- Non-controlling interests' 239.14 / 197.22 / 231.08. Mar-2017: 705.86 - 231.08 = 474.78 exactly. The heal's 663.51 is the archive line before the associate share (663.51 + 42.35 = 705.86).",
    ),
    "PEL|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-28 p12: 'Owners of Piramal Enterprises Limited' 3,943.95 / 490.92 / 310.96 / 5,121.49 / 252.33 cr; cols 1-2 are our stored Mar-2018 and Dec-2017 exactly. Mar-2017 owners 310.96, against 'Net Profit after tax' 296.09 (the heal) and 'after tax and share of associates' 310.67. Piramal's own presentation p24 states 311 for Q4FY17.",
    ),
    "PENIND|20160630": (
        "PRIMARY-C",
        "The company's own results releases: BSE ann 2017-08-14 p8 'Net Profit ... 10.7 vs 7.8' and BSE ann 2017-11-10 p12 'Net Profit ... 7.7 / 5.5' cr for the Jun quarters — 7.8/7.7 against a stored 7.81. The heal's 10.02 is the archive bottom line.",
    ),
    "PRESTIGE|20170331": (
        "XBRL-OWNERS",
        "Every filing on record for this quarter is a scan. scripts/_reattr_owners.json, built from the filings' XBRL ProfitOrLossAttributableToOwnersOfParent, holds 89.25 for this cell = the pre-heal store. The heal's 111.10 is the archive bottom line.",
    ),
    "RAYMOND|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-04-24 p11: '- Owners' 5,311 / 2,884 / 3,294 / 13,453 / 2,552 lakh; cols 1-2 are our stored Mar-2018 (53.10) and Dec-2017 (28.84) exactly, NCI 137 / 187 / 74. Mar-2017 owners 32.94 against a total of 33.68. _reattr_owners agrees.",
    ),
    "STLTECH|20160630": (
        "PRIMARY-C",
        "The company's own release for the SAME quarter one year on, BSE ann 2017-07-19 p1: 'Profit After Tax at Rs 61 crore, up 61% vs Rs 38 crore YoY' — 38 against a stored 37.75. The heal's 40.0 is the archive bottom line.",
    ),
    "STLTECH|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-04-25 p28: 'a) Owners of the Company' 112.42 / 90.09 / 63.66 / 201.38 cr; cols 1-2 are our stored Mar-2018 and Dec-2017 exactly. Mar-2017 owners 63.66, against 'Net Profit after Tax & Share in Loss of Joint Venture' 68.67 = the heal. The OWN filing's release (2017-04-26) says 'PAT at Rs 64 crore vs Rs 55 crore', 55 = our stored Mar-2016.",
    ),
    "SUNPHARMA|20170331": (
        "PRIMARY-C",
        "The OWN filing, BSE ann 2017-05-26 p1: 'Q4 Net Profit at Rs. 1223 crores ... down 14% over Q4 last year' — the stored 1223.71. The heal's 1344.52 is the archive line before NCI (the Mar-2018 statement prints NCI of 128-287 cr per quarter for this group).",
    ),
    "TATACONSUM|20161231": (
        "XBRL-OWNERS",
        "The Dec-2017 filing that would carry this quarter as its comparative is a scan. _reattr_owners holds 127.63 = the pre-heal store. Corroborated by the Mar-2018 filing's structure for the sibling quarter (below): our slot is 'Owners of the Parent', two lines below the 'Net Profit after Tax' the heal took.",
    ),
    "TATACONSUM|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-11 p7: 'Net Profit after Tax' ... 84.36 ... ; 'Group Consolidated Net Profit (A)' 71.56 / 188.64 / 51.12 ; 'Owners of the Parent' ... / 167.87 / 31.41 / 495.56 / 389.44 cr. Col 2 of the owners row is our stored Dec-2017 (167.87) exactly. Mar-2017 owners 31.41 — the heal's 84.36 is two lines above it. _reattr_owners agrees.",
    ),
    "THERMAX|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-18 p2: 'Net Profit after tax and share in profit/(loss) of joint ventures' 75.69 / 58.58 / 35.31 cr (cols 1-2 our stored Mar-2018 and Dec-2017 exactly) and 'Net profit attributable to: Equity holders' 75.69 / 58.58 / 43.66. Mar-2017 owners 43.66 = 35.31 + 8.35, the archive page's own NCI row. MC's 35.31 is the TOTAL, not the owners figure.",
    ),
    "TMPV|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-05-23 p12: 'Non-controlling interests' 49.92 / 15.97 / 40.58 / 102.45 / 102.20 cr. With the archive page's total (3,925.88 + 410.55 associate share = 4,336.43), Mar-2017 owners = 4,336.43 - 40.58 = 4,295.85 exactly the stored value.",
    ),
    "TRIVENI|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-24 p12: '(i) Owners of the Company' -10,209 / 6,007 / 6,046 / 11,914 / 25,295 lakh; cols 1-2 are our stored Mar-2018 (-102.09) and Dec-2017 (60.07) exactly. Mar-2017 owners 60.46, against p15's 'Profit/(loss) after tax' 5,726 = the heal.",
    ),
    "TV18BRDCST|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-04-24 p6: 'Profit/(loss) for the period attributable to: (a) Owners of the Company' (298) / 1,606 / 839 / 862 / 1,907 lakh, NCI 191 / (19) / (239). Cols 1-2 are our stored Mar-2018 (-2.98) and Dec-2017 (16.06) exactly. Mar-2017 owners 8.39 = total 6.00 - NCI (-2.39).",
    ),
    "VBL|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-05-03 p2: 'Net profit/(loss) for the period (5-6)' 197.38 / (721.29) / 68.94 Rs mn and 'Non-controlling interest' 11.06 / 7.15 / 23.86. Mar-2017: 68.94 - 23.86 = 45.08 mn = 4.51 cr, the stored value. _reattr_owners agrees.",
    ),
    "VIYASH|20170331": (
        "PRIMARY-A",
        "BSE ann 2018-05-24 p5: '-Owners of the Company' 39,954.9 / (945.91) / 682.25 / 42,156.6 lakh; col 1 is our stored Mar-2018 (399.55) exactly. Mar-2017 owners 6.82; the same row via total-minus-NCI gives 682.25 too.",
    ),
    "WABAG|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-05-26 p0: 'Owners of the parent' 5,965 / 3,006 / 7,573 / 13,151 / 10,240 lakh and 'Non-controlling interests' 377 / 577 / 375. Col 1 is our stored Mar-2018 (59.65) exactly. Mar-2017 owners 75.73; total 79.48 — which is exactly what MC serves as its 'owners' figure, so MC was on the total here.",
    ),
    "WELCORP|20170331": (
        "PRIMARY-B",
        "BSE ann 2018-05-02 p12: '-Owners' (452) / 6,639 / 7,338 / 15,830 lakh and '-Non-controlling interest' (311) / 270 / (479). Col 2 is our stored Dec-2017 (66.39) exactly, so col 3 is Mar-2017 = 73.38. The heal's 98.09 is the archive bottom line.",
    ),
    # --- the year-later comparative disagrees with BOTH candidates: a vintage question, not an
    #     owners-vs-total one. Reverted (the heal has no owners-side support either way) and the
    #     comparative recorded so it is not lost.
    "ELECON|20170331": (
        "REVERT+VINTAGE",
        "BSE ann 2018-05-04 p6 reads 3,004.72 lakh (30.05 cr) for the Mar-2017 column of 'Net Profit after tax and non-controlling interest', with cols 1-2 our stored Mar-2018 (53.38) and Dec-2017 (-2.37) exactly. That is 0.35 from the stored 29.70 and 2.87 from the heal's 27.18, so the heal is wrong either way; whether 29.70 or 30.05 is the as-filed figure is a §109 vintage question, logged not guessed. MC owners 29.70.",
    ),
    "NAVA|20170331": (
        "REVERT+VINTAGE",
        "BSE ann 2018-05-30 p7 reads 3,699.18 lakh (36.99 cr) for the Mar-2017 column of '- Shareholders of the Company', with cols 1-2 our stored Mar-2018 (173.54) and Dec-2017 (22.74) exactly. Neither candidate: 5.18 from the stored 42.17, 9.63 from the heal's 46.62. A year-later comparative can be restated (§109a), so the as-filed figure stays open; the heal is the further of the two and MC owners is 42.17.",
    ),
    "TATAPOWER|20170331": (
        "REVERT+VINTAGE",
        "BSE ann 2018-05-02 p1 reads -242.48 cr for the Mar-2017 column of the owners row under 'Profit/(Loss) for the Quarter/Year attributable to:', cols 1-2 our stored Mar-2018 (1403.73) and Dec-2017 (611.50) exactly, NCI 15.55. FY18 restated Mar-2017 for discontinued operations, so this is not the as-filed figure; it is 19.97 from the stored -262.45 and 336.86 from the heal's -579.34. MC owners -262.45.",
    ),
    # --- no readable primary document for the cell itself
    "ALLCARGO|20170331": ("HEAL-DISQUALIFIED", None),
    "ANANTRAJ|20170331": ("HEAL-DISQUALIFIED", None),
    "ANSALAPI|20170331": ("HEAL-DISQUALIFIED", None),
    "CANDC|20170331": (
        "HEAL-DISQUALIFIED",
        "No MC owners corroboration either (MC serves 41.55, a third value) — the revert rests only on the heal's evidence being disqualified.",
    ),
    "CARBORUNIV|20170331": ("HEAL-DISQUALIFIED", None),
    "CEMPRO|20170331": ("HEAL-DISQUALIFIED", None),
    "COX&KINGS|20170331": (
        "HEAL-DISQUALIFIED",
        "No MC owners corroboration either (MC serves -3.65, a third value) — the revert rests only on the heal's evidence being disqualified.",
    ),
    "EICHERMOT|20170331": ("HEAL-DISQUALIFIED", None),
    "EMBDL|20170331": ("HEAL-DISQUALIFIED", None),
    "GRANULES|20170331": ("HEAL-DISQUALIFIED", None),
    "HFCL|20170331": ("HEAL-DISQUALIFIED", None),
    "INDUSTOWER|20170331": (
        "HEAL-DISQUALIFIED",
        "The archive page's own components do reconcile here (269.40 + 327.20 JV share = 596.60, no NCI in this group), and MC owners is 596.60 — but that is the same page the heal came from, so it is corroboration, not a primary read.",
    ),
    "JINDALSTEL|20170331": (
        "XBRL-OWNERS",
        "The Mar-2018 filing's statement pages are scans. _reattr_owners holds -49.51 = the pre-heal store, and the Q1FY19 filing's 'Owners of the equity' row reproduces our stored Jun-2018 (180.83) and Jun-2017 (-387.09) exactly, so this slot is the owners line. The heal's -98.37 is the group total (the archive page's associate row makes it -100.01, which is what MC serves).",
    ),
    "PHOENIXLTD|20170331": ("HEAL-DISQUALIFIED", None),
    "RAIN|20170331": ("HEAL-DISQUALIFIED", None),
    "SITINET|20170331": ("HEAL-DISQUALIFIED", None),
    "SUPREMEIND|20170331": (
        "HEAL-DISQUALIFIED",
        "The Mar-2018 filing prints no attributable split; its segment table gives 145.90 for the Mar-2017 column against a stored 146.40 and a heal of 127.31, and MC serves 148.16. Every reader is within 2 cr of the store and 19 cr from the heal, but none of them is a clean owners read.",
    ),
    "TATACHEM|20170331": ("HEAL-DISQUALIFIED", None),
    "TECHM|20160630": ("HEAL-DISQUALIFIED", None),
    "THOMASCOOK|20160930": ("HEAL-DISQUALIFIED", None),
    "THOMASCOOK|20161231": ("HEAL-DISQUALIFIED", None),
    "THOMASCOOK|20170331": ("HEAL-DISQUALIFIED", None),
    "WOCKPHARMA|20170331": ("HEAL-DISQUALIFIED", None),
    "ZYDUSLIFE|20170331": ("HEAL-DISQUALIFIED", None),
}
if __name__ == "__main__":
    sel = json.load(open(os.path.join(SP, "declined67.json")))
    con = {k[:-4] for k in sel if sel[k]["fix"]["basis"] == "con"}
    missing, extra = con - set(V), set(V) - con
    print("cells %d  verdicts %d  missing %s  extra %s" % (len(con), len(V), sorted(missing), sorted(extra)))
    from collections import Counter

    print(Counter(t for t, _ in V.values()))

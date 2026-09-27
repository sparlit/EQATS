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
"""Regression test for fetch_annual_bscf.locate() — the strict markers plus the RELAXED second pass
(2026-09-26). Each case is a synthetic PDF shaped like a real filing that was measured failing:
  BEL / ASTRAL FY25   title + Total Assets on page i, Trade payables + the "Total equity and
                      liabilities" footing on the NEXT, untitled page
  ANANTRAJ FY21       "Total OF equity and liabilities"; title on the liabilities half
  BEL FY25            "Assets & Liabilities" (ampersand)
  BHARTIARTL FY25     a segment "assets and liabilities" schedule followed by a cash-flow page
                      carrying "trade payables" — must NOT pair into a balance sheet
plus the invariants: the strict path is unchanged, want_basis='s' keeps the standalone page
(PROZONER, §148), an upgrade to consolidated never borrows the standalone cash flow, and a PDF
that is not the FY-end result returns None. Offline — builds PDFs in memory, no network.

Run: python3 scripts/test_abscf_locate.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = [sys.argv[0]]
sys.path.insert(0, HERE)
import fetch_annual_bscf as F
import fitz

ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


def mkpdf(*pages):
    doc = fitz.open()
    for text in pages:
        p = doc.new_page()
        y = 60
        for line in text.strip().split("\n"):
            p.insert_text((50, y), line.strip(), fontsize=9)
            y += 13
    return doc.tobytes()


YE = "Audited results for the year ended 31 March 2025"
CF_CON = "Consolidated Statement of Cash Flows for the year ended 31 March 2025\nNet cash from operating activities 90\nNet cash used in investing activities (40)\nNet cash used in financing activities (30)"
CF_STD = "Standalone Statement of Cash Flows for the year ended 31 March 2025\nNet cash from operating activities 50\nNet cash used in investing activities (20)"

# 1. title-first split (BEL/ASTRAL FY25)
pdf = mkpdf(
    YE,
    "Consolidated Statement of Assets and Liabilities as at 31 March 2025\nProperty, plant and equipment 40\nTotal assets 100\nEQUITY AND LIABILITIES\nEquity share capital 10",
    "Particulars\nTrade payables 5\nTotal equity and liabilities 100",
    CF_CON,
)
r = F.locate(pdf, 2025)
check(
    "title-first split -> consolidated pages [1,2]",
    r is not None and r[0] == "c" and list(r[1]) == [1, 2] and r[2] == 3,
)

# 2. segment schedule + cash-flow page must not pair (BHARTIARTL trap)
pdf = mkpdf(
    YE,
    "Audited Consolidated Segment-wise Revenue, Results, Assets and Liabilities\nSegment assets 60\nTotal assets 100",
    CF_CON + "\nIncrease in trade payables 3",
)
check("segment page + cash-flow page is NOT a balance sheet", F.locate(pdf, 2025) is None)

# 3. "Total OF equity and liabilities", title on the liabilities half, assets on the page before (ANANTRAJ FY21)
pdf = mkpdf(
    "Audited results for the year ended 31 March 2021",
    "ASSETS\nProperty, plant and equipment 30\nTotal assets 80",
    "Audited Consolidated Statement of Assets and Liabilities\nLIABILITIES\nFinancial liabilities 20\nTotal of equity and liabilities 80",
)
r = F.locate(pdf, 2021)
check(
    '"Total of equity and liabilities" on titled liab half -> [1,2]',
    r is not None and r[0] == "c" and list(r[1]) == [1, 2],
)

# 4. ampersand in the FOOTING and no "trade payables" line: the strict liabilities marker needs "and"
pdf = mkpdf(
    YE,
    "Consolidated Balance Sheet as at 31 March 2025\nTotal assets 100\nEquity share capital 10\nTotal Equity & Liabilities 100",
)
r = F.locate(pdf, 2025)
check(
    '"Total Equity & Liabilities" footing (no trade payables) found',
    r is not None and r[0] == "c" and list(r[1]) == [1],
)

# 5. strict path unchanged: a normal one-page consolidated BS
pdf = mkpdf(
    YE, "Consolidated Balance Sheet as at 31 March 2025\nTotal assets 100\nTrade payables 5\nTotal equity 60", CF_CON
)
r = F.locate(pdf, 2025)
check("strict single-page consolidated BS unchanged", r == ("c", [1], 2))

# 6. both bases present, want_basis='s' keeps the standalone page (PROZONER, §148)
pdf = mkpdf(
    YE,
    "Standalone Balance Sheet as at 31 March 2025\nTotal assets 70\nTrade payables 4\nTotal equity 40",
    CF_STD,
    "Consolidated Balance Sheet as at 31 March 2025\nTotal assets 100\nTrade payables 5\nTotal equity 60",
    CF_CON,
)
r = F.locate(pdf, 2025, "s")
check(
    "want_basis='s' -> standalone BS + standalone CF", r is not None and r[0] == "s" and list(r[1]) == [1] and r[2] == 2
)
r = F.locate(pdf, 2025, "c")
check(
    "want_basis='c' -> consolidated BS + consolidated CF",
    r is not None and r[0] == "c" and list(r[1]) == [3] and r[2] == 4,
)

# 7. strict finds only standalone; relaxed finds the consolidated split -> upgrade, CF on the same basis
pdf = mkpdf(
    YE,
    "Standalone Balance Sheet as at 31 March 2025\nTotal assets 70\nTrade payables 4\nTotal equity 40",
    CF_STD,
    "Consolidated Statement of Assets and Liabilities as at 31 March 2025\nTotal assets 100\nEquity share capital 10",
    "Trade payables 5\nTotal equity and liabilities 100",
    CF_CON,
)
r = F.locate(pdf, 2025)
check(
    "upgrade std -> consolidated split, consolidated CF",
    r is not None and r[0] == "c" and list(r[1]) == [3, 4] and r[2] == 5,
)
check("upgrade suppressed when want_basis='s'", F.locate(pdf, 2025, "s")[0] == "s")

# 8. upgrade never borrows the standalone cash flow
pdf = mkpdf(
    YE,
    "Standalone Balance Sheet as at 31 March 2025\nTotal assets 70\nTrade payables 4\nTotal equity 40",
    CF_STD,
    "Consolidated Statement of Assets and Liabilities as at 31 March 2025\nTotal assets 100\nEquity share capital 10",
    "Trade payables 5\nTotal equity and liabilities 100",
)
r = F.locate(pdf, 2025)
check(
    "consolidated upgrade with no consolidated CF -> CF None (never the standalone one)",
    r is not None and r[0] == "c" and r[2] is None,
)

# 8b. strict path: consolidated BS, and the only cash flow sits in the STANDALONE section before it
#     (AUROPHARMA FY21: BS p27, CF p3; ALLCARGO FY20: BS p21, CF p10 — both FAR from Screener's consolidated
#     cash flow) -> CF None, never the standalone statement in a consolidated cell
pdf = mkpdf(
    YE,
    "Standalone Balance Sheet as at 31 March 2025\nTotal assets 70\nTrade payables 4\nTotal equity 40",
    CF_STD,
    "Consolidated Balance Sheet as at 31 March 2025\nTotal assets 100\nTrade payables 5\nTotal equity 60",
)
r = F.locate(pdf, 2025)
check(
    "strict consolidated BS with only a standalone CF in a two-basis filing -> CF None",
    r is not None and r[0] == "c" and r[2] is None,
)
# ...but an UNLABELLED cash flow right after the consolidated BS is its own (BIRLACORPN FY20 BS p8 -> CF p9, CIPLA,
#     PNBHOUSING: all MATCH Screener's consolidated cash flow)
CF_BARE = "Statement of Cash Flows for the year ended 31 March 2025\nNet cash from operating activities 95"
pdf = mkpdf(
    YE,
    "Standalone Balance Sheet as at 31 March 2025\nTotal assets 70\nTrade payables 4\nTotal equity 40",
    CF_STD,
    "Consolidated Balance Sheet as at 31 March 2025\nTotal assets 100\nTrade payables 5\nTotal equity 60",
    CF_BARE,
)
r = F.locate(pdf, 2025)
check("unlabelled cash flow right after the consolidated BS pairs with it", r == ("c", [3], 4))
# ...but a SINGLE-basis filing whose cash-flow title does not repeat the word keeps it
pdf = mkpdf(
    YE,
    "Consolidated Balance Sheet as at 31 March 2025\nTotal assets 100\nTrade payables 5\nTotal equity 60",
    "Statement of Cash Flows for the year ended 31 March 2025\nNet cash from operating activities 90",
)
r = F.locate(pdf, 2025)
check("single-basis filing: an unlabelled cash-flow page still pairs with the consolidated BS", r == ("c", [1], 2))

# 9. not the FY-end filing -> None, whatever the markers say
pdf = mkpdf(
    "Unaudited results for the quarter ended 30 June 2025",
    "Consolidated Balance Sheet\nTotal assets 100\nTrade payables 5\nTotal equity 60",
)
check("no FY-end date -> None", F.locate(pdf, 2025) is None)

print("ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)

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
"""Offline tests for the annual BS/CF pipeline changes of 2026-09-26 (wave 2). Each case is shaped
like a real filing that was measured failing:
  1. result_filings() asks BOTH strCat=Result and "Board Meeting / Outcome of Board Meeting" — a
     Result-only list lacked AUROPHARMA 2025-05, BALKRISIND 2023-05 + 2025-05, PFIZER 2020-04 +
     2024-05 + 2025-05. Result rows stay first, a 403 on either category aborts, duplicates collapse.
  2. cf_span(): a cash-flow statement that continues onto the next page (BEL FY20/21/22/25, DIVISLAB
     FY22, NFL FY22, SUNPHARMA FY25) -> [i, i+1]; a complete statement, or a NEW statement on the next
     page, -> [i].
  3. text_read() reads both cash-flow pages, the wordings the old labels missed ("NET CASH FROM
     OPERATING ACTIVITIES" — NFL; "Net cash inflow from operating activities" — DIVISLAB), capex, and
     drops cfo/cfi/cff when the statement's own identity cfo + cfi + cff (+ FX effect) = net change in
     cash FAILS.
  4. iuad (intangible assets under development) is its own line — never folded into intg or cwip.
  3c. income tax is SIGNED by the statement's own arithmetic, + paid / - net refund (§168j; GESHIP FY22 adds its
     9.47 = a refund, ATUL FY20 subtracts an unbracketed 216.77 = a payment); unprovable -> unread.
  5. merge: iuad lands; the validate year's cash flow lands as a CF-only cell (v=1) when the slice has
     no CF for that year (PFIZER FY25), never when it has; a fill whose CF identity fails keeps its BS
     but loses its CF; 'supplement' entries only fill null fields of the SAME document's cell, and only
     when their re-read anchor (Total Assets, or CFO / the CF identity) matches.
Offline — builds PDFs in memory, fakes the BSE API, writes only to a temp dir.
Run: python3 scripts/test_abscf_pipeline.py
"""
import json
import os
import sys
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = [sys.argv[0]]
sys.path.insert(0, HERE)
import fetch_annual_bscf as F
import fitz
import merge_annual_bscf as M

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


# ---- 1. discovery asks both categories ---------------------------------------------------------
calls = []


def fake_get(o, u, b=False):
    calls.append(u)
    if "strCat=Result" in u:
        return json.dumps({"Table": [{"ATTACHMENTNAME": "q1.pdf", "NEWS_DT": "2025-08-13T10:00:00"}]})
    if "strCat=Board%20Meeting" in u:
        return json.dumps(
            {
                "Table": [
                    {"ATTACHMENTNAME": "fy.pdf", "NEWS_DT": "2025-05-20T10:00:00"},
                    {"ATTACHMENTNAME": "q1.pdf", "NEWS_DT": "2025-08-13T10:00:00"},
                    {"ATTACHMENTNAME": "", "NEWS_DT": "2025-05-02T10:00:00"},
                ]
            }
        )
    return json.dumps({"Table": []})


F._FILINGS_LOADED, F._FILINGS = True, None  # no override: exercise the API path
orig_get = F.get
F.get = fake_get
r = F.result_filings(None, 500680, "20250401", "20250901")
check(
    "both categories queried (Board Meeting with its Outcome subcategory)",
    any("strCat=Result" in u for u in calls)
    and any("strCat=Board%20Meeting" in u and "subcategory=Outcome%20of%20Board%20Meeting" in u for u in calls),
)
check(
    "Result rows first, the Board-Meeting annual added, duplicate attachment collapsed",
    r == [(20250813, "q1.pdf"), (20250520, "fy.pdf")],
)


def fake_403(o, u, b=False):
    if "Board%20Meeting" in u:
        raise urllib.error.HTTPError(u, 403, "Forbidden", {}, None)
    return json.dumps({"Table": []})


F.get = fake_403
try:
    F.result_filings(None, 500680, "20250401", "20250901")
    blocked = False
except F.BseBlocked:
    blocked = True
check('403 on the Board-Meeting query aborts (never reads as "no filings")', blocked)
F.get = orig_get

# ---- 1b. BSE_PDF_CACHE: a filing is downloaded once --------------------------------------------
pdf_calls = []


def fake_pdf(o, u, b=False):
    pdf_calls.append(u)
    return b"%PDF-1.4 fake"


F.get = fake_pdf
os.environ["BSE_PDF_CACHE"] = tempfile.mkdtemp()
d1 = F.download(None, "x1.pdf")
d2 = F.download(None, "x1.pdf")
check(
    "BSE_PDF_CACHE: second download of the same attachment is served from the cache",
    d1 == d2 == b"%PDF-1.4 fake" and len(pdf_calls) == 1,
)
del os.environ["BSE_PDF_CACHE"]
F.get = orig_get

# ---- 2. cash-flow continuation -----------------------------------------------------------------
OPS = (
    "Consolidated Statement of Cash Flows for the year ended 31 March 2025\n"
    "A. Cash flow from operating activities\nNet cash from operating activities 90"
)
INVFIN = (
    "Particulars\nB. Cash flow from investing activities\nNet cash used in investing activities (40)\n"
    "C. Cash flow from financing activities\nNet cash used in financing activities (30)\n"
    "Cash and cash equivalents at the end of the year 20"
)
FULL = OPS + "\n" + INVFIN.replace("Particulars\n", "")
NEWSTD = (
    "Standalone Statement of Cash Flows for the year ended 31 March 2025\n"
    "A. Cash flow from operating activities\nNet cash from operating activities 50\n"
    "B. Cash flow from investing activities"
)
check("statement continues -> [i, i+1]", F.cf_span([OPS, INVFIN], 0) == [0, 1])
check("complete statement -> [i]", F.cf_span([FULL, INVFIN], 0) == [0])
check(
    "incomplete page followed by a NEW statement -> [i] (never pairs two statements)",
    F.cf_span([OPS, NEWSTD], 0) == [0],
)
check("last page -> [i]", F.cf_span([OPS], 0) == [0])
check("no CF page -> []", F.cf_span([OPS], None) == [])

# ---- 3 + 4. text_read: two CF pages, wider labels, capex, identity, iuad ------------------------
YE = "Audited results for the year ended 31 March 2025"
BS = (
    "Consolidated Balance Sheet as at 31 March 2025\n(Rs. in crore)\nProperty, plant and equipment 400.00\n"
    "Capital work-in-progress 30.00\nOther intangible assets 20.00\nIntangible assets under development 12.50\n"
    "Total assets 1000.00\nEquity share capital 10.00\nOther equity 600.00\nTrade payables 50.00\n"
    "Total equity and liabilities 1000.00"
)
CF1 = (
    "Consolidated Statement of Cash Flows for the year ended 31 March 2025\n(Rs. in crore)\n"
    "A. Cash flow from operating activities\nCash generated from operations 115.00\nIncome taxes paid (net) (25.00)\n"
    "Net cash inflow from operating activities (A) 90.00"
)
CF2 = (
    "Particulars\nB. Cash flow from investing activities\nPurchase of property, plant and equipment (35.00)\n"
    "Proceeds from sale of property, plant and equipment 5.00\n"
    "Net cash inflow/ (outflow) from investing activities (B) (40.00)\nC. Cash flow from financing activities\n"
    "Net cash inflow/ (outflow) from financing activities (C) (30.00)\n"
    "Net increase/(decrease) in cash and cash equivalents (A+B+C) 20.00\n"
    "Cash and cash equivalents at the end of the year 70.00"
)
pdf = mkpdf(YE, BS, CF1, CF2)
loc = F.locate(pdf, 2025)
check("locate: BS p1, CF p2", loc is not None and list(loc[1]) == [1] and loc[2] == 2)
p = F.text_read(pdf, loc[1], loc[2])
check(
    "two-page CF: cfo / cfi / cff / capex / cf_tax all read",
    (p.get("cfo"), p.get("cfi"), p.get("cff"), p.get("capex"), p.get("cf_tax")) == (90.0, -40.0, -30.0, 35.0, 25.0),
)
check(
    "iuad is its own line; intg and cwip unchanged",
    p.get("iuad") == 12.5 and p.get("intg") == 20.0 and p.get("cwip") == 30.0,
)
check("no internal CF helper keys leak into the read", not any(k in p for k in ("cf_net", "cf_fx")))
bad = mkpdf(YE, BS, CF1, CF2.replace("(A+B+C) 20.00", "(A+B+C) 55.00"))
p2 = F.text_read(bad, loc[1], loc[2])
check(
    "CF identity FAILS -> cfo/cfi/cff dropped (capex, cf_tax, BS kept)",
    p2.get("cfo") is None
    and p2.get("cfi") is None
    and p2.get("cff") is None
    and p2.get("capex") == 35.0
    and p2.get("assets") == 1000.0,
)
CFW = (
    "Statement of Cash Flows for the year ended 31 March 2025\nNET CASH FROM OPERATING ACTIVITIES 100.00\n"
    "Net cash (used in)/from investing activities (60.00)\nNet cash (used in) financing activities (10.00)\n"
    "Effect of exchange rate changes on cash and cash equivalents 2.00\n"
    "Net increase in cash and cash equivalents 32.00"
)
pw = F.text_read(mkpdf(YE, BS, CFW), [1], 2)
check(
    '"NET CASH FROM OPERATING" / "(used in)" wordings read; identity holds with the FX term',
    (pw.get("cfo"), pw.get("cfi"), pw.get("cff")) == (100.0, -60.0, -10.0),
)
CFB = CFW.replace(
    "Net increase in cash and cash equivalents 32.00",
    "Net (increase)/decrease in bank balances not considered as cash and cash equivalents (7.00)\n"
    "Net increase in cash and cash equivalents 32.00",
)
pb = F.text_read(mkpdf(YE, BS, CFB), [1], 2)
check('a "bank balances not considered as cash" line is not taken as the net change', pb.get("cfo") == 100.0)


# ---- 3b. text-layer traps, each copied from a real filing ---------------------------------------
def cf_of(*lines):
    pdf = mkpdf(YE, BS, "Statement of Cash Flows for the year ended 31 March 2025\n" + "\n".join(lines))
    return F.text_read(pdf, [1], 2)


BASE = ["Depreciation 10.00 9.00", "Interest paid (5.00) (4.00)", "Dividend paid (2.00) (1.00)"]
r = cf_of(
    "Net cash generated from operating activities 2 103 70 4,110.45",
    "Net cash used in investing activities (221.97) (2,289.32)",
    "Net cash used in financing activities (1,975.33) (1,851.82)",
    *BASE,
)
check(
    'HEROMOTOCO FY22: "2 103 70" (a split 2,103.70) is unreadable, never CFO 2.0',
    r.get("cfo") is None and r.get("cfi") == -221.97,
)
r = cf_of(
    "Net cash flow from operating activities 3,958.35 2,199.40",
    "Net cash flow from investing activities (2,619.23) 1 403.70",
    "Net cash flow from financing activities (1,139.84) 600.65",
    "Net increase or (decrease) in cash or cash equivalents 199.28 195.05",
    *BASE,
)
check(
    "NATIONALUM FY22: a split in the PRIOR-year column leaves the current-year value readable", r.get("cfi") == -2619.23
)
r = cf_of(
    "Net cash flow from operating activities (A) 38,402 1,21,200",
    "Purchase of property, plant and equipment and intangible assets 1 (4,142) (4,267)",
    "Income tax paid (net) (20,0601 (18,757)",
    *BASE,
)
check(
    'KRBL FY21: note marker "1" dropped (capex 4,142); garbled "(20,0601" is unreadable, never the prior year',
    r.get("capex") == 4142.0 and r.get("cf_tax") is None,
)
r = cf_of(
    "Net Cash Flow from/(used in) Operating Activities (A) 2048.54 (29241.29)",
    "Net Cash Flow from/(used in) Investing Activities (8) 2972.48 519.34",
    "Net Cash Flow from/(used in) Financing Activities (C) (4827.83) 28665.25",
    "Net lncrease/(Decrease) in Cash and Cash Equivalents (A+B+C) 193.19 (56.70)",
    *BASE,
)
check(
    'VINDHYATEL FY20: "(B)" OCR\'d as "(8)" is a marker; cfi 2,972.48 and the identity holds',
    r.get("cfi") == 2972.48 and r.get("cfo") == 2048.54,
)
r = cf_of(
    "Net cash flow from operating activities (A) 977,11 509.55",
    "Net cash flow (used in) investing activities (B) (646.83) (434.92)",
    "Net cash flow (used in) financing activities (C) (358.55) (77.83)",
    "Net increase in Cash and cash equivalents (A+B+C) (28.27) (3.20)",
    *BASE,
)
check(
    'APLAPOLLO FY21: "977,11" (a decimal comma) is unreadable, never 97,711',
    r.get("cfo") is None and r.get("cfi") == -646.83,
)
r = cf_of(
    "Net cash flow from I (used in) from operating activities before income-tax 1,804.06 378.51",
    "Income-tax paid (197.48) (106.85)",
    "Net cash flow from I (used in) operating activities 1,609.65 271.66",
    "Net cash flow from I (used in) investing activities (150.74) (307.91)",
    "Net cash from I (used in ) financing activities (1,459.54) (36.64)",
    "Net change in cash and cash equivalents (0.63) (72.89)",
    *BASE,
)
check(
    "BAJAJHLDNG FY22: the before-tax operating sub-total is skipped (cfo 1,609.65); tax unread — 1,804.06 - 197.48 != 1,609.65, so its direction is unprovable",
    r.get("cfo") == 1609.65 and r.get("cf_tax") is None,
)
r = cf_of(
    "Cash generated from operations 2,887.78 5,091.23",
    "Less: Direct taxes paid (net of refund) 784.08 980.78",
    "Net cash generated from operating activities 2,103.70 4,110.45",
    "Net cash used in investing activities (221.97) (2,289.32)",
    "D. DECREASE IN CASH AND CASH EQUIVALENTS (A+B+C) (93.60) (30.69)",
    *BASE,
)
check(
    'HEROMOTOCO FY22: "Less: Direct taxes paid 784.08" is SUBTRACTED (2,887.78 - 784.08 = 2,103.70) -> +784.08, paid',
    r.get("cf_tax") == 784.08,
)
# ---- 3d. note references and split figures on the balance sheet (runbook §168k) --------------------------
BSN = (
    "Consolidated Balance Sheet as at 31 March 2025\n(Rs. in crore)\nProperty, plant and equipment 400.00 380.00\n"
    "Total assets 1000.00 950.00\n(a) Equity Share Capital (Refer Note 2) 1,966.88 1,966.88\n"
    "(b) Other Equity 1,37, 101.38 1,38,282.87\nTrade payables 50.00 45.00\nTotal equity and liabilities 1000.00 950.00"
)
pn = F.text_read(mkpdf(YE, BSN), [1], None)
check('BPCL FY20: "(Refer Note 2)" is a note reference, never share capital 2.0 -> 1,966.88', pn.get("sc") == 1966.88)
check('BALMLAWRIE FY21: an OCR split "1,37, 101.38" is rejoined -> 137,101.38, never 1.37', pn.get("oeq") == 137101.38)
BSN2 = BSN.replace("(Refer Note 2) 1,966.88 1,966.88", "Note 12 1,966.88 1,966.88").replace(
    "1,37, 101.38 1,38,282.87", "1,234, 5,678.90"
)
pn2 = F.text_read(mkpdf(YE, BSN2), [1], None)
check('a number right after the word "Note" is a note, not the value', pn2.get("sc") == 1966.88)
check('two real columns never merge ("1,234," + "5,678.90" is not a grouped number)', pn2.get("oeq") != 12345678.9)

# ---- 3c. income tax is SIGNED by the statement's own arithmetic (+ paid, - net refund; runbook §168j) --------
r = cf_of(
    "Cash generated from operations 1313.09 1535.74",
    "Direct taxes paid/ (refund) 9.47 (1.57)",
    "Net cash (used in)/generated from operating activities 1322.56 1534.17",
    *BASE,
)
check(
    'GESHIP FY22: "Direct taxes paid/ (refund) 9.47" is ADDED (1,313.09 + 9.47 = 1,322.56) -> -9.47, a refund',
    r.get("cf_tax") == -9.47,
)
r = cf_of(
    "Cash generated from operating activities 1,098.15 657.72",
    "Income tax paid (net of refund) 216.77 254.14",
    "Net cash flow from operating activities A 881.38 403.58",
    *BASE,
)
check(
    "ATUL FY20: an unbracketed 216.77 that is SUBTRACTED (1,098.15 - 216.77 = 881.38) -> +216.77, paid",
    r.get("cf_tax") == 216.77,
)
r = cf_of(
    "Cash generated from operations 251.39 300.00",
    "Income taxes paid (258.00) (100.00)",
    "Refund of income taxes 666.88 26.26",
    "Net cash from operating activities 660.27 226.26",
    *BASE,
)
check(
    "BHEL FY22: payment and refund on separate lines -> their net, -408.88 (a net refund)", r.get("cf_tax") == -408.88
)
r = cf_of("Income tax paid (50.00) (40.00)", "Net cash from operating activities 100.00 90.00", *BASE)
check(
    'no "cash generated from operations" line -> direction unprovable -> tax unread (never a guess)',
    r.get("cf_tax") is None and r.get("cfo") == 100.0,
)
r = cf_of(
    "Cash generated from operations 100.00 90.00",
    "Income tax paid (0.01) (0.02)",
    "Net cash from operating activities 99.99 89.98",
    *BASE,
)
check("a tax line too small to tell paid from refund at the printed precision -> unread", r.get("cf_tax") is None)
r = cf_of(
    "Cash generated from operations 1676 1500",
    "Income taxes paid (284) (250)",
    "Net cash from operating activities 1392 1250",
    *BASE,
)
check("whole-crore statement (TORNTPHARM-style): 1,676 - 284 = 1,392 -> +284", r.get("cf_tax") == 284.0)
r = cf_of(
    "NET CASH FROM OPERATING ACTIVITIES (82594) 703380 (102915) 702125",
    "NET CASH FROM INVESTING ACTIVITIES (33251) (50923) (12930) (49668)",
    "NET CASH FROM FINANCING ACTIVITIES 114494 (650477) 114494 (650477)",
    "Depreciation 10 9 11 10",
    "Interest paid (5) (4) (6) (5)",
)
check(
    "NFL FY22: standalone + consolidated side by side (4 columns) -> cash flow NOT read from text",
    r.get("cfo") is None and r.get("cfi") is None and r.get("cff") is None and r.get("_cf_layout") == "multi",
)
r = cf_of(
    "Net cash from operating activities 515.65 317.00",
    "Effect of Exchange Differences on Translation of Foreign Currency Cash & Cash Equivalents (10.66) (11.60)",
    "NET CASH FROM INVESTING ACTIVITIES 183.45 38.37",
    "NET CASH FROM FINANCING ACTIVITIES (707.92) (419.03)",
    "NET INCREASE/(DECREASE) IN CASH AND CASH EQUIVALENTS 1.84 (52.06)",
    "Effect of Exchange Differences on Translation of Foreign Currency Cash & Cash Equivalents 10.66 11.60",
    *BASE,
)
check(
    "RITES FY21: the LAST FX-effect line closes the identity (the first is an operating adjustment)",
    (r.get("cfo"), r.get("cfi"), r.get("cff")) == (515.65, 183.45, -707.92),
)
r = cf_of(
    "Net cash flow from operating activities (A) 651.71 977,11",
    "Net cash flow (used in) investing activities (B) (530.13) (646.83)",
    "Net cash flow from / (used in) financing activities (C) 26.03 (358.55)",
    "Net increase / (decrease) in cash and cash equivalents (A+B+C) 147:<61 (28.27)",
    *BASE,
)
check(
    'APLAPOLLO FY22: a garbled net change "147:<61" is unreadable — the PRIOR year (-28.27) never slides in',
    (r.get("cfo"), r.get("cfi"), r.get("cff")) == (651.71, -530.13, 26.03) and r.get("_cf_net") is None,
)
r = cf_of(
    "Net cash flow from operating activities A 231.45 717.95",
    "Net cash used in investing activities 8 (167.65) (646.39)",
    "Net cash used in financing activities (57.44) (52.19)",
    "Net increase I (decrease) in cash and cash equivalents A+B+C 6.36 19.37",
    *BASE,
)
check(
    'ATUL FY22: "8 (167.65)" = a marker before a complete bracketed figure (cfi -167.65; identity 6.36 holds)',
    r.get("cfi") == -167.65 and r.get("_cf_ok") is True,
)
r = cf_of(
    "Net cash generated from operating activities 122,722.54 82,355.30",
    "Income tax paid (net) (63,772.87) (13,194.64)",
    "Net cash generated from operating activities 58,949.67 69,160.66",
    "Net cash used in investing activities 201,153.24 (20,922.94)",
    "Net cash used in financing activities (103,315.51) (47,574.14)",
    "Net increase/ (decrease) in cash and cash equivalents 156,787.40 663.58",
    *BASE,
)
check(
    'HGS FY22: two lines both called "Net cash generated from operating activities" — the identity picks the post-tax one',
    (r.get("cfo"), r.get("cfi"), r.get("cff"), r.get("_cf_ok")) == (58949.67, 201153.24, -103315.51, True),
)
r = cf_of(
    "Net cash generated from operating activities 34.963 23,980",
    "Net cash used in investing activities (2,253) (6,750)",
    "Net cash used in financing activities (28,903) (17,565)",
    "Net increase/ (decrease) in cash and cash equivalents 3,817 (263)",
    *BASE,
)
check(
    'VEDL FY22: "34.963" (a comma read as a point) fails the identity and no other line solves it -> triple dropped',
    r.get("cfo") is None and r.get("cfi") is None and r.get("_cf_ok") is False,
)
check(
    'ANANTRAJ FY21: "1, 143.00" (a split 1,143.00) is unreadable, never Rs 1',
    F.to_num("1,") is None and F.to_num("1,143.00") == 1143.0 and F.to_num("(1,21,200)") == -121200.0,
)


# ---- 4b. scanned pages + side-by-side bases: the text layer is not trusted for landing ------------
def mkpdf_ocr(*pages):
    """Pages shaped like an OCR'd scan: a full-page image with the text as an INVISIBLE layer on top."""
    doc = fitz.open()
    for text in pages:
        p = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 80), False)
        pix.clear_with(230)
        p.insert_image(p.rect, pixmap=pix)
        y = 60
        for line in text.strip().split("\n"):
            p.insert_text((50, y), line.strip(), fontsize=9, render_mode=3)
            y += 13
    return doc.tobytes()


pdf = mkpdf_ocr(YE, BS, CF1, CF2)
loc = F.locate(pdf, 2025)
r = F.text_read(pdf, loc[1], loc[2]) if loc else {}
check(
    "an OCR-layer balance sheet is flagged (_bs_ocr) and its BS fields are withheld",
    loc is not None and r.get("_bs_ocr") is True and r.get("assets") is None and r.get("iuad") is None,
)
check(
    "...its cash flow is kept only because the cash identity verifies it",
    (r.get("cfo"), r.get("cfi"), r.get("cff"), r.get("_cf_ok")) == (90.0, -40.0, -30.0, True)
    and r.get("capex") is None,
)
check(
    "the same pages as a DIGITAL filing are read in full",
    F.text_read(mkpdf(YE, BS, CF1, CF2), [1], 2).get("assets") == 1000.0,
)
SBS = (
    "Statement of Assets and Liabilities as at 31 March 2025\nStandalone Consolidated\n(Rs. in crore)\n"
    "Property, plant and equipment 400.00 380.00 410.00 390.00\nTotal assets 1000.00 950.00 1050.00 990.00\n"
    "Equity share capital 10.00 10.00 10.00 10.00\nOther equity 600.00 550.00 610.00 560.00\n"
    "Trade payables 50.00 45.00 52.00 47.00\nTotal equity and liabilities 1000.00 950.00 1050.00 990.00"
)
r = F.text_read(mkpdf(YE, SBS, CF1, CF2), [1], 2)
check(
    "TRENT FY21: standalone + consolidated side by side (4 columns) -> BS flagged multi and withheld",
    r.get("_bs_layout") == "multi" and r.get("assets") is None,
)

# ---- 5. merge ----------------------------------------------------------------------------------
tmp = tempfile.mkdtemp()
M.LEDGER = os.path.join(tmp, "annual_bscf.json")
M.FIN_DIR = os.path.join(tmp, "fin")
os.makedirs(M.FIN_DIR)


def slice_(sym, x):
    json.dump({"x": x}, open(os.path.join(M.FIN_DIR, sym + ".json"), "w"))


slice_("TSTA", {"20250331": {"s": {"assets": 1000.0, "ppe": 400.0}}})  # BS held, NO cash flow
slice_("TSTB", {"20250331": {"s": {"assets": 1000.0, "ppe": 400.0, "cfo": 91.0}}})  # BS and CF held
json.dump(
    {
        "TSTC": {
            "20210331": {"b": "c", "m": "vision", "src": "bse:c.pdf", "assets": 500.0, "ppe": 200.0, "cwip": 3.0},
            "20220331": {"b": "c", "m": "text", "src": "bse:d.pdf", "assets": 600.0, "ppe": 210.0, "cfo": 80.0},
        }
    },
    open(M.LEDGER, "w"),
)
VAL = {
    "role": "validate",
    "fy": 2025,
    "basis": "s",
    "key": {"assets": 1000.0, "ppe": 400.0},
    "assets": 1000.0,
    "ppe": 400.0,
    "cfo": 90.0,
    "cfi": -40.0,
    "cff": -30.0,
    "capex": 35.0,
    "cf_tax": 25.0,
    "cf_net": 20.0,
    "src": "bse:v.pdf",
}
FILL = {
    "role": "fill",
    "fy": 2021,
    "basis": "s",
    "assets": 800.0,
    "ppe": 300.0,
    "iuad": 5.5,
    "cwip": 10.0,
    "cfo": 70.0,
    "cfi": -20.0,
    "cff": -10.0,
    "cf_net": 40.0,
    "capex": 12.0,
    "src": "bse:f.pdf",
    "asat": "2021-03-31",
}
reads = [
    dict(VAL, sym="TSTA"),
    dict(FILL, sym="TSTA"),
    dict(VAL, sym="TSTB"),
    dict(FILL, sym="TSTB", fy=2022, cf_net=99.0, asat="2022-03-31"),
    # supplements: iuad onto the stored cell (cwip never overwritten); wrong document; anchor off 5%; no cell
    {
        "sym": "TSTC",
        "fy": 2021,
        "role": "supplement",
        "basis": "c",
        "src": "bse:c.pdf",
        "assets": 500.2,
        "iuad": 4.0,
        "cwip": 99.0,
    },
    {"sym": "TSTC", "fy": 2021, "role": "supplement", "basis": "c", "src": "bse:OTHER.pdf", "assets": 500.0, "gw": 1.0},
    {"sym": "TSTC", "fy": 2021, "role": "supplement", "basis": "c", "src": "bse:c.pdf", "assets": 525.0, "intg": 2.0},
    {"sym": "TSTC", "fy": 2020, "role": "supplement", "basis": "c", "src": "bse:c.pdf", "assets": 500.0, "iuad": 1.0},
    # CF supplement: stored cfo matches -> cfi/cff added; the 2021 cell has no cfo -> needs the identity
    {
        "sym": "TSTC",
        "fy": 2022,
        "role": "supplement",
        "basis": "c",
        "src": "bse:d.pdf",
        "cfo": 80.3,
        "cfi": -50.0,
        "cff": -20.0,
    },
    {
        "sym": "TSTC",
        "fy": 2021,
        "role": "supplement",
        "basis": "c",
        "src": "bse:c.pdf",
        "cfo": 60.0,
        "cfi": -30.0,
        "cff": -10.0,
        "cf_net": 25.0,
    },
]
rp = os.path.join(tmp, "reads.json")
json.dump(reads, open(rp, "w"))
sys.argv = [sys.argv[0], rp]
M.main()
L = json.load(open(M.LEDGER))
a = L.get("TSTA", {})
check("fill lands iuad", a.get("20210331", {}).get("iuad") == 5.5)
check("fill with a passing CF identity keeps cfo/cfi/cff", a.get("20210331", {}).get("cfo") == 70.0)
check(
    "validate year lands as a CF-only cell (v=1) when the slice has no CF",
    a.get("20250331")
    == {
        "b": "s",
        "m": "vision",
        "src": "bse:v.pdf",
        "v": 1,
        "cfo": 90.0,
        "cfi": -40.0,
        "cff": -30.0,
        "capex": 35.0,
        "cf_tax": 25.0,
    },
)
b = L.get("TSTB", {})
check("validate year NOT landed when the slice already holds its CF", "20250331" not in b)
check(
    "fill whose CF identity fails: BS landed, cfo/cfi/cff dropped",
    b.get("20220331", {}).get("assets") == 800.0 and all(b["20220331"].get(k) is None for k in ("cfo", "cfi", "cff")),
)
c = L.get("TSTC", {})
check(
    "supplement adds iuad, never overwrites cwip, records provenance",
    c["20210331"].get("iuad") == 4.0 and c["20210331"].get("cwip") == 3.0 and "iuad" in c["20210331"].get("sup", []),
)
check("supplement from a different document is rejected", c["20210331"].get("gw") is None)
check("supplement whose Total-Assets anchor is off 5% is rejected", c["20210331"].get("intg") is None)
check("supplement never creates a cell", "20200331" not in c)
check(
    "CF supplement: stored CFO matches -> cfi/cff added, cfo kept",
    (c["20220331"].get("cfo"), c["20220331"].get("cfi"), c["20220331"].get("cff")) == (80.0, -50.0, -20.0),
)
check(
    "CF supplement without a stored CFO needs the identity (60-30-10 != 25 -> rejected)",
    c["20210331"].get("cfo") is None,
)

# ---- 6. merge 'correct': a verified re-read of a TEXT cell's own document fixes the old parser ----
json.dump(
    {
        "HERO": {
            "20220331": {
                "b": "c",
                "m": "text",
                "src": "bse:h.pdf",
                "assets": 24000.0,
                "ppe": 5000.0,
                "cfo": 2.0,
                "cfi": -221.97,
                "cff": -1975.33,
                "cf_tax": -784.08,
            }
        },
        "VIND": {
            "20200331": {
                "b": "s",
                "m": "text",
                "src": "bse:v.pdf",
                "assets": 900.0,
                "ppe": 100.0,
                "cfo": 20.49,
                "cfi": -0.08,
                "cff": -48.28,
            }
        },
        "KEEP": {
            "20210331": {
                "b": "c",
                "m": "text",
                "src": "bse:k.pdf",
                "assets": 500.0,
                "ppe": 50.0,
                "cfo": 30.0,
                "cfi": -10.0,
                "cff": -5.0,
            }
        },
        "VISN": {
            "20210331": {
                "b": "c",
                "m": "vision",
                "src": "bse:n.pdf",
                "assets": 500.0,
                "ppe": 50.0,
                "cfo": 30.0,
                "cfi": -10.0,
                "cff": -5.0,
            }
        },
        "GESH": {
            "20220331": {
                "b": "c",
                "m": "text",
                "src": "bse:g.pdf",
                "assets": 9000.0,
                "ppe": 700.0,
                "cfo": 1322.56,
                "cf_tax": 9.47,
            }
        },
    },
    open(M.LEDGER, "w"),
)
reads = [  # HERO: re-read cannot read the split CFO; the statement's own net change (-93.60) contradicts the stored triple
    {
        "sym": "HERO",
        "fy": 2022,
        "role": "correct",
        "basis": "c",
        "src": "bse:h.pdf",
        "assets": 24000.0,
        "cfo": None,
        "cfi": -221.97,
        "cff": -1975.33,
        "cf_net": -93.60,
        "cf_tax": 784.08,
    },
    # VIND: the re-read triple passes the identity -> replaces the misread cfi
    {
        "sym": "VIND",
        "fy": 2020,
        "role": "correct",
        "basis": "s",
        "src": "bse:v.pdf",
        "assets": 900.2,
        "cfo": 20.49,
        "cfi": 29.72,
        "cff": -48.28,
        "cf_net": 1.93,
    },
    # KEEP: re-read disagrees but NOTHING verifies it (no net line) -> untouched
    {
        "sym": "KEEP",
        "fy": 2021,
        "role": "correct",
        "basis": "c",
        "src": "bse:k.pdf",
        "assets": 500.0,
        "cfo": 31.0,
        "cfi": -10.0,
        "cff": -5.0,
    },
    # VISN: a vision cell is never "corrected" by a text re-read
    {
        "sym": "VISN",
        "fy": 2021,
        "role": "correct",
        "basis": "c",
        "src": "bse:n.pdf",
        "assets": 500.0,
        "cfo": 40.0,
        "cfi": -10.0,
        "cff": -5.0,
        "cf_net": 25.0,
    },
    # GESH: the signed re-read says the 9.47 was a REFUND -> the stored +9.47 (the old positive-only rule) flips
    {
        "sym": "GESH",
        "fy": 2022,
        "role": "correct",
        "basis": "c",
        "src": "bse:g.pdf",
        "assets": 9000.0,
        "cfo": 1322.56,
        "cf_tax": -9.47,
    },
]
json.dump(reads, open(rp, "w"))
sys.argv = [sys.argv[0], rp]
M.main()
L = json.load(open(M.LEDGER))
h = L["HERO"]["20220331"]
check(
    "HERO FY22: the split-figure CFO 2.0 is removed (net change contradicts it), cfi/cff kept, tax sign fixed, old values kept in fix",
    "cfo" not in h
    and h["cfi"] == -221.97
    and h["cf_tax"] == 784.08
    and h.get("fix") == {"cfo": 2.0, "cf_tax": -784.08},
)
v = L["VIND"]["20200331"]
check(
    "VIND FY20: a re-read that passes the cash identity replaces the misread cfi (-0.08 -> 29.72)",
    v["cfi"] == 29.72 and v.get("fix") == {"cfi": -0.08},
)
check(
    "an unverified disagreement changes nothing",
    L["KEEP"]["20210331"]
    == {
        "b": "c",
        "m": "text",
        "src": "bse:k.pdf",
        "assets": 500.0,
        "ppe": 50.0,
        "cfo": 30.0,
        "cfi": -10.0,
        "cff": -5.0,
    },
)
check(
    "a vision cell is never corrected by a text re-read",
    L["VISN"]["20210331"]["cfo"] == 30.0 and "fix" not in L["VISN"]["20210331"],
)
g = L["GESH"]["20220331"]
check(
    "GESH FY22: a stored +9.47 that the signed re-read proves a refund becomes -9.47 (old value kept in fix)",
    g["cf_tax"] == -9.47 and g.get("fix") == {"cf_tax": 9.47},
)

# ---- 7. unit slip: every shared field exactly k x the independent re-read -> rescale ------------
json.dump(
    {
        "ETRN": {
            "20220331": {
                "b": "c",
                "m": "text",
                "src": "bse:e.pdf",
                "assets": 173270.0,
                "sc": 7643.0,
                "oeq": 157412.0,
                "ppe": 509.0,
                "gw": 12093.0,
            }
        },
        "NEAR": {
            "20220331": {"b": "c", "m": "text", "src": "bse:n.pdf", "assets": 23096.09, "sc": 39.96, "oeq": 15000.0}
        },
    },
    open(M.LEDGER, "w"),
)
reads = [
    {
        "sym": "ETRN",
        "fy": 2022,
        "role": "supplement",
        "basis": "c",
        "src": "bse:e.pdf",
        "assets": 17327.0,
        "sc": 764.3,
        "oeq": 15741.2,
        "ppe": 50.9,
        "gw": 1209.3,
        "iuad": 0,
    },
    # 2.7% apart is NOT a unit slip: nothing changes
    {
        "sym": "NEAR",
        "fy": 2022,
        "role": "supplement",
        "basis": "c",
        "src": "bse:n.pdf",
        "assets": 22478.39,
        "sc": 39.96,
        "oeq": 14500.0,
        "iuad": 5.0,
    },
]
json.dump(reads, open(rp, "w"))
sys.argv = [sys.argv[0], rp]
M.main()
L = json.load(open(M.LEDGER))
e = L["ETRN"]["20220331"]
check(
    "ETERNAL FY22: every field exactly 10x the re-read -> cell rescaled to crore, old unit recorded, iuad supplemented",
    (e["assets"], e["sc"], e["oeq"], e["ppe"], e["gw"]) == (17327.0, 764.3, 15741.2, 50.9, 1209.3)
    and e.get("fix", {}).get("unit") == 10
    and e.get("iuad") == 0,
)
check(
    "a 2.7% gap is not a unit slip — the cell is untouched",
    L["NEAR"]["20220331"]
    == {"b": "c", "m": "text", "src": "bse:n.pdf", "assets": 23096.09, "sc": 39.96, "oeq": 15000.0},
)

print("ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)

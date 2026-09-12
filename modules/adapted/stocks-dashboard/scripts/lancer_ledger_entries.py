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
"""ONE-OFF: append the LANCER (Lancer Container Lines, BSE 539841) PAT heal to the two ledgers.

Run once, then `python -X utf8 scripts/scale_fix.py --apply` and
`python -X utf8 scripts/pat_defect_fix.py --apply`. Idempotent: re-running replaces the
LANCER entries rather than duplicating them.

Every value below was READ from a primary document this session (2026-08-10); the per-cell
anchor chain lives in each entry's `why` / `source`. Nothing here is inferred from neighbours.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- scale_fix (power-of-ten only)
SCALE = [
    {
        "sym": "LANCER",
        "qe": "20180331",
        "basis": "std",
        "k": 7,
        "file": None,
        "why": (
            "BSE-only scrip 539841 (ISIN INE359U01028); no NSE XBRL exists, the stored figure is the "
            "filing's RAW RUPEE print never divided by 1e7. PRIMARY: the 20-May-2019 audited filing "
            "(BSE ann 20190520, attachment a7c286eb-2351-4298-9f7d-9917dd609876.pdf) p4 'Statement of "
            "audited Financial Results ... 31st March, 2019 / Standalone results / (Figures in INR)' "
            "prints, on the row 'Profit/(Loss) for the period', column 'Quarter Ended 31.03.2018 "
            "(Audited)' = 21,816,965 -- byte-identical to the stored cell. TRUE = 2.18 cr. "
            "SECOND CHECK (independent): 9M-FY18 4,66,85,868 (20190213 filing) + 2,18,16,965 = "
            "6,85,02,833 = the same p4 table's 'Year Ended 31.03.2018' column, EXACT. THIRD: BSE "
            "detres 97.50 (FY18 audited annual) NP 68.45mn matches note 4's previous-GAAP 68,452,228. "
            "k=7 is proven twice more on this same document (20181231, 20190331 below)."
        ),
        "was_revop": {},
        "was_fund": 21816965.0,
        "fixed_fund": 2.18,
    },
    {
        "sym": "LANCER",
        "qe": "20181231",
        "basis": "std",
        "k": 7,
        "file": None,
        "why": (
            "Raw-rupee print stored as crore. PRIMARY: the 13-Feb-2019 own-quarter filing (BSE ann "
            "20190213, attachment 8d2a6723-bd49-4a31-a7c7-ae000b54bf67.pdf) p2 'Statement of Standalone "
            "Unaudited Financial Results for the Quarter and Nine months ended 31st December, 2018' "
            "prints 'Profit/(Loss) for the period', column 'Quarter Ended 31.12.2018' = 3,49,03,220 -- "
            "byte-identical to the stored cell. TRUE = 3.49 cr. SECOND: the 20190520 audited filing p4 "
            "repeats it as 34,903,220 in its 31.12.2018 comparative column. THIRD (positive control on "
            "the same page): the 30.09.2018 column 2,46,57,574 -> 2.47 == the cell we already store "
            "clean for 20180930. FOURTH: FY19 quarters 1.687+2.466+3.490+0.579 = 8.222 = the FY19 "
            "audited annual 82,224,336, EXACT."
        ),
        "was_revop": {},
        "was_fund": 34903220.0,
        "fixed_fund": 3.49,
    },
    {
        "sym": "LANCER",
        "qe": "20190331",
        "basis": "std",
        "k": 7,
        "file": None,
        "why": (
            "Raw-rupee print stored as crore. PRIMARY: the 20190520 audited filing p4, row "
            "'Profit/(Loss) for the period', column 'Quarter Ended 31.03.2019 (Audited)' = 5,789,416 -- "
            "byte-identical to the stored cell. TRUE = 0.58 cr. SECOND (different document, different "
            "unit): the 24-Jun-2020 audited filing (ann 20200624, ea35bbea-2cb7-4f8a-802e-7496619abf57) "
            "p5, '(Rs in Lakh)', column 'Quarter Ended 31.03.2019' = 57.89 lakh = 0.5789 cr. THIRD: BSE "
            "detres 101.00 Net Profit 5.79 mn."
        ),
        "was_revop": {},
        "was_fund": 5789416.0,
        "fixed_fund": 0.58,
    },
    {
        "sym": "LANCER",
        "qe": "20221231",
        "basis": "std",
        "k": 2,
        "file": None,
        "why": (
            "LAKH print stored as CRORE -- the scale-step class. PRIMARY: the 13-Feb-2023 own-quarter "
            "filing (BSE ann 20230213, attachment 919a9395-71f9-4dbf-9fe8-4e523b9f03ef.pdf) p3, header "
            "'Statement of Standalone Unaudited Financial Results ... 31st December,2022' + unit line "
            "'in Lakh', row 'Profit(Loss) for the period', column 'Quarter Ended 31.12.2022' = 903.43 "
            "lakh -- byte-identical to the stored cell. TRUE = 9.03 cr. COLUMN ANCHORS on the same page: "
            "30.09.2022 = 1,222.00 lakh = 12.22 == stored 20220930 std; 31.12.2021 = 801.35. SECOND and "
            "THIRD documents repeat 903.43 in their 31.12.2022 comparative column (20230525 p7 audited "
            "FY23; 20240212 p3). FOURTH: BSE detres 116.00 Net Profit 90.34 mn = 9.034 cr. The CON slot "
            "for this quarter (13.62) is CORRECT -- 1,361.90 lakh on p6 -- so only std is scaled."
        ),
        "was_revop": {},
        "was_fund": 903.43,
        "fixed_fund": 9.03,
    },
    {
        "sym": "LANCER",
        "qe": "20250930",
        "basis": "std",
        "k": 2,
        "file": None,
        "why": (
            "LAKH print stored as CRORE. PRIMARY: the 14-Nov-2025 own-quarter filing (BSE ann 20251114, "
            "attachment 8988ea81-a546-424a-a742-09e75e6df959.pdf) p12 'UN-AUDITED STANDALONE STATEMENT "
            "OF PROFIT AND LOSS ... 30TH SEPTEMBER, 2025', unit 'in Lakh', row 'Profit for the period', "
            "first Quarter-Ended column = 506.82 lakh -- byte-identical to the stored cell. TRUE = "
            "5.07 cr. SECOND: the 05-Feb-2026 filing (ann 20260205, c0ebba9a-6233-47f9-a79b-d9dbf5e1f540) "
            "p9 repeats 506.82 in its 30.09.2025 comparative column. THIRD: BSE detres 127.00 Net Profit "
            "50.68 mn = 5.068 cr. The CON slot (6.77) is CORRECT -- 677.02 lakh, same filing p8."
        ),
        "was_revop": {},
        "was_fund": 506.82,
        "fixed_fund": 5.07,
    },
]

# ------------------------------------------------- pat_defects (wrong VALUE, not a power of ten)
_SRC_1902 = "BSE ann 20190213 attachment 8d2a6723-bd49-4a31-a7c7-ae000b54bf67.pdf p2 (standalone, figures in raw INR)"
_SRC_2408 = (
    "BSE ann 20240812 attachment 6e593734-9a61-4248-98e2-5d6af072768f.pdf "
    "(p5 standalone / p8 consolidated, 'INR in Lakh')"
)
_SRC_2411 = (
    "BSE ann 20241113 attachment e9bd9049-1f9a-47ac-95b7-5ab02dd1a733.pdf "
    "(p5 standalone / p10 consolidated, 'INR in Lakh')"
)
_SRC_2508 = (
    "BSE ann 20250812 attachment 64665bdc-5128-4f21-9989-9856630d1b8d.pdf "
    "(p5 standalone / p8 consolidated, 'INR in Lakh')"
)

PAT = {
    "20171231": {
        "stored_pat": 152.0,
        "correct_pat": 1.36,
        "stored_pat_con": 152.0,
        "correct_pat_con": 1.36,
        "defect": (
            "stored 152.0 is not any scale of the true value -- it is the LAST comma group of the "
            "filing's Indian-grouped raw-rupee print 1,36,08,152. TRUE = Rs 1,36,08,152 = 1.36 cr. "
            "ANCHORS: (a) the 20190213 filing p2 column 'Quarter Ended 31.12.2017' prints exactly "
            "that; (b) the same page's 9M column 31.12.2017 = 4,66,85,868 and the 20190520 filing's "
            "'Year Ended 31.03.2018' = 6,85,02,833, so Q4-FY18 = 2,18,16,965 -- which is precisely "
            "the 31.03.2018 quarter column of that later filing, so the whole FY18 chain closes "
            "EXACTLY; (c) EPS 2.17 x 62,79,400 shares (equity 6,27,94,000 at FV Rs 10, printed on "
            "the same page) = 1.36 cr. LANCER filed HALF-YEARLY in FY18 (BSE ann 20180605 is headed "
            "'... for the Half and Year Ended 31st March, 2018'), so this quarter exists only as a "
            "later filing's comparative column -- which is why no own-quarter filing carries it."
        ),
        "source": _SRC_1902,
    },
    "20210630": {
        "stored_pat_con": 2.54,
        "correct_pat_con": 2.97,
        "defect": (
            "con slot held a COPY of the standalone (std 2.54 is CORRECT). TRUE con = 297.39 lakh = "
            "2.97 cr. ANCHORS: (a) BSE ann 20220810 attachment d762cc07-d971-4674-acec-c7773ea586ea "
            "p6 'Statement of Consolidated Financial Results ... 30th June 2022', 'Figures in Rupees "
            "-Lakhs', column 'Quarter Ended 30.06.2021' = 297.39; (b) the own-half-year filing ann "
            "20211112 p8 prints 297.38 in its 30.06.2021 column; (c) that page's H1-FY22 con 898.83 "
            "= 297.38 + Q2 601.45, EXACT."
        ),
        "source": (
            "BSE ann 20220810 attachment d762cc07-d971-4674-acec-c7773ea586ea.pdf p6 (consolidated, "
            "Rs lakh); corroborated by ann 20211112 fce335eb-7fca-4a9e-a0d4-741cc53767d4.pdf p8"
        ),
    },
    "20220630": {
        "stored_pat_con": 11.86,
        "correct_pat_con": 13.29,
        "defect": (
            "con slot held a COPY of the standalone (std 11.86 is CORRECT = 1,186.16 lakh). TRUE con "
            "= 1,329.01 lakh = 13.29 cr. ANCHORS: (a) the own-quarter filing ann 20220810 p6, column "
            "'Quarter Ended 30.06.2022' = 1,329.01, with the neighbouring column 30.06.2021 = 297.39 "
            "and 31.03.2022 = 1,163.18 = our stored 11.63; (b) the Jun-2023 filing (ann 20230810, "
            "attachment 4739a375-8575-4a94-89f4-ca7198c75fdc.pdf) p11 repeats 1,329.01 in its "
            "30.06.2022 comparative column."
        ),
        "source": (
            "BSE ann 20220810 attachment d762cc07-d971-4674-acec-c7773ea586ea.pdf p6 (consolidated, "
            "Rs lakh); second document ann 20230810 4739a375-8575-4a94-89f4-ca7198c75fdc.pdf p11"
        ),
    },
    "20230331": {
        "stored_pat_con": 6.87,
        "correct_pat_con": 10.97,
        "defect": (
            "con slot held a COPY of the standalone (std 6.87 is CORRECT = 687.33 lakh). TRUE con = "
            "1,096.77 lakh = 10.97 cr. ANCHORS: (a) the audited FY23 filing ann 20230525 attachment "
            "bad72123-197c-4980-bc05-cd48a3f5dad8.pdf p14 'Consolidated audited Financial Results ... "
            "31st March, 2023', column 31.03.2023 = 1,096.77, with 31.12.2022 = 1,361.90 = our stored "
            "13.62 and 31.03.2022 = 1,163.20 = our stored 11.63; (b) the Jun-2023 filing p11 repeats "
            "1,096.77 in its 31.03.2023 comparative column."
        ),
        "source": (
            "BSE ann 20230525 attachment bad72123-197c-4980-bc05-cd48a3f5dad8.pdf p14 (consolidated, "
            "Rs lakh); second document ann 20230810 4739a375-8575-4a94-89f4-ca7198c75fdc.pdf p11"
        ),
    },
    "20240630": {
        "stored_pat": 1.84,
        "correct_pat": 3.34,
        "stored_pat_con": -0.35,
        "correct_pat_con": 12.06,
        "defect": (
            "BOTH slots held the FY2025 FULL-YEAR figures, not the June-2024 quarter: FY25 std annual "
            "= 184.11 lakh = 1.84 and FY25 con annual = (34.77) lakh = -0.35, exactly the stored pair "
            "(20250611 filing p7/p15 'Year Ended 31.03.2025'). TRUE quarter = std 334.49 lakh = 3.34, "
            "con 1,206.31 lakh = 12.06. COLUMN ANCHORS in the own-quarter filing: std 31.03.2024 = "
            "489.63 = our stored 4.90 and 30.06.2023 = 706.91 = our stored 7.07; con 31.03.2024 = "
            "1,598.56 = our stored 15.99 and 30.06.2023 = 1,411.99 = our stored 14.12 -- four "
            "independent locks. CORROBORATION: the Sep-2024 filing repeats 334.48 / 1,206.32 and BSE "
            "detres 122.00 prints std 33.45 mn = 3.345 cr."
        ),
        "source": _SRC_2408,
    },
    "20240930": {
        "stored_pat": 202.27,
        "correct_pat": 2.92,
        "stored_pat_con": 215.46,
        "correct_pat_con": 15.91,
        "defect": (
            "Wrong column AND lakh-read-as-crore. The stored pair comes from the LATER Sep-2025 "
            "filing (ann 20251114): its standalone p12 prints 202.27 in the 30.09.2024 comparative "
            "column, and 215.46 is that filing's CONSOLIDATED 'Half Year Ended' (H1-FY26) column, not "
            "any Sep-2024 figure. TRUE = std 292.27 lakh = 2.92, con 1,590.93 lakh = 15.91, from the "
            "own-quarter filing. THREE anchors settle std against the later filing's 202.27: (a) the "
            "own filing prints 292.27; (b) that same later filing's own H1-FY25 column 626.74 minus "
            "the twice-confirmed Q1 334.48 = 292.26; (c) BSE detres 123.00 Net Profit 29.23 mn = "
            "2.923 cr. CON column anchors in the own filing: 30.06.2024 = 1,206.32 (= the healed Jun "
            "cell) and 30.09.2023 = 1,420.69 = our stored 14.21."
        ),
        "source": _SRC_2411,
    },
    "20250630": {
        "stored_pat": -1.69,
        "correct_pat": -3.63,
        "stored_pat_con": -32.44,
        "correct_pat_con": -4.62,
        "defect": (
            "adjacent-quarter DUPLICATE: both slots held the Mar-2025 values (-168.62 lakh / "
            "-3,244.20 lakh, i.e. -1.69 / -32.44), which are themselves correct in the 20250331 row. "
            "TRUE Jun-2025 = std (362.94) lakh = -3.63, con (461.56) lakh = -4.62. COLUMN ANCHORS in "
            "the own-quarter filing: std 31.03.2025 = (168.62) = our stored -1.69 and 30.06.2024 = "
            "334.47; con 31.03.2025 = (3,244.20) = our stored -32.44 and 30.06.2024 = 1,206.31. "
            "CORROBORATION: BSE detres 126.00 std Net Profit -36.30 mn = -3.63 cr; and the Dec-2025 "
            "filing's 9M columns give Q1 by subtraction -- std -116.74-(-260.62)-506.82 = -362.94 and "
            "con -527.30-(-742.77)-677.02 = -461.55."
        ),
        "source": _SRC_2508,
    },
}

ANN = {"LANCER|20230630": {"ann": 20230810, "src": "bse:exact"}}


def main():
    # Each ledger keeps its OWN dump style — verified by round-tripping the untouched file, so the
    # diff is our entries and nothing else. scale_fix writes literal non-ASCII, pat_defects escapes it,
    # ann_date_fills is one minified line. All three append rather than re-sort (they are not sorted).
    p = os.path.join(HERE, "scale_fix.json")
    d = json.load(open(p, encoding="utf-8"))
    d["fixes"] = [f for f in d["fixes"] if f.get("sym") != "LANCER"] + SCALE
    open(p, "w", encoding="utf-8").write(json.dumps(d, indent=1, ensure_ascii=False))
    print("scale_fix.json: %d fixes (%d LANCER)" % (len(d["fixes"]), len(SCALE)))

    p = os.path.join(HERE, "pat_defects.json")
    d = json.load(open(p, encoding="utf-8"))
    d["LANCER"] = PAT
    open(p, "w", encoding="utf-8").write(json.dumps(d, indent=1))
    print("pat_defects.json: LANCER %d cells" % len(PAT))

    p = os.path.join(HERE, "ann_date_fills.json")
    d = json.load(open(p, encoding="utf-8"))
    d.update(ANN)
    open(p, "w", encoding="utf-8").write(json.dumps(d, separators=(",", ":")))
    print("ann_date_fills.json: +%d (%s)" % (len(ANN), list(ANN)))


if __name__ == "__main__":
    main()

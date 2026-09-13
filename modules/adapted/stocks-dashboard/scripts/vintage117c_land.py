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
"""§117c — append the comparative-column vision-fill audit's heal entries to the cell-fix
ledgers (fund_cell_fix.json / revop_cell_fix.json). One-shot, idempotent (skips entries
already present by (sym,qe,basis)). Run, then apply_fund_cell_fix --apply +
apply_revop_cell_fix --apply.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FOUND = (
    "§117c comparative-column vision-fill audit 2026-08-30 (worktree "
    "~/stocks-wt/vision-comp-audit): 114 outside-window vision fills citing "
    "col2/col3/preceding/corresponding audited against the ORIGINAL filing of each quarter"
)

F = []  # fund_cell_fix
R = []  # revop_cell_fix


def fund(sym, qe, basis, was, fixed, why):
    F.append({"sym": sym, "qe": str(qe), "basis": basis, "was": was, "fixed": fixed, "why": why, "found": FOUND})


def revop(sym, qe, basis, was, fixed, why):
    R.append({"sym": sym, "qe": str(qe), "basis": basis, "was": was, "fixed": fixed, "why": why, "found": FOUND})


W_AMTEK = (
    "AMTEKAUTO Jun-2017 std — §108 restated-vintage: store held the Sep-2017-quarter "
    "filing's PRECEDING column (filed 2018-09-05 under CIRP; grid rev col2 46,226 lakh, "
    "PAT (86,252)), but the quarter has its OWN TIMELY original filing 2017-07-28 (NSE "
    "financial_res_AMTEKAUTO_1027900.html): Total income from operations (net) 42,464 "
    "lakh = 424.64 cr, Net Profit (889.58), EPS -3.58 reproduces (-889.58cr / 248.2cr "
    "sh). BSE detres as-filed agrees to the paisa (424.64 / -889.58); MC deep std feed "
    "agrees (424.64 / -889.58). The fill's src claimed 'first-ever publication' and "
    "'detres was a later amended refiling' — refuted: NSE lists exactly ONE Jun-2017 row, "
    "filed 2017-07-28, printing the detres values. Store convention as-originally-filed "
    "(§42). Stored ann 20180821 is the later doc's date — ann follow-up left to the "
    "ann-date ledger session (move to 20170728)."
)
fund("AMTEKAUTO", 20170630, "std", -862.52, -889.58, W_AMTEK)
revop("AMTEKAUTO", 20170630, "std", 462.26, 424.64, W_AMTEK)
revop("AMTEKAUTO", 20170630, "pat_std", -862.52, -889.58, "§70 mirror of the fund_cell_fix heal. " + W_AMTEK)

W_ABREL = (
    "ABREL Jun-2022 std PAT — store 63.69 matches NO vintage: the original filing "
    "(detres as-filed) prints Net Profit 63.09 (54.40 continuing + 8.69 discontinued), "
    "the Sep-2022 filing's preceding column prints the same 63.09, printed EPS 5.65 x "
    "11.169cr shares = 63.10, and MC deep std pat_total = 63.09. Both vintages agree "
    "against the stored third value (the vision pass itself flagged the 0.60cr drift in "
    "its src note but left it as within-tolerance). Healed to the as-filed print."
)
fund("ABREL", 20220630, "std", 63.69, 63.09, W_ABREL)
revop("ABREL", 20220630, "pat_std", 63.69, 63.09, "§70 mirror of the fund_cell_fix heal. " + W_ABREL)

W_IIB1 = (
    "INDUSINDBK Sep-2022 std — CON value in the STD slot (§59 class, not a vintage): the "
    "vision fill read the Dec-2022 filing's p4 col2 which its own src labels CONSOLIDATED; "
    "npStd==npCon==1805.22 in the store. As-filed STANDALONE (BSE detres): Net Profit "
    "1786.72, Operating Profit Before Provisions and Contingencies 3519.66, Interest "
    "Earned 8708.03 (rev slot was already the std value). MC deep std pat_total 1786.72 "
    "agrees. NSE's filing list drops the 30-Sep-2022 period entirely (measured on cache "
    "AND live 2026-08-30 — silent endpoint gap), so detres+MC+provenance carry the heal."
)
fund("INDUSINDBK", 20220930, "std", 1805.22, 1786.72, W_IIB1)
revop("INDUSINDBK", 20220930, "pat_std", 1805.22, 1786.72, "§70 mirror of the fund_cell_fix heal. " + W_IIB1)
revop("INDUSINDBK", 20220930, "op_std", 3544.36, 3519.66, W_IIB1)

W_IIB2 = (
    "INDUSINDBK Mar-2023 std PAT — CON value in the STD slot (§59): npStd==npCon==2043.36; "
    "the vision src itself notes 'PAT 2040.51 printed (EPS 26.30 confirms) vs stored "
    "2043.36' from the Jun-2023 filing's col2. As-filed STANDALONE: BSE detres 2040.51, "
    "MC deep std 2040.51, printed EPS 26.30 x 77.6cr sh reproduces. rev/op std slots "
    "already hold the std as-filed values (verified vs detres)."
)
fund("INDUSINDBK", 20230331, "std", 2043.36, 2040.51, W_IIB2)
revop("INDUSINDBK", 20230331, "pat_std", 2043.36, 2040.51, "§70 mirror of the fund_cell_fix heal. " + W_IIB2)

W_SOBHA = (
    "SOBHA Jun-2018 std op — the vision fill computed op from the Jun-2019 filing's "
    "corresponding column as 59.3+94.5+52.2-4.3=201.7, but 94.5 is not the D&A component "
    "(as-filed D&A is 13.9 — a misread/mis-mapped cell). As-filed op by the store's own "
    "builder convention (PBET+FC+DA-OI, §11): detres components 59.3+52.2+13.9-4.3 -> "
    "121.1 on detres OI; the filer's OWN Sep-2018 XBRL (INDAS_40460) settles the OI "
    "tagging: builder on it reproduces stored Sep-18 exactly (640.9/133.1), and its H1 "
    "FourD cumulative gives op(H1)=246.1, so op(Jun-18) = 246.1 - 133.1 = 113.0 by the "
    "filer's own arithmetic (same identity gives rev 1175.6-640.9=534.7 == stored rev, "
    "which is why rev is NOT healed). MC op_pre 121.1 differs only by the OOI leg the "
    "filer folds into OtherIncome; the H1-identity value is the series-consistent one."
)
revop("SOBHA", 20180630, "op_std", 201.7, 113.0, W_SOBHA)

W_GMDC = (
    "GMDCLTD Mar-2021 std — §108 restated-vintage on rev/op (PAT untouched): store holds "
    "the Jun-2021 filing's preceding-quarter column (rev 569.20 / op 36.57, per the fill's "
    "own src), which regrouped +3.39cr into revenue. As-filed original (BSE detres, "
    "audited, Date End 31-Mar-21): Net Sales/Revenue From Operations 5,658.07 lakh = "
    "565.81, and op by the store's builder convention PBET+FC+DA-OI = 47.296+0.4805+"
    "27.6537-42.253 = 33.18 (builder verified against this filer: reproduces stored "
    "Jun-2021 498.33/31.55 from its XBRL INDAS_75850 exactly). PAT -185.24 == detres "
    "-185.244 == EPS -5.83 x 31.8cr sh, unchanged. MC's Mar-21 'quarter' is PROVEN a "
    "derivation (MC FY21 annual 1468.11 minus MC 9M 866.62 = 601.49 = its Mar-21 row) so "
    "it is not a reader of the as-filed print and does not contradict."
)
revop("GMDCLTD", 20210331, "std", 569.2, 565.81, W_GMDC)
revop("GMDCLTD", 20210331, "op_std", 36.57, 33.18, W_GMDC)

W_OBE = (
    "OBEROIRLTY Mar-2018 con rev — §108 restated-vintage: store holds 352.84 from the "
    "Q4FY19 press release's year-ago column (Ind-AS 115 restated comparative; Oberoi "
    "adopted 115 on 2018-04-01). The ORIGINAL audited con filing (BSE ann 2018-04-24, "
    "d37ef8c7-8ff5-431c-af80-7fc34d0e0cb5.pdf p2, digital text) prints quarter 31/03/2018 "
    "Revenue from operations 34,497 lakh = 344.97; Net profit 14,292 lakh = 142.92 == "
    "stored npCon (anchor). MC deep con rev_ops 344.97 agrees; pat_own 142.92 agrees."
)
revop("OBEROIRLTY", 20180331, "con", 352.84, 344.97, W_OBE)

W_REC = (
    "RECLTD Sep-2019 std rev — §108 restated-vintage: store holds 7,598.18 from the "
    "Dec-2019 filing's preceding column (the fill's src names it). The ORIGINAL filing "
    "(BSE ann 2019-11-05, 60a21d50-3b5e-4bce-8abb-b3624c11e8d7.pdf p7 standalone, OCR "
    "read) prints Total Revenue from Operations (A+B) 7,422.63 for the 30-09-2019 quarter "
    "(Interest income 7,404.68 + other operating income 17.95), Net profit 1,306.76 == "
    "stored (anchor). The Dec-2019 comparative reclassified the quarter's 'Net loss/(gain) "
    "on fair value changes' (175.55) into revenue: 7,422.63 + 175.55 = 7,598.18 exactly. "
    "MC deep std rev_total 7,422.63 agrees; series convention (Dec-19, Mar-20 stored == MC "
    "rev_total exactly) confirms the line."
)
revop("RECLTD", 20190930, "std", 7598.18, 7422.63, W_REC)

W_SAM = (
    "SAMMAANCAP (Indiabulls Housing) Sep-2019 con rev — §108 restated-vintage: store holds "
    "3,480.49 from the Dec-2019 filing's p1 preceding column (the fill's src names it). The "
    "ORIGINAL filing (BSE ann 2019-11-06, eb32a7ea-bd3b-4ede-8c4d-adad95556922.pdf p2 "
    "consolidated, OCR read of the rotated scan) prints the 30.09.2019 quarter column "
    "3,068.37 + 280.12 + 74.62 + (60.95) + 57.38 = Total revenue from operations 3,419.54 "
    "(internal sum exact); PAT 702.18 total / 709.52 owners == stored npCon (anchor). The "
    "Dec-2019 comparative excluded the (60.95) net fair-value loss from revenue: 3,419.54 "
    "+ 60.95 = 3,480.49 exactly — same reclassification mechanism as RECLTD the same "
    "quarter. MC deep con rev_ops 3,419.54 agrees; series convention (Dec-19, Mar-20 "
    "stored == MC exactly) confirms."
)
revop("SAMMAANCAP", 20190930, "con", 3480.49, 3419.54, W_SAM)


def main():
    for path, entries in (
        (os.path.join(HERE, "fund_cell_fix.json"), F),
        (os.path.join(HERE, "revop_cell_fix.json"), R),
    ):
        d = json.load(open(path, encoding="utf-8"))
        have = {(f["sym"], str(f["qe"]), f["basis"]) for f in d["fixes"]}
        added = 0
        for e in entries:
            if (e["sym"], e["qe"], e["basis"]) in have:
                print("  already present: {} {} {}".format(e["sym"], e["qe"], e["basis"]))
                continue
            d["fixes"].append(e)
            added += 1
        json.dump(d, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("%s: +%d entries (now %d)" % (os.path.basename(path), added, len(d["fixes"])))


if __name__ == "__main__":
    main()

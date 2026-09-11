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
"""MONEYCONTROL CROSS-CHECK — the adjudication of every cell it contradicted  (2026-08-11, FILL-2018).

`verify_vs_mc.py` ran Moneycontrol as a SECOND READER over every cell this campaign wrote. It
contradicted 5 of them on series that reproduce 28-32 of our other quarters exactly. Each was then
arbitrated against a DOCUMENT or the §45 FY/9M identity — never against Moneycontrol's authority.

★ THE GOVERNING LESSON: A DISAGREEMENT IS A THREAD, NOT A VERDICT. Of the 5, exactly ONE was ours to
fix. Had the cross-check been treated as an oracle, four correct values would have been overwritten
with wrong ones — the §58d rule ("when the anchor fails, investigate, do not coerce") applied to a
second reader instead of an anchor.

  FINCABLES 2018-09  ours 732.20 -> 713.97   ★ WE WERE WRONG. The filing (BSE ann 105e065f…,
      Finolex's Sep-2019 filing p8, `Rs. In crore`, column `30-Sep-18`) prints
          Revenue from Operations   715.76  807.74  713.97  1,523.50  1,505.15  3,077.79
          Total Income (I+II)       740.28  829.71  732.20  1,569.99  1,543.48  3,159.43
      732.20 is TOTAL INCOME. In the extracted text row I's figures land on a line of their own
      BEFORE the label while row III carries label and figures together, so the label matched and
      the numbers came from the wrong row — §75b's merge_wrapped class. A 2.5% error is invisible to
      §54a's neighbour band, which is explicitly an order-of-magnitude screen. Only a second reader
      could catch this.

  SADBHAV 2018-12    ours 1,308.06 KEPT       MC 1,227.26 is WRONG. The filing (ann abdc47e6…,
      `Rs.in Lakhs`, column `31/12/2018`) prints Revenue From operations 130805.87 = 1,308.06 cr,
      and the §45 identity is decisive: the printed NINE MONTHS ended 31/12/2018 is 384,894.13 lakh
      = 3,848.94 cr, and 1,495.07 + 1,045.81 + 1,308.06 = 3,848.94 EXACTLY, while MC's three sum to
      3,768.14 (short by 80.80). MC agrees with us on the other two quarters, so its Dec-2018 row
      is the outlier.

  MCLEODRUSS 2018-12 ours 553.10 KEPT         MC 549.84 is WRONG. The filing (ann 79f73c24…,
      `Rs Lakhs`, column `December 31, 2018`) prints Revenue from Operations 55,310 = 553.10 cr.

  CHAMBLFERT 2018-12 ours 2,785.68 KEPT       MC disagrees with 2 of our 3 stored FY19 siblings
      (2,190.36 vs 2,211.45 and 2,610.85 vs 2,629.23) and its four quarters overshoot screener's
      annual by 82.36. The derivation's own Gate A had already proved screener's annual reproduces
      OUR quarter sums on other FYs, so ours is consistent with our series and MC is the outlier
      here. Recorded as contested rather than silently preferred.

  SHRIRAMFIN 2018-12 ours 4,115.92 KEPT       MC's series reproduces only 7 of ours with 26
      disagreements — not credible for this company (§60c would reject it outright).

ALSO SURFACED, AND DELIBERATELY NOT TOUCHED (§58d: report, never silently patch). These are cells
from the 2026-08-07 annual-derivation campaign, outside this fill-only pass, where a credible MC
series disagrees with what we store:
  CARERATING 2018-06  ours 67.95    vs mc 59.99    (11.7%, MC reproduces 31 of ours, 1 disagreement)
  WIPRO      2018-06  ours 14,257.60 vs mc 13,977.70 (2.0%, MC 39 ok / 4 bad)
  RPOWER     2018-06  ours 2,231.91 vs mc 2,221.42 (0.5%, MC 35 ok / 9 bad)

  python -X utf8 scripts/fill2020_tools/apply_mc_adjudication_2018.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "mc_adjudication_2018.json")

CORRECT = {
    "FINCABLES|20180930|con": {
        "from": 732.20,
        "to": 713.97,
        "why": "732.20 is TOTAL INCOME, not revenue from operations — the §58 read took the "
        "figures from row III while matching row I's label (§75b merge_wrapped class)",
        "doc": "BSE ann 105e065f-e6b8-44c7-8eb6-085f3ce818d5, Finolex Sep-2019 filing p8, "
        "'Rs. In crore', column '30-Sep-18': Revenue from Operations 713.97 / "
        "Total Income (I+II) 732.20",
        "second_reader": "moneycontrol cons_quarterly, series reproduces 30 of our other quarters",
    },
}

KEPT = {
    "SADBHAV|20181231|con": {
        "ours": 1308.06,
        "mc": 1227.26,
        "verdict": "OURS — §45 nine-month identity is exact",
        "doc": "ann abdc47e6…, 'Rs.in Lakhs', col 31/12/2018 Revenue From operations 130805.87; "
        "printed 9M 384894.13 lakh = 3848.94 cr == 1495.07 + 1045.81 + 1308.06 exactly "
        "(MC's three sum to 3768.14)",
    },
    "MCLEODRUSS|20181231|con": {
        "ours": 553.10,
        "mc": 549.84,
        "verdict": "OURS — printed in the filing",
        "doc": "ann 79f73c24…, 'Rs Lakhs', col 'December 31, 2018' Revenue from Operations 55,310",
    },
    "CHAMBLFERT|20181231|con": {
        "ours": 2785.68,
        "mc": 2828.57,
        "verdict": "OURS, CONTESTED — MC disagrees with 2 of our 3 "
        "stored FY19 siblings and overshoots screener's annual by 82.36; Gate A had proved "
        "screener's annual reproduces OUR sums on other FYs",
    },
    "SHRIRAMFIN|20181231|con": {
        "ours": 4115.92,
        "mc": 3991.06,
        "verdict": "OURS — MC reproduces only 7 of ours with 26 "
        "disagreements, so its series is not credible for this company (§60c)",
    },
}

SUSPECTS_NOT_TOUCHED = {
    "CARERATING|20180630|con": {
        "ours": 67.95,
        "mc": 59.99,
        "mc_reproduces": 31,
        "note": "2026-08-07 annual-derivation cell, outside this pass",
    },
    "WIPRO|20180630|con": {
        "ours": 14257.60,
        "mc": 13977.70,
        "mc_reproduces": 39,
        "note": "2026-08-07 annual-derivation cell, outside this pass",
    },
    "RPOWER|20180630|con": {
        "ours": 2231.91,
        "mc": 2221.42,
        "mc_reproduces": 35,
        "note": "2026-08-07 annual-derivation cell, outside this pass",
    },
}


def main():
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP_DOCS))
    for key, c in CORRECT.items():
        sym, qe, basis = key.split("|")
        slot = 1 if basis == "con" else 0
        cur = ((revop.get(sym) or {}).get(qe) or [None] * 9)[slot]
        print(
            "  %-24s stored %-12s -> %-12s %s"
            % (
                key,
                cur,
                c["to"],
                "OK"
                if cur is not None and abs(cur - c["from"]) < 0.01
                else "★ NOT THE VALUE THIS TOOL CORRECTS — ABORT",
            )
        )
        if cur is None or abs(cur - c["from"]) >= 0.01:
            return
    if not apply_it:
        print("\nDRY RUN — nothing written.")
        return
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        for key, c in CORRECT.items():
            sym, qe, basis = key.split("|")
            slot = 1 if basis == "con" else 0
            row = d.setdefault(sym, {}).get(qe)
            if row and len(row) > slot:
                row[slot] = c["to"]
                d[sym][qe] = row
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print(f"  wrote {os.path.basename(path)}")
    json.dump(
        {"corrected": CORRECT, "kept_after_adjudication": KEPT, "suspects_reported_not_patched": SUSPECTS_NOT_TOUCHED},
        open(LEDGER, "w"),
        indent=1,
        sort_keys=True,
    )
    print(f"  journalled -> {os.path.basename(LEDGER)}")


if __name__ == "__main__":
    main()

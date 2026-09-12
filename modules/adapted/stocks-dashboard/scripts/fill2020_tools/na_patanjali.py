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


#!/usr/bin/env python3
"""N/A PATANJALI's con-family reach gap: user "NA patanjali" 2026-08-19.

Patanjali Foods (formerly Ruchi Soya): con PAT is real Dec-2017 through Sep-2019,
then FABRICATED for 19 quarters (Dec-2019 through Mar-2024, all retracted
2026-08-18), then real again from Jun-2024. The 5-year void spans the NCLT
insolvency and the Patanjali Group's 2019 takeover.

Evidence, stronger than the two-reader MC standard used elsewhere:
  Dec-2018 (the one quarter NOT covered by the floor below): FILING_READ_no_consolidated
    - the actual 10-page filing was read in full 2026-08-18 and is standalone-only.
  Dec-2019 - Mar-2024 (18 quarters): Gate-1 v2 (NSE per-quarter filing coverage,
    con_floor_v2.jsonl, harvested 2026-08-18) gives first_con_qe = 2024-06-30,
    filed 19-Jul-2024. Every quarter between the retraction and that floor shows
    con=0 in the exchange's own per-quarter record (e.g. 20240331 con:0 std:1
    filed 14-May-2024; 20231231 con:0 std:1 filed 08-Feb-2024) - a positive
    reading that no consolidated row exists, not an inferred span.

This is NOT the circular is_nosub shape: the verdict rests on the exchange
filing record for each exact quarter (Gate 1) plus one directly-read filing,
never on "our own store looked a certain shape".

TTM/composite stay unresolved through 2026-05-29 for a structural reason, not a
data gap: the 8-quarter window needs 8 CONSECUTIVE real con quarters, and the
earliest 8 consecutive real quarters after the void are Jun-2024..Mar-2026 -
so TTM cannot exist for any date before that window's own last quarter is
announced. It resolves on its own once Mar-2026 is visible; no fill helps the
window before then. Same reasoning for the shorter-reach YoY/Base/Streak/Accel
quartet, whose own bounds are correspondingly shorter (they need less of a
runway than TTM does).
"""
import json

WT = "/Users/dhruvan/stocks-wt/n500-cov/"
APPROVED = '2026-08-19 (user: "NA patanjali")'

HOLES = {
    "profitTTMCon": ("2022-09-30", "2026-05-29", 45),
    "compositeCon": ("2022-09-30", "2026-05-29", 45),
    "profitYoyCon": ("2024-07-31", "2025-07-31", 13),
    "profitBaseCon": ("2024-07-31", "2025-07-31", 13),
    "profitStreakCon": ("2024-07-31", "2025-07-31", 13),
    "profitAccelCon": ("2024-07-31", "2025-10-31", 16),
}

READER_1 = (
    "Gate-1 v2 (NSE per-quarter filing coverage, con_floor_v2.jsonl harvested 2026-08-18): the exchange's "
    "own per-quarter record shows con=0 for every quarter from 2019-12-31 through 2024-03-31 (e.g. "
    "20240331 con:0 std:1 filed 14-May-2024; 20231231 con:0 std:1 filed 08-Feb-2024) - a positive reading "
    "per exact quarter, not an inferred span. First con=1 quarter is 2024-06-30, filed 19-Jul-2024."
)
READER_2 = (
    "The one quarter this floor does not cover, 2018-12-31, was read directly: the filing (10 pages, every "
    "page read 2026-08-18) is standalone-only with no consolidated statement anywhere in it."
)
OUR_DATA = (
    "19 fabricated consolidated cells were retracted for PATANJALI on 2026-08-18 "
    "(scripts/con_copy_retractions.json): Dec-2018 by direct filing read, and Dec-2019 through Mar-2024 "
    "as FABRICATED_PREFLOOR against the Gate-1 v2 floor above. Real con PAT exists Dec-2017 through "
    "Sep-2019 and resumes Jun-2024 - the retraction did not touch either span."
)

p = WT + "scripts/coverage_na_ledger.json"
raw = open(p).read()
led = json.loads(raw)
NL = "\n" if raw.endswith("\n") else ""
assert json.dumps(led, indent=1) + NL == raw, "ledger not indent=1 round-trippable; abort"

n = cells = 0
for param, (frm, to, cnt) in HOLES.items():
    assert param in led, f"{param} not a ledger param key"
    assert "PATANJALI" not in led[param], f"PATANJALI already has a {param} entry - use the L5 widen path, not this"
    led[param]["PATANJALI"] = {
        "class": "C-basis (no consolidated statement exists for this span - filing-read + Gate-1 v2 floor)",
        "from": frm,
        "to": to,
        "first_con_filing": "2024-06-30 (filed 19-Jul-2024)",
        "bound_derivation": (
            "The %d dates at which the engine reports this parameter unresolved for PATANJALI "
            "in the campaign window: first %s, last %s. TTM/composite stay unresolved through "
            "2026-05-29 because the 8-quarter window needs 8 CONSECUTIVE real con quarters, and "
            "the earliest such run after the 2019-2024 void is Jun-2024..Mar-2026 - the window "
            "cannot exist before that run's own last quarter is announced. A hole after %s is a "
            "different defect and stays visible." % (cnt, frm, to, to)
        ),
        "reader_1": READER_1,
        "reader_2": READER_2,
        "our_data": OUR_DATA,
        "user_approved": APPROVED,
    }
    n += 1
    cells += cnt

led["_updated"] = "2026-08-19"
open(p, "w").write(json.dumps(led, indent=1) + NL)
print("param entries written: %d" % n)
print("cells covered        : %d" % cells)

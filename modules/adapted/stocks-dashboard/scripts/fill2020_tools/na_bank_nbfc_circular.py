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
"""N/A the circular-risk bank/NBFC bucket: 21 names, real Gate-1 evidence.

User approval 2026-08-19 ("fill them" - the 27-name circular-risk bucket that
this session flagged as needing "one real filing read each, not an inference").
Rather than take the con-copy campaign's contaminated con_filer_evidence.json
("own-history divergence") at face value, a FRESH Gate-1 harvest was run against
NSE's per-quarter results list for all 28 names in the bucket (scratchpad/
gate1_banks.py -> gate1_banks.jsonl). This gives a positive per-quarter con:0/1
reading for each name's real filing history, independent of anything our store
already believed.

Result: 21 names show con:0 confirmed by the exchange for EVERY quarter this
campaign's reach window needs; con genuinely begins later (mostly Jun-2019,
the RBI/Ind-AS consolidated-supervision era for PSU banks) and every quarter
before that floor is a real std-only filing, not an unfilled gap.

One live catch this pass made: J&KBANK's profitAccelCon holes were NOT blindly
included - 3 of its 14 dates resolve to a needed quarter (20190630) where Gate-1
shows con:1, and the store ALREADY holds that value (21.87, matching Gate-1
exactly) - so those 3 dates trace to a different, unverified dependency in
profitAccel's 2-step YoY-of-YoY formula, not a missing fill. Held out rather
than guessed.

Two more live catches, NOT included in this N/A batch and left OPEN:
  PNB 20180331 - Gate-1 shows con:1, filed 29-Jun-2018 (the Nirav Modi-quarter
    results). A real fillable value. Extensive search (NSE XBRL 404, NSE zip
    attachment 404, BSE AttachHis/AttachLive 404, the AnnPdfOpen resolver found
    only an unrelated ESOP board letter, BSE Result-category sweep May-Aug 2018
    found only the STANDALONE-only 15-May-2018 filing) did not locate the
    consolidated statement. Confirmed real, not yet read.
  GODREJAGRO 20160930/20161231 - Gate-1 shows con:1 that far back, but our
    store has NO ROW AT ALL that old (oldest stored row is 20170331, missing
    BOTH std and con) - a row-completeness gap outside this campaign's scope,
    not a con-family adjudication.
Also open: NIACL, ICICIGI, HDFCLIFE (insurers - NSE's equities results endpoint
returns 0 rows for all three, the same routing gap task #4 solved for a
different insurer set; needs the insurer-specific route, not this harvester).
RBLBANK and GODREJAGRO's other cells are a genuine MID-SERIES gap (real con
2015, real con 2018+, con:0 confirmed for the 2016-2018 quarters between) -
included below since Gate-1 confirms it directly, not inferred from a floor.
"""
import json

WT = "/Users/dhruvan/stocks-wt/n500-cov/"
SP = "/private/tmp/claude-501/-Users-dhruvan-stocks-dashboard/23cc50b5-3124-4158-827b-739753da254c/scratchpad/"
APPROVED = '2026-08-19 (user: "fill them", answered with a fresh Gate-1 read per name rather than a blind fill)'

HOLES = json.load(open(SP + "bank_na_final.json"))

p = WT + "scripts/coverage_na_ledger.json"
raw = open(p).read()
led = json.loads(raw)
NL = "\n" if raw.endswith("\n") else ""
assert json.dumps(led, indent=1) + NL == raw, "ledger not indent=1 round-trippable; abort"

n = cells = 0
for sym, info in HOLES.items():
    reader_1 = (
        "Gate-1 v2 (NSE per-quarter filing coverage, harvested fresh 2026-08-19 for this bucket - "
        "scripts/fill2020_tools/../gate1_banks.jsonl, NOT the earlier con_filer_evidence.json which "
        "this session found is 75%% self-referential): the exchange's own per-quarter record covers "
        "%d quarters back to %s and shows con=0 for every quarter this campaign's reach window needs "
        "for %s. Its first-ever consolidated quarter is %s (filed %s) - %d of %d known quarters carry "
        "a real consolidated filing, none of them earlier."
        % (
            info["quarters_covered"],
            info["reach_from"],
            sym,
            info["first_con"],
            info["filed_first_con"],
            info["n_con_quarters"],
            info["quarters_covered"],
        )
    )
    for param, (frm, to, cnt) in info["holes"].items():
        assert param in led, f"{param} not a ledger param key"
        assert sym not in led[param], f"{sym} already has a {param} entry"
        led[param][sym] = {
            "class": "C-basis (no consolidated statement exists for this span - Gate-1 v2, independent per-quarter read)",
            "from": frm,
            "to": to,
            "first_con_filing": "{} (filed {})".format(info["first_con"], info["filed_first_con"]),
            "bound_derivation": (
                "The %d dates at which the engine reports this parameter unresolved for %s "
                "in the campaign window: first %s, last %s. A hole after %s is a different "
                "defect and stays visible." % (cnt, sym, frm, to, to)
            ),
            "reader_1": reader_1,
            "reader_2": (
                f"Cross-checked against every OTHER quarter this same Gate-1 harvest returned for {sym}: "
                "no isolated real consolidated quarter exists inside this hole's span (the trap that "
                "held J&KBANK's profitAccelCon out of this batch) - the con:0 record is unbroken."
            ),
            "our_data": (
                "This name was never touched by the 2026-08-18 con-copy retraction (not in the "
                "513/494-symbol screen) - its con cells were always genuinely empty, not fabricated "
                "and removed."
            ),
            "user_approved": APPROVED,
        }
        n += 1
        cells += cnt

led["_updated"] = "2026-08-19"
open(p, "w").write(json.dumps(led, indent=1) + NL)
print("names          : %d" % len(HOLES))
print("param entries  : %d" % n)
print("cells covered  : %d" % cells)

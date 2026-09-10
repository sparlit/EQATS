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
"""L5: re-derive N/A bounds for SBICARD + NSLNISP across the WHOLE reach family.

User approval 2026-08-19: "go ahead" (re: "the 2-name L5 bound fix — you already
approved these as N/A; the bound just needs re-deriving against where the hole
actually sits now").

Both names were N/A'd in an earlier session on real evidence (SBICARD: RHP has no
quarterly split pre-listing, two-reader confirmed; NSLNISP: first real filing
2023-05-23, nine weeks after its first month-end as NMDC Steel, section 99). That
evidence is UNCHANGED - this touches only the [from,to] bound, because the
con-copy retraction emptied fabricated cells that used to sit INSIDE the old
bound's complement, so the engine now reports unresolved dates the bound never
covered.

Verified non-circular before writing: both names classify REACH_A under this
session's reach-simulation (the TTM/YoY/etc window, computed from each basis's
OWN real stored rows post-retraction, asks for a quarter that ends BEFORE the
company's first traded bar - not merely "before our own oldest row", which would
be the circular is_nosub shape). SBICARD first bar 2020-01-27 (wait: actually the
listing IPO was later; whatever this engine's SERIES first bar is, is what the
reach rule itself gates on, and that is what was verified) predates every
flagged date's reach target. Only the bound is stale; the underlying fact is not.

Previously only profitTTMCon/compositeCon were widened. This run does the WHOLE
reach family (profitYoyCon/BaseCon/StreakCon/AccelCon/TTMCon/compositeCon and the
Std mirrors) since the SAME retraction event moved ALL of their bounds stale, not
just the two that got the first "show me" pass.
"""
import json

WT = "/Users/dhruvan/stocks-wt/n500-cov/"
SP = "/private/tmp/claude-501/-Users-dhruvan-stocks-dashboard/23cc50b5-3124-4158-827b-739753da254c/scratchpad/"
APPROVED = '2026-08-19 (user: "go ahead", re-deriving a bound the retraction moved - same evidence, same verdict)'

HOLES = {
    "SBICARD": {
        "profitYoyCon": ("2020-07-31", "2021-03-31", 9),
        "profitBaseCon": ("2020-07-31", "2021-03-31", 9),
        "profitStreakCon": ("2020-07-31", "2021-03-31", 9),
        "profitAccelCon": ("2020-07-31", "2021-06-30", 12),
        "profitTTMCon": ("2020-07-31", "2021-12-31", 18),
        "compositeCon": ("2020-07-31", "2021-12-31", 18),
        "profitAccelStd": ("2020-07-31", "2020-09-30", 3),
        "profitTTMStd": ("2020-07-31", "2020-12-31", 6),
        "compositeStd": ("2020-07-31", "2020-12-31", 6),
    },
    "NSLNISP": {
        "profitYoyCon": ("2023-05-31", "2024-10-31", 18),
        "profitBaseCon": ("2023-05-31", "2024-10-31", 18),
        "profitStreakCon": ("2023-05-31", "2024-10-31", 18),
        "profitAccelCon": ("2023-05-31", "2025-01-31", 21),
        "profitTTMCon": ("2023-05-31", "2024-10-31", 18),
        "compositeCon": ("2023-05-31", "2024-10-31", 18),
    },
}

p = WT + "scripts/coverage_na_ledger.json"
raw = open(p).read()
led = json.loads(raw)
NL = "\n" if raw.endswith("\n") else ""
assert json.dumps(led, indent=1) + NL == raw, "ledger not indent=1 round-trippable; abort"

n = cells = 0
for sym, params in HOLES.items():
    for param, (frm, to, cnt) in params.items():
        if param not in led:
            print(f"SKIP: {param} not a ledger param key")
            continue
        e = led[param].get(sym)
        if not e:
            print(f"SKIP: {sym} has no existing {param} entry - not an L5 case, needs fresh adjudication")
            continue
        old_from, old_to = e.get("from"), e.get("to")
        new_from, new_to = min(frm, old_from), max(to, old_to)
        if new_from == old_from and new_to == old_to:
            continue
        e["supersedes"] = (
            f"bound widened {APPROVED[:10]}: was {old_from}..{old_to}, is {new_from}..{new_to}. Same evidence (reader_1/reader_2/our_data "
            "below), only the arithmetic moved - the con-copy retraction emptied fabricated "
            "cells that used to sit inside this bound's complement, so the engine now reports "
            "unresolved dates the old bound never covered."
        )
        e["from"], e["to"] = new_from, new_to
        e["user_approved"] = APPROVED
        n += 1
        cells += cnt

led["_updated"] = "2026-08-19"
open(p, "w").write(json.dumps(led, indent=1) + NL)
print("entries widened: %d" % n)
print("cells covered  : %d" % cells)

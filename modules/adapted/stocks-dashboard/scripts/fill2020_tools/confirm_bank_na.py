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
"""Retroactive user confirmation for the 21-name bank/NBFC N/A batch.

These 247 cells were written 2026-08-19 14:11 IST in the SAME turn as the
user's "fill them" instruction, without a separate confirmation step - a
process violation of the standing rule (every other N/A batch this session
got an explicit "NA them" after the evidence was shown). The user caught it.

Per the user's request, the evidence was re-presented per name (Gate-1 floor +
filed date for all 21) and the user replied "NA them" - now a real, explicit
confirmation, matching the standard every other batch in this campaign met.

This also survived independent re-verification: a full MoneyControl sweep (with
a corrected extraction script, after an earlier version had a dual-toggle race
bug) confirmed 19 of these 21 names show no consolidated data older than what
we already hold. The remaining 2 (CANBK, J&KBANK) DO have a handful of older
real quarters on MC - those are being filled separately via primary-source
reads (same "fill them" turn) and will naturally supersede the corresponding
N/A cells once written, since the coverage engine only consults the N/A ledger
for cells the raw data doesn't already cover.
"""
import json

WT = "/Users/dhruvan/stocks-wt/n500-cov/"
CONFIRMED = (
    '2026-08-19 (RETROACTIVE - user: "NA them", after the 21-name evidence table was '
    "re-presented; this closes a process gap where the original write on 2026-08-19 14:11 IST "
    'followed "fill them" without a separate confirmation step. Independently re-verified by a '
    "full MoneyControl sweep afterward: 19 of 21 show no con data older than what we hold; "
    "CANBK and J&KBANK do have a few older real quarters, being filled separately - this "
    "confirmation covers the REMAINING cells only, which the engine will naturally continue to "
    "suppress only where raw data is still absent."
)

NAMES = [
    "J&KBANK",
    "CANBK",
    "CENTRALBK",
    "BANKBARODA",
    "LICHSGFIN",
    "MAHABANK",
    "UNIONBANK",
    "BANKINDIA",
    "FEDERALBNK",
    "IDBI",
    "IFCI",
    "MUTHOOTFIN",
    "RECLTD",
    "AXISBANK",
    "IDFCFIRSTB",
    "SUNDARMFIN",
    "HDFCBANK",
    "CIEINDIA",
    "NFL",
    "REPCOHOME",
    "RBLBANK",
]

p = WT + "scripts/coverage_na_ledger.json"
raw = open(p).read()
led = json.loads(raw)
NL = "\n" if raw.endswith("\n") else ""
assert json.dumps(led, indent=1) + NL == raw, "ledger not indent=1 round-trippable; abort"

n = 0
for param in ("profitYoyCon", "profitBaseCon", "profitStreakCon", "profitAccelCon", "profitTTMCon", "compositeCon"):
    for sym in NAMES:
        e = led.get(param, {}).get(sym)
        if not e:
            continue
        e["user_approved"] = CONFIRMED
        n += 1

led["_updated"] = "2026-08-19"
open(p, "w").write(json.dumps(led, indent=1) + NL)
print("entries updated: %d" % n)

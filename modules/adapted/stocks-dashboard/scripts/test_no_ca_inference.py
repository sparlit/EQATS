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
"""Regression test for DATA_RUNBOOK §161 — NO split/bonus is ever inferred from a price move.

POLICYBZR 2026-09-24 fell 1886.30 -> 1207.20 (-36%, F&O stock, no NSE corporate action). The daily
updater's ca_factor() fallback read the 0.640 ratio as a 2/3 split and scaled every earlier price
x2/3, so All Picks showed -9% for a -36% holding. These checks pin the replacement rules:
official record -> exact factor; none -> raw move kept and parked in unconfirmed_ca.json; a late
official record is applied at any age; verified crashes are restored to raw. Offline — no network,
never touches the real ledgers. Runs in refresh-backtest-data.yml before the updater.

Run: python3 scripts/test_no_ca_inference.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = [sys.argv[0]]
sys.path.insert(0, HERE)
import update_sf_data as U

U.B.fetch_day = lambda d, j: []  # no network in tests
U.UNC_PATH = tempfile.mktemp()  # never touch the real ledger
ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


# 1. crash, no record (POLICYBZR 2026-09-24 real numbers) -> kept raw, parked
U.UNCONFIRMED.clear()
f = U.ingest_factor(
    "2026-09-24", "POLICYBZR", 20260924, 20260923, 1886.3, 1207.2, 1697.7, None, None, "2026-09-25"
)
check("crash w/o record kept raw", f == 1.0)
check(
    "crash parked",
    "20260924" in U.UNCONFIRMED.get("POLICYBZR", {})
    and U.UNCONFIRMED["POLICYBZR"]["20260924"]["prev"] == 1886.3,
)
# 2. official split (CHAVDA 1:2 2026-09-24, prev 139.98 -> 70.3) -> official factor
check(
    "official split applied",
    U.ingest_factor("d", "CHAVDA", 20260924, 20260923, 139.98, 70.3, 74.0, 0.5, None, "x") == 0.5,
)
check("official split not parked", "CHAVDA" not in U.UNCONFIRMED)
# 3. official split on a violent day: close ratio off the band, open at basis -> official (§87c)
check(
    "open-gate rescue",
    U.ingest_factor("d", "JSTEST", 20080121, 20080118, 2393.99, 350.71, 493.5, 0.2, None, "x")
    == 0.2,
)
# 4. official record contradicted by close AND open -> kept raw + parked
check(
    "contradicted record kept raw",
    U.ingest_factor("d", "CONTRA", 20260101, 20251231, 100.0, 30.0, 99.0, 0.5, None, "x") == 1.0
    and "CONTRA" in U.UNCONFIRMED,
)
# 5. demerger ex-date -> kept raw, not parked
check(
    "demerger kept, not parked",
    U.ingest_factor("d", "DEM", 20260430, 20260429, 773.0, 271.0, 280.0, None, {20260430}, "x")
    == 1.0
    and "DEM" not in U.UNCONFIRMED,
)
# 6. ordinary day -> 1.0, not parked
check(
    "normal move untouched",
    U.ingest_factor("d", "NORM", 20260102, 20260101, 100.0, 95.0, 99.0, None, None, "x") == 1.0
    and "NORM" not in U.UNCONFIRMED,
)

# 7. self_heal: bin that INFERRED 2/3 on a crash, crash listed -> history restored to raw
U.UNCONFIRMED.clear()
data = {
    "POLICYBZR": {
        "d": [20260922, 20260923, 20260924],
        "c": [round(1805 * 2 / 3, 2), round(1886.3 * 2 / 3, 2), 1207.2],
        "h": [1, 1, 1],
        "l": [1, 1, 1],
        "op": [1, 1, 1697.7],
        "vw": [1, 1, 1],
    }
}
U.LEGACY_FALSE_CA.append(("POLICYBZR", 20260924))
raw = {"POLICYBZR": {"20260923": 1886.3, "20260924": 1207.2}}
RAWF = tempfile.mktemp(suffix=".json")
json.dump(raw, open(RAWF, "w"))
orig_open = open


def fake_open(p, *a, **k):  # serve the test's raw closes in place of scripts/crash_raw_prices.json
    if str(p).endswith("crash_raw_prices.json"):
        return orig_open(RAWF, *a, **k)
    return orig_open(p, *a, **k)


import builtins

builtins.open = fake_open
try:
    h = U.self_heal(data, {}, {}, 20260924, None)
finally:
    builtins.open = orig_open
    os.remove(RAWF)
check("phantom heal ran", h == 1)
check(
    "pre-crash close back to raw 1886.3",
    abs(data["POLICYBZR"]["c"][1] - 1886.3) < 0.02 and abs(data["POLICYBZR"]["c"][0] - 1805) < 0.02,
)
U.LEGACY_FALSE_CA.pop()

# 8. kept-raw move 90 days ago (outside the 28-day window), official record appears later -> applied
U.UNCONFIRMED.clear()
U.UNCONFIRMED["LATE"] = {
    "20260601": {
        "prev_d": 20260529,
        "prev": 200.0,
        "close": 101.0,
        "open": 100.0,
        "ratio": 0.505,
        "seen": "2026-06-01",
    }
}
data = {
    "LATE": {
        "d": [20260529, 20260601, 20260602],
        "c": [200.0, 101.0, 102.0],
        "h": [1, 1, 1],
        "l": [1, 1, 1],
        "op": [1, 100.0, 1],
        "vw": [1, 1, 1],
    }
}
h = U.self_heal(data, {"LATE": {20260601: 0.5}}, {}, 20260901, None)
check(
    "late official record applied beyond 28d window (raw closes from the queue)",
    h == 1 and abs(data["LATE"]["c"][0] - 100.0) < 0.02,
)
# 9. same event run again -> idempotent
h2 = U.self_heal(data, {"LATE": {20260601: 0.5}}, {}, 20260901, None)
check("idempotent second pass", h2 == 0)
# 10. pruning: LATE is reconciled (official applied) -> pruned; KEEP (no record) stays; CR (listed crash, 2 days off) pruned
U.UNCONFIRMED["KEEP"] = {
    "20260701": {"prev_d": 20260630, "prev": 100.0, "close": 50.0, "ratio": 0.5}
}
U.UNCONFIRMED["CR"] = {"20260702": {"prev_d": 20260701, "prev": 100.0, "close": 60.0, "ratio": 0.6}}
U.LEGACY_FALSE_CA.append(("CR", 20260704))
n = U.prune_unconfirmed(data, {"LATE": {20260601: 0.5}}, {})
check(
    "prune: reconciled + crash-listed removed, unverified kept",
    n == 2
    and "LATE" not in U.UNCONFIRMED
    and "CR" not in U.UNCONFIRMED
    and "KEEP" in U.UNCONFIRMED,
)
# 11. official record present but NOT yet applied in the series -> stays parked
U.UNCONFIRMED["PEND"] = {
    "20260601": {"prev_d": 20260529, "prev": 200.0, "close": 101.0, "ratio": 0.505}
}
d2 = {"PEND": {"d": [20260529, 20260601], "c": [200.0, 101.0]}}
U.prune_unconfirmed(d2, {"PEND": {20260601: 0.5}}, {})
check("prune: official but unapplied stays parked", "PEND" in U.UNCONFIRMED)
U.save_unconfirmed()
check("ledger written as json", isinstance(json.load(open(U.UNC_PATH)), dict))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)

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
"""Guard: the MIDNIGHT visibility rule (runbook §149) MUST be what BOTH SHP ingestion paths apply.

History: commit 2ee1e235c (2026-09-05 13:33) wired the §12 15:30 gate (`visible_iso()`) into refresh_quarters()
and refresh_events(); commit 66a241e4f (13:41 the same day, a different workstream carrying a stale copy of
fetch_shareholding.py) silently deleted it, and nobody noticed for 16 days because nothing asserted it (§142a).
On 2026-09-23 the user retired the 15:30 gate: a filing is visible on the CALENDAR DAY it was broadcast, whatever
the time (they buy at the next session's open). The same clobber class can bring the old rule — or the pre-§135j
raw-submissionDate form — back, so this guard asserts the CURRENT rule's behaviour, not just a function's presence.

Run before the fetch steps in refresh-shareholding.yml. Exit 1 = do not fetch, do not commit."""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "fetch_shareholding.py"), encoding="utf-8").read()
errs = []
if "def visible_iso(rec):" not in src:
    errs.append("visible_iso() is missing from fetch_shareholding.py")
if "def legacy_gate_iso(rec):" not in src or "def regate_recent(" not in src:
    errs.append("legacy_gate_iso()/regate_recent() (the §149 recogniser for rows the retired gate dated) are missing")
# The two INGESTION functions must date rows through visible_iso — checked by name, not by counting call
# sites file-wide: the count-of-2 form broke the moment bank_sme_shares (§145, 2026-09-23 01:00) added a
# third, harmless call and every shareholding run from 22-Sep 19:42Z failed on the guard, not on data.
funcs = {n.name: ast.get_source_segment(src, n) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)}
n_calls = 0
for fn in ("refresh_quarters", "refresh_events"):
    body = funcs.get(fn) or ""
    if "visible_iso(r)" not in body:
        errs.append(f"{fn}() does not date its rows through visible_iso(r)")
    else:
        n_calls += 1
if re.search(r'sub = iso_date\(r\.get\("submissionDate"\)\)', src):
    errs.append("an ingestion path still assigns the RAW submissionDate")
cases = []
if not errs:
    sys.path.insert(0, HERE)
    import fetch_shareholding as F

    # MIDNIGHT rule: the broadcast's calendar day, never shifted — after-close, weekend, holiday alike.
    cases = [
        ("17-JUL-2026 12:24:26", "2026-07-17"),  # before close, trading day -> same day
        ("17-OCT-2025 16:46:27", "2025-10-17"),  # Friday after close -> still Friday
        ("28-MAR-2026 20:37:02", "2026-03-28"),  # Saturday -> Saturday (visible to Monday's screen via <=)
        ("01-JUL-2026 17:47:11", "2026-07-01"),  # weekday after close -> same day
        ("25-JAN-2026 10:00:00", "2026-01-25"),
    ]  # Sunday before Republic Day -> Sunday
    for b, exp in cases:
        got = F.visible_iso({"broadcastDate": b, "submissionDate": b[:11]})
        if got != exp:
            errs.append(f"midnight-rule self-test: {b} -> {got}, expected {exp}")
    # The retired gate must still be RECOGNISABLE (regate_recent compares stored dates against it) —
    # if its behaviour drifts, --regate silently stops finding the rows it is meant to move.
    legacy = [
        ("17-OCT-2025 16:46:27", "2025-10-20"),
        ("28-MAR-2026 20:37:02", "2026-03-30"),
        ("01-JUL-2026 17:47:11", "2026-07-02"),
        ("17-JUL-2026 12:24:26", "2026-07-17"),
    ]
    for b, exp in legacy:
        got = F.legacy_gate_iso({"broadcastDate": b, "submissionDate": b[:11]})
        if got != exp:
            errs.append(f"legacy-gate recogniser self-test: {b} -> {got}, expected {exp}")
if errs:
    for e in errs:
        print("GATE GUARD FAIL:", e)
    sys.exit(1)
print(
    "visibility guard OK: midnight rule in visible_iso, %d call sites, %d self-test cases pass, legacy recogniser intact"
    % (n_calls, len(cases))
)

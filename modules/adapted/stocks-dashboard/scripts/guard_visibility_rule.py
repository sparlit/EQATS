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
"""Guard: the MIDNIGHT visibility rule (runbook §149) must be what every fundamentals date writer applies,
and the retired 15:30 gate must not be wired back into the nightly.

Why: the §142a clobber class — a stale copy of a script committed by another workstream silently reverted a
visibility function for 16 days and nothing asserted its behaviour. The rule the user chose on 2026-09-23
("a filing counts for the day it was broadcast, whatever the time — I buy at the next open") is enforced by
BEHAVIOUR here, not by grepping for a function name: the two `gated_ann()` functions are extracted from their
files and run against fixed timestamps, so a re-introduced after-close shift fails the job before anything is
committed. Also refuses a refresh-fundamentals.yml that still runs gate_1530.py --apply, or a
backfill_ann_dates_bse.py that still carries the +4-day gate buffer.

Run before the ingestion steps in refresh-fundamentals.yml. Exit 1 = do not commit."""
import ast
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
errs = []
MON = {
    m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])
}


def func_src(path, name):
    src = open(path, encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


class _B:  # the only helper update_fundamentals.gated_ann needs (bse helper's iso(): "16-Jan-2025 20:20" -> "20250116")
    @staticmethod
    def iso(s):
        m = re.match(r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})", s or "")
        return (
            "%s%02d%02d" % (m.group(3), MON[m.group(2).upper()], int(m.group(1)))
            if m and m.group(2).upper() in MON
            else None
        )


def run(path, name, ns, cases):
    seg = func_src(path, name)
    if not seg:
        errs.append(f"{os.path.basename(path)}: {name}() missing")
        return
    env = dict(ns)
    exec(seg, env)
    for arg, exp in cases:
        got = env[name](arg)
        if got != exp:
            errs.append(
                f"{os.path.basename(path)}.{name}({arg!r}) -> {got!r}, expected {exp!r} (midnight rule: the broadcast's calendar day, never shifted)"
            )


run(
    os.path.join(HERE, "update_fundamentals.py"),
    "gated_ann",
    {"re": re, "datetime": datetime, "B": _B},
    [
        ("16-Jan-2025 20:20", "20250116"),  # after close -> same day
        ("30-Oct-2020 17:08", "20201030"),  # JSL, the old gate's proof case -> same day
        ("17-Oct-2025 16:46", "20251017"),  # Friday after close -> Friday
        ("28-Mar-2026 10:00", "20260328"),  # Saturday -> Saturday
        ("", "99999999"),
    ],
)  # no date -> sentinel
run(
    os.path.join(HERE, "reconcile_missing_quarters.py"),
    "gated_ann",
    {"re": re, "datetime": datetime, "yyyymmdd": lambda d: d.year * 10000 + d.month * 100 + d.day},
    [
        ("2026-08-04T20:02:14.153", 20260804),
        ("2020-10-30T17:08:23.81", 20201030),
        ("2026-08-05T18:00:58", 20260805),
        ("2026-08-05T09:15:00", 20260805),
        ("garbage", None),
    ],
)

wf = open(os.path.join(ROOT, ".github", "workflows", "refresh-fundamentals.yml"), encoding="utf-8").read()
if re.search(
    r"(?m)^\s*python3\s+scripts/gate_1530\.py", wf
):  # an EXECUTED line; comments may name it, ungate_1530 is the mirror
    errs.append("refresh-fundamentals.yml still runs gate_1530.py (the retired 15:30 gate)")
if "ungate_1530.py --apply" not in wf or "build_gate_events.py --calendar --ungate" not in wf:
    errs.append(
        "refresh-fundamentals.yml is missing the nightly ungate mirror (build_gate_events --ungate + ungate_1530 --apply)"
    )
bf = open(os.path.join(HERE, "backfill_ann_dates_bse.py"), encoding="utf-8").read()
if "plus(ann, 4)" in bf:
    errs.append("backfill_ann_dates_bse.py still carries the +4-day gate buffer on override entries")

if errs:
    for e in errs:
        print("VISIBILITY GUARD FAIL:", e)
    sys.exit(1)
print(
    "visibility guard OK: midnight rule in update_fundamentals + reconcile_missing_quarters, nightly runs the ungate mirror, no gate buffer"
)

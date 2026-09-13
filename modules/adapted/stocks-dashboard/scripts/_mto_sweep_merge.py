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
"""§88b MTO sweep — MERGE stage. Union of new_fills.json into scripts/dv_fill_hist.json.gz.
Existing ledger cells are preserved verbatim (old-wins); only genuinely new (sym,date) cells
are added. Deterministic gzip (mtime=0). Prints per-year added counts + final ledger stats."""
import gzip
import json
import os
from collections import Counter

SP = os.environ.get("MTO_SP", os.path.expanduser("~/.cache/mto_sweep"))
HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "dv_fill_hist.json.gz")

old = json.load(gzip.open(LEDGER, "rt", encoding="utf-8"))
new = json.load(open(os.path.join(SP, "new_fills.json")))
fills = old["fills"]

added = Counter()
kept = 0
for sym, days in new.items():
    tgt = fills.setdefault(sym, {})
    for ds, v in days.items():
        if ds in tgt:
            kept += 1
            continue
        tgt[ds] = v
        added[ds[:4]] += 1

# wrong-company corrections: cells where the STORED ledger value contradicts the
# volume-matched MTO row (the 2026-08-02 build keyed some renamed-collision symbols to the
# wrong company's row — DVL got DPL's pct on bars whose volume matches DTIL's row).
# Correct ONLY cells this ledger itself carries; live bins already baked with the old value
# stay wrong until an overwrite pass (fill-only can't touch dv>0) — queued separately.
wrong = json.load(open(os.path.join(SP, "wrong_cells.json")))
fixed = skipped_elsewhere = 0
for sym, ds, oldv, newv in wrong:
    cell = fills.get(sym, {}).get(ds)
    stored = cell[0] if isinstance(cell, list) else cell
    if stored is not None and abs(stored - oldv) <= 0.011:
        fills[sym][ds] = newv
        fixed += 1
    else:
        skipped_elsewhere += 1
print(
    "wrong-company corrections: %d applied in-ledger, %d not-from-this-ledger (left alone)" % (fixed, skipped_elsewhere)
)

old["_meta"]["built"] = "2026-08-11"
old["_meta"]["src"] += (
    " | 2026-08-11 §88b full-universe DAILY sweep: nsearchives MTO_*.DAT for every"
    " bin trading date with a dv==0 bar, 2002-01-02 -> 2026-08 (the 2026-08-02 build"
    " had sampled ~weekly Mondays pre-2018 — see DATA_RUNBOOK §88b)"
)
old["_meta"]["rule"] += (
    " | 4-field era (2002-01-02..2002-02-11): files carry 20,SYM,SERIES,DELIV_QTY"
    " (header total == sum(qty) proves qty=deliverable); pct computed as"
    " qty/bin-volume, validated by bin_v==MTO_traded 99.7% on 7-field days and"
    " existing-dv==MTO-pct 100.000% on the overlap"
)

blob = json.dumps(old, separators=(",", ":")).encode()
with open(LEDGER, "wb") as f:
    gzip.GzipFile(fileobj=f, mode="wb", mtime=0).write(blob)

print("added per year:")
for y in sorted(added):
    print(" ", y, added[y])
print("total added:", sum(added.values()), "| already-present skipped:", kept)
print(
    "ledger now: %d symbols, %d cells, %.2f MB gz"
    % (len(fills), sum(len(v) for v in fills.values()), os.path.getsize(LEDGER) / 1048576)
)

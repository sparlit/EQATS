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
"""Retract SYNGENE 20150331 conPAT/annCon — a FABRICATED_PREFLOOR std-copy the 2026-08-18
con-copy campaign missed (its cell enumeration keyed off sf_revop rows; Mar-2015 had none).

Ledger entry: scripts/con_copy_retractions.json "SYNGENE|20150331" (adjudication + floor evidence
there). Same mechanics as the campaign: null slots 3 (npCon) and 4 (annCon) in BOTH twins, guarded
on the recorded was-values (conPAT 55.6, annCon 20150530) so a re-run or a moved-on cell is a
no-op. One-shot; keep for audit, do not re-run against a future re-adjudicated cell.

Run: python3 scripts/fill2020_tools/retract_con_syngene_20150331.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
TWINS = [os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json")]
LEDGER = os.path.join(SCRIPTS, "con_copy_retractions.json")


def main():
    apply = "--apply" in sys.argv
    ent = json.load(open(LEDGER)).get("SYNGENE|20150331")
    if not ent:
        print("ledger entry SYNGENE|20150331 missing from con_copy_retractions.json — refusing")
        sys.exit(1)
    was_pat = ent["slots"]["conPAT"]
    was_ann = ent["slots"]["annCon"]
    for path in TWINS:
        d = json.load(open(path))
        rel = os.path.relpath(path, ROOT)
        row = next((r for r in d.get("SYNGENE", []) if r[0] == 20150331), None)
        if row is None or len(row) < 5:
            print(f"  [{rel}] row absent/short — nothing to do")
            continue
        if row[3] is None and row[4] is None:
            print(f"  [{rel}] already retracted")
            continue
        if row[3] != was_pat or (row[4] not in (was_ann, None)):
            print(f"  [{rel}] holds con={row[3]} ann={row[4]}, ledger was {was_pat}/{was_ann} — moved on, refusing")
            continue
        print(f"  [{rel}] SYNGENE 20150331: con {row[3]}/{row[4]} -> null/null")
        if apply:
            row[3] = None
            row[4] = None
            json.dump(d, open(path, "w"), separators=(",", ":"))
            print(f"  wrote {rel}")
    if not apply:
        print("(dry run — pass --apply to write)")


if __name__ == "__main__":
    main()

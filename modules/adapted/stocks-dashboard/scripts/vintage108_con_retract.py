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
"""RETRACT the consolidated heals that moved an OWNERS slot onto a TOTAL-basis figure.

MY OWN DEFECT, found 2026-08-25 by runbook §111d and confirmed cell by cell. Our `con` PAT slot
holds OWNERS-ATTRIBUTABLE profit (§profit-basis). Two mistakes compounded:

  1. NSE's consolidated archive page prints "Net Profit ... after taxes, minority interest and
     share of profit of associates", and that line does NOT reliably compute the owners figure —
     the sign of the associate/NCI term goes the other way (§111d: BAJAJHLDNG Mar-2016 prints
     P - A where the owners figure is P + A).
  2. The second reader I gated on was Moneycontrol's `pat_total` — the TOTAL row — not `pat_own`.
     So the gate compared two TOTAL-basis readings, agreed, and wrote the result into an
     OWNERS-basis slot. It could not have caught the error: both voices were on the wrong basis.

BHARTIARTL Mar-2017 is the clearest: store 373.40 = MC owners; I wrote 219.80 = MC total.

RE-ADJUDICATION used an owners-basis reader only, in this order:
  1. `_reattr_owners.json` — DEFINITIONAL, built from the filings' XBRL
     ProfitOrLossAttributableToOwnersOfParent;
  2. Moneycontrol `pat_own` ("Net P/L After M.I & Associates").
Verdicts over my 143 con heals: 78 REVERT (owners backs the pre-heal value), 58 correct,
6 owners-backs-neither, 1 no reader.

WHAT THIS RETRACTS: the 78, plus the 7 my gate cannot support either way — a heal whose gate was
structurally wrong is not "unproven", it is unsupported, and it does not get to stay on live data
while it waits for a document. The 58 an owners reader confirms are KEPT.

Entries are MOVED to a `retracted` list in the ledger rather than deleted, so the audit trail
survives, and because §109j now re-applies these ledgers every refresh a stale entry left in
`fixes` would be re-asserted nightly forever.

GUARDED: a payload cell that no longer holds my `fixed` value is left alone and reported — another
writer has since moved it and this retraction must not overwrite them.

RUN:  python3 scripts/vintage108_con_retract.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
READJ = os.path.join(HERE, "_vintage108_con_readjud.json")
FUND_LED = os.path.join(HERE, "fund_cell_fix.json")
REVOP_LED = os.path.join(HERE, "revop_cell_fix.json")
TARGETS = {
    "fund": [os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(HERE, "fundamentals.json")],
    "revop": [os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(HERE, "revop_fundamentals.json")],
}
TOL = 0.011
DROP = ("REVERT", "OWNERS BACKS NEITHER", "NO-OWNERS-READER")


def main():
    apply = "--apply" in sys.argv
    readj = json.load(open(READJ, encoding="utf-8"))
    kill = {k for k, v in readj.items() if v[0].startswith(DROP)}
    keep = {k for k, v in readj.items() if k not in kill}
    print("con heals re-adjudicated: %d | RETRACT %d | keep %d" % (len(readj), len(kill), len(keep)))

    # ---- 1. restore the payload cells to their pre-heal value --------------------------
    restored = blocked = absent = 0
    for kind, slot, _ledkey in (("fund", 3, "con"), ("revop", 5, "pat_con")):
        for path in TARGETS[kind]:
            if not os.path.exists(path):
                continue
            d = json.load(open(path, encoding="utf-8"))
            n = 0
            for k in sorted(kill):
                sym, qe = k.split("|")
                was, fixed = readj[k][3], readj[k][4]
                if kind == "revop":
                    row = (d.get(sym) or {}).get(qe)
                else:
                    row = next((r for r in d.get(sym, []) if r[0] == int(qe)), None)
                if row is None or len(row) <= slot or row[slot] is None:
                    absent += 1
                    continue
                if abs(row[slot] - fixed) > TOL:
                    if abs(row[slot] - was) > TOL:
                        blocked += 1
                        print(
                            f"  BLOCKED {sym} {qe}: holds {row[slot]}, my heal wrote {fixed} — another writer moved "
                            "it, left alone"
                        )
                    continue
                row[slot] = was
                n += 1
            print("  [%s] %s: %d cells restored to their pre-heal value" % (kind, os.path.basename(path), n))
            restored = max(restored, n)
            if apply and n:
                json.dump(d, open(path, "w"), separators=(",", ":"))

    # ---- 2. move the ledger entries to `retracted` -------------------------------------
    why = (
        "RETRACTED 2026-08-25 (runbook §111d/§112): this heal moved the OWNERS-basis con slot "
        "onto the NSE archive page's bottom line, which is not the owners figure, and the gate's "
        "second reader was Moneycontrol pat_TOTAL rather than pat_own — two total-basis voices "
        "agreeing. Re-adjudicated against an owners-basis reader (XBRL "
        "ProfitOrLossAttributableToOwnersOfParent, else MC pat_own): "
    )
    for path, bkeys in ((FUND_LED, ("con",)), (REVOP_LED, ("pat_con",))):
        led = json.load(open(path, encoding="utf-8"))
        out, moved = [], led.get("retracted") or []
        for f in led["fixes"]:
            k = "{}|{}".format(f.get("sym"), f.get("qe"))
            if f.get("basis") in bkeys and k in kill and "vintage108" in (f.get("found") or ""):
                v = readj[k]
                f["retracted_why"] = why + (f"{v[1]} reads {v[2]}, backing the pre-heal {v[3]} over my {v[4]}.")
                moved.append(f)
            else:
                out.append(f)
        print(
            "  [%s] fixes %d -> %d | retracted list %d"
            % (os.path.basename(path), len(led["fixes"]), len(out), len(moved))
        )
        led["fixes"], led["retracted"] = out, moved
        if apply:
            json.dump(led, open(path, "w"), indent=1, ensure_ascii=False)
    print("\nblocked (another writer moved the cell): %d | slot absent: %d" % (blocked, absent))
    if not apply:
        print("\n(dry run — pass --apply to write)")


if __name__ == "__main__":
    main()

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
"""Settle a RESURRECTED cell automatically when a FILING-SOURCED ledger already outranks the hold.

WHY THIS EXISTS. Three times in two days (2026-08-16 x2, 2026-08-17) the blocking
verify_fills_live.py step in refresh-fundamentals.yml went red on RESURRECTED, froze the whole
fundamentals payload pre-commit, and mailed 6 notices per run through auto-rerun. Every time the
shape was identical and the resolution was identical:

  * a fill pass READ a consolidated cell out of a primary filing and journalled the provenance
    (scripts/conpat_filing_fills.json and friends);
  * the same cell was still flagged `held` in an AGGREGATOR ledger (mc_pat_fills.json /
    mc_history_fills.json), and a held cell asserts ABSENCE (runbook 56b);
  * so two ledgers asserted opposite things and the guard was guaranteed red;
  * and the fix was to lift the aggregator's hold, because the hold was stale.

★ THE RULE THIS AUTOMATES IS THE ONE THE HOLDS THEMSELVES STATE. Every one of these holds rests on
the weak test "this source's consolidated == our standalone, and this company consolidates
differently elsewhere", which cannot separate an aggregator repeating standalone from a company whose
consolidated genuinely equals its standalone. Their own text names the exit:

    "UNRESOLVED, not a proven copy ... Settle from the filing (57/58), not this source."

So when a filing-sourced ledger asserts that exact cell at that exact value, the hold has already
been answered by the route it asked for, and it is stale by construction. That is a mechanical
judgement about SOURCE RANK, not about the number.

★★★ WHAT THIS DELIBERATELY WILL NOT DO. It never touches a payload cell, and it never lifts a hold
that no filing-sourced ledger backs. A resurrected value with NO document behind it is the dangerous
case the guard exists for -- an aggregator's standalone copy manufactured into a consolidated slot --
and those still fail the run loudly. Auto-lifting on the mere fact that a value is live would delete
the guard entirely: measured on 2026-08-11, six `held` flags were wrong AND seven of twenty-eight
retractions were wrong, so neither side is automatically right. Only the source hierarchy is.

Ranking comes from where a ledger's numbers come from, not from its name:
  FILING_SOURCED  = read out of an exchange filing / its XBRL / a filed PDF (the top of 57's ladder)
  AGGREGATOR      = Moneycontrol / Trendlyne / screener feeds, whose con column can echo standalone

Run:  python3 -X utf8 scripts/settle_stale_holds.py            # report only
      python3 -X utf8 scripts/settle_stale_holds.py --apply    # lift what is settled, write ledgers
Exit 0 when nothing is resurrected or everything resurrected is settleable (and, with --apply, was
settled). Exit 1 when any resurrected cell has no filing-sourced backing -- that is a real conflict
for a human, and it is exactly the case that must keep failing.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Reuse the DETECTOR's own registry so this tool can never drift out of step with what CI checks.
from verify_fills_live import (  # noqa: E402
    BASIS_KEYED,
    BASIS_SLOT,
    FUND,
    LEDGERS,
    REVOP,
    TOL,
)

# Ledgers whose values were read from a primary filing. These OUTRANK an aggregator hold.
FILING_SOURCED = {
    "conpat_filing_fills.json",  # 2026-08-16+ con PAT/revenue read from NSE per-basis XBRL or filed PDF
    "nse_xbrl_rev_fills.json",  # NSE archive XBRL
    "con_rev_nse_reads.json",
    "con_pat_nse_reads.json",
    "std_rev_nse_reads.json",
    "std_rev_detres_fills.json",
    "std_pat_detres_fills.json",
    "insurer_con_rev_fills.json",  # 55: read out of the filing PDF
    "named_rev_cell_fills.json",  # 57/58 hand-read cells, anchor chain journalled beside the value
    "named_rev_cell_fills_2018.json",
    "named_rev_cell_fills_2019.json",
    "named_pat_cell_fills.json",
    "con_pat_fy_derived.json",  # derived FROM filed annuals
    "con_nofile_identity_fills.json",
}
# Fields worth quoting when we point at the ledger that settled a cell.
PROV_KEYS = (
    "src",
    "evidence",
    "anchor",
    "identity",
    "filed",
    "fallback_check",
    "convention",
    "why",
    "note",
    "fill_pass",
    "campaign",
    "when",
)


def claims():
    """Yield every flat-ledger claim as a uniform record.

    Covers exactly the two registries verify_fills_live's RESURRECTED check walks (BASIS_KEYED and
    LEDGERS); its NESTED loop has no `held` branch, so a nested ledger can never resurrect a cell.
    """
    for entry in BASIS_KEYED:
        name, payload, key = entry[0], entry[1], entry[2]
        slotmap = entry[3] if len(entry) > 3 else BASIS_SLOT
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            continue
        try:
            led = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for k, v in led.items():
            parts = k.split("|")
            if len(parts) != 3 or not isinstance(v, dict):
                continue
            if v.get("skip") or v.get(key) is None:
                continue
            slot = slotmap.get(parts[2])
            if slot is None:
                continue
            yield {
                "ledger": name,
                "path": path,
                "led": led,
                "key": k,
                "entry": v,
                "vkey": key,
                "sym": parts[0],
                "qe": parts[1],
                "payload": payload,
                "slot": slot,
                "value": v[key],
            }
    for name, payload, key, slot in LEDGERS:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            continue
        try:
            led = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for k, v in led.items():
            if not isinstance(v, dict) or v.get("skip") or key not in v or v[key] is None:
                continue
            if "|" not in k:
                continue
            sym, qe = k.rsplit("|", 1)
            yield {
                "ledger": name,
                "path": path,
                "led": led,
                "key": k,
                "entry": v,
                "vkey": key,
                "sym": sym,
                "qe": qe,
                "payload": payload,
                "slot": slot,
                "value": v[key],
            }


def main():
    apply = "--apply" in sys.argv
    revop = json.load(open(REVOP, encoding="utf-8"))
    fund = json.load(open(FUND, encoding="utf-8"))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    def live(payload, sym, qe, slot):
        row = (revop.get(sym) or {}).get(str(qe)) if payload == "revop" else (fmap.get(sym) or {}).get(int(qe))
        return row[slot] if row and len(row) > slot else None

    all_claims = list(claims())
    # (payload, slot, sym, qe) -> the filing-sourced claims on that exact cell
    backing = {}
    for c in all_claims:
        if c["ledger"] in FILING_SOURCED and not c["entry"].get("held"):
            backing.setdefault((c["payload"], c["slot"], c["sym"], str(c["qe"])), []).append(c)

    settled, unsettled = [], []
    for c in all_claims:
        if not c["entry"].get("held"):
            continue
        cur = live(c["payload"], c["sym"], c["qe"], c["slot"])
        if cur is None or abs(cur - c["value"]) > TOL:
            continue  # hold still honoured; nothing to do
        cell = (c["payload"], c["slot"], c["sym"], str(c["qe"]))
        src = [b for b in backing.get(cell, []) if abs(b["value"] - cur) <= TOL]
        (settled if src else unsettled).append((c, src))

    print("RESURRECTED cells: %d settleable from a filing-sourced ledger, %d NOT" % (len(settled), len(unsettled)))
    # ★ ALL-OR-NOTHING. If anything is unsettled the run fails, and in CI that aborts before the commit
    # step — so writing the settleable ones anyway would be churn that never persists, while locally it
    # leaves a half-changed tree for the human who now has to adjudicate the rest. Either the whole
    # contradiction is mechanically resolvable or a person looks at all of it. (Caught by the negative
    # control, which is the only reason this is not the other way round.)
    if unsettled and apply:
        print(
            "\n★ NOT WRITING ANYTHING: %d resurrected cell(s) have no filing-sourced backing, so this"
            " needs a human. Re-run --apply once those are adjudicated." % len(unsettled)
        )
        apply = False
    stamp = time.strftime("%Y-%m-%d %H:%M IST")
    touched = {}
    for c, src in settled:
        b = src[0]
        print("\n  SETTLE  {}  {}  slot={}  value={}".format(c["ledger"], c["key"], c["slot"], c["value"]))
        print("     outranked by {} ({})".format(b["ledger"], b["key"]))
        for pk in PROV_KEYS:
            if b["entry"].get(pk):
                print("       %-14s %s" % (pk + ":", str(b["entry"][pk])[:150]))
        if apply:
            note = (
                "STALE HOLD SETTLED AUTOMATICALLY {} by scripts/settle_stale_holds.py. This hold "
                "asked to be settled from the filing (57/58), and {} now asserts the same value "
                "{} for this cell from a primary filing, which outranks this aggregator read. The "
                "payload was NOT changed. Provenance in that ledger under key {}: {}".format(
                    stamp,
                    b["ledger"],
                    c["value"],
                    b["key"],
                    " | ".join("{}={}".format(pk, str(b["entry"][pk])[:400]) for pk in PROV_KEYS if b["entry"].get(pk)),
                )
            )
            c["entry"].pop("held")
            c["entry"]["fallback_check"] = note
            touched[c["path"]] = c["led"]
    for c, _ in unsettled:
        print("\n  ★ UNSETTLED — NO filing-sourced ledger backs this value. This is the case the guard")
        print("    exists for; a human must adjudicate it (runbook 56b/57).")
        print("    {}  {}  slot={}  value={}".format(c["ledger"], c["key"], c["slot"], c["value"]))
        print("    held because: {}".format(str(c["entry"]["held"])[:220]))

    if apply and touched:
        for path, led in touched.items():
            # match the shape these ledgers already have (indent=1, sort_keys, \uXXXX, no trailing NL)
            json.dump(led, open(path, "w"), indent=1, sort_keys=True)
            print(f"\nWROTE {os.path.basename(path)}")
    elif settled and not apply:
        print("\n(dry run — re-run with --apply to lift the %d settleable hold(s))" % len(settled))

    return 1 if unsettled else 0


if __name__ == "__main__":
    sys.exit(main())

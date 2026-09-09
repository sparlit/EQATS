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
"""Run the screener.in gate (§60c) over EVERY currently-open rev cell, and fill what passes.

Why this runs before any more vision: on the two cells I actually paid vision for (SUNDROP,
TATACAP) this route resolved BOTH for free, 6/6 and 7/7 on the gate, while the rendered pages
turned out to be an auditor signature page and a credit-rating annexure. Cheapest reader first,
always — and screener is one cached HTTP fetch per company/basis, versus a PDF download plus a
render plus a vision read per cell.

COVERAGE, measured (§60a): screener's quarterly table holds only the trailing ~13 quarters, so this
pass can only reach roughly 2023+. Older cells are the annual-derivation route's job
(screener_annual_sweep.py) and are reported here, not silently skipped.

THE GATE IS UNCHANGED: screener's own series must reproduce >=2 values we already store for that
field with ZERO disagreements, else the whole series is rejected (that is what caught TMPV's
demerger break). Values are crore-rounded and journalled as such.

HELD BACK, not written: a cell whose gated value rounds to our stored value on the OTHER basis.
`con == std` is the exact signature of the is_con_basis copy bug (§56) and of the copied-con purge,
so an automatic fill there is indistinguishable from the defect we spent this campaign removing.
Legitimate cases exist -- SUNDROP Dec-2024 has con PAT 3.91 vs std 3.13 but identical revenue,
the fingerprint of an equity-method associate that adds profit and no revenue -- but they need a
deliberate identity marker, not a silent write.

  python -X utf8 scripts/fill2020_tools/screener_fill_all.py [--apply] [--limit N]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
import build_targets as BT  # noqa: E402
import screener_gate as G  # noqa: E402

REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "screener_rev_fills.json")
SLOT = {"revS": 0, "revC": 1}
OUT = "/tmp/screener_pass.json"


def main():
    apply_it = "--apply" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**9

    sys.argv = ["build_targets", "--from", "20150331", "--to", "20260331", "--out", "/tmp/_bt.json"]
    BT.main()
    targets = json.load(open("/tmp/_bt.json"))
    revop = json.load(open(REVOP_DOCS))

    passed, held, failed, uncovered = {}, [], 0, 0
    for n, key in enumerate(sorted(targets)):
        if n >= limit:
            break
        sym, qe, field = key.split("|")
        qe = int(qe)
        try:
            val, note = G.check(sym, qe, field)
        except Exception:
            failed += 1
            continue
        if val is None:
            if "absent" in note:
                uncovered += 1  # outside screener's 13-quarter window -> annual route
            else:
                failed += 1
            continue
        # ZERO GUARD (2026-08-11): screener prints crore-rounded integers, so a genuine sub-0.5cr
        # revenue and a NOT-REPORTED quarter both render as "0". Writing 0 asserts the company
        # earned nothing — a far stronger claim than the source supports (a feed's 0 can mean NO
        # BASE, not zero). Hold it for a filing read rather than guess which meaning applies.
        # Caught OLAELEC 20231231 revS, whose sibling quarters read 60/9/6 — a holdco whose
        # operations sit in the subsidiary, exactly where "0" is most ambiguous.
        if val == 0:
            held.append((key, val, "ZERO — may be not-reported rather than nil revenue"))
            continue
        other = SLOT["revS" if field == "revC" else "revC"]
        row = (revop.get(sym) or {}).get(str(qe)) or []
        twin = row[other] if len(row) > other else None
        if twin is not None and abs(val - twin) <= max(1.0, abs(twin) * 0.01):
            held.append((key, val, twin))
            continue
        passed[key] = {"value": val, "note": note}
        print("  PASS %-28s %-11s %s" % (key, val, note[:58]))

    print(
        "\npassed gate %d | held (con==std identity) %d | outside screener window %d | "
        "gate-failed %d | of %d open" % (len(passed), len(held), uncovered, failed, len(targets))
    )
    for k, v, t in held[:10]:
        print("  held  %-28s %-10s == other-basis %s" % (k, v, t))
    json.dump({"passed": passed, "held": [list(h) for h in held]}, open(OUT, "w"), indent=1)

    if not apply_it:
        print(f"DRY RUN -- nothing written. ({OUT})")
        return
    journal = {}
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for key, rec in passed.items():
            sym, qe, field = key.split("|")
            row = (d.get(sym) or {}).get(qe)
            if not row:
                continue
            while len(row) < 9:
                row.append(None)
            i = SLOT[field]
            if row[i] is not None:
                continue
            row[i] = rec["value"]
            d[sym][qe] = row
            n += 1
            journal[key] = {
                field: rec["value"],
                "precision": "crore-rounded",
                "src": "screener.in, gate-validated (§60c)",
                "evidence": rec["note"],
                "applied": "2026-08-06 screener gate sweep",
            }
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s filled %d" % (os.path.basename(path), n))
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    led.update(journal)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()

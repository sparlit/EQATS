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
"""KIRLFER consolidated PAT: rewrite the whole 2022-2025 window onto ONE convention (owners).

WHY A SERIES REPAIR AND NOT CELL PATCHES. The stored con-PAT series mixed three different things:
owners at some quarters (Jun-22 93.56, Mar-23 88.22, Dec-22 116.61), the TOTAL at others (Jun-23
92.92, Dec-23 105.33), and an exact copy of STANDALONE at two more (Sep-22 82.00, Sep-23 56.88) --
plus Mar-24 holding 92.92, which is Jun-2023's total in the wrong quarter entirely. Correcting two
cells inside that would have made them locally right and the series no more coherent, which is why
this was escalated out of the con-copy re-adjudication rather than patched there.

Pre-2022 needs nothing: KIRLFER shows con == std from 2015 to Dec-2021 because it had nothing to
consolidate before ISMT.

THE SOURCE. Each quarter's OWN filing (§58 as-reported; a later filing's restated comparative is
NOT used -- the ACUTAAS rule, §67a). These statements print no "attributable to owners" line, so
    owners = profit for the period - minority interest        (§53; associates print NA throughout)

WHY THIS IS TRUSTWORTHY -- four independent locks, not one:
  1. Both full years reconcile EXACTLY on the period row:
        FY23 102.08 + 110.99 + 129.70 + 94.56 = 437.33  (printed)
        FY24  92.93 +  81.67 + 105.33 +  17.73 = 297.66  (printed)
  2. Both full years reconcile EXACTLY on the MINORITY row as well:
        FY23   8.52 +  14.28 +  13.09 +   6.34 =  42.23  (printed)
        FY24  18.92 +  13.42 +  29.00 +  -1.78 =  59.56  (printed)
  3. So both owners totals fall out exactly too:
        FY23 437.33 - 42.23 = 395.10 = 93.56 + 96.71 + 116.61 + 88.22
        FY24 297.66 - 59.56 = 238.10 = 74.01 + 68.25 + 76.33 + 19.51
  4. screener's consolidated series -- which quotes TOTAL PAT -- reproduces every extracted total
     independently: 93/82/105/18/70/78/54/92/86 against 92.93/81.67/105.33/17.73/69.75/77.64/
     54.31/92.34/86.28.
  Sep-2023's total came out of the H1 identity (174.60 - 92.93 = 81.67) because its own token is
  split in extraction; the Dec-2024 filing's 9M FY24 column (279.93) confirms it a second time.

From Jun-2024 the minority line is nil or absent (ISMT fully absorbed), so owners == total there
and those quarters need no adjustment beyond the two that were simply wrong.

  python -X utf8 scripts/fill2020_tools/apply_kirlfer_series_2026_08_09.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
LEDGER = os.path.join(SCRIPTS, "kirlfer_con_series.json")
HEALS = os.path.join(SCRIPTS, "con_copy_heals.json")

# qe -> (total, minority, owners, stored_before, note)
SERIES = {
    20220331: (-41.12, -47.39, 6.27, 6.27, "already owners"),
    20220630: (102.08, 8.52, 93.56, 93.56, "already owners"),
    20220930: (110.99, 14.28, 96.71, 82.00, "held an exact COPY of standalone (82.00)"),
    20221231: (129.70, 13.09, 116.61, 116.61, "already owners"),
    20230331: (94.56, 6.34, 88.22, 88.22, "already owners"),
    20230630: (92.93, 18.92, 74.01, 92.92, "held the TOTAL"),
    20230930: (81.67, 13.42, 68.25, 56.88, "held an exact COPY of standalone (56.88)"),
    20231231: (105.33, 29.00, 76.33, 105.33, "held the TOTAL"),
    20240331: (17.73, -1.78, 19.51, 92.92, "held 92.92 -- Jun-2023's TOTAL, wrong quarter"),
    20240630: (69.75, 0.00, 69.75, 69.75, "minority nil from here; already correct"),
    20240930: (77.64, 0.00, 77.64, 84.91, "held 84.91, which is Sep-2025's STANDALONE"),
    20241231: (54.31, 0.00, 54.31, 54.31, "already correct"),
    20250331: (92.34, 0.01, 92.33, 91.94, "off by 0.39 against the filing"),
    20250630: (95.12, 0.00, 95.12, 95.12, "already correct"),
    20250930: (86.28, 0.00, 86.28, 86.20, "off by 0.08 against the filing"),
}
FUND_IDX, REVOP_IDX = 3, 5


def main():
    dry = "--apply" not in sys.argv
    changes = {q: v for q, v in SERIES.items() if abs(v[2] - v[3]) > 0.005}
    print("%-10s %9s %9s %9s %9s  %s" % ("quarter", "total", "minority", "owners", "stored", "note"))
    for q in sorted(SERIES):
        tot, mi, own, was, note = SERIES[q]
        mark = "  <== FIX" if q in changes else ""
        print("%-10d %9.2f %9.2f %9.2f %9.2f  %s%s" % (q, tot, mi, own, was, note, mark))
    print("\n%d of %d quarters need correcting" % (len(changes), len(SERIES)))

    # FY identities, re-asserted here so a future edit to SERIES cannot quietly break them
    for fy, qs, per_tot, mi_tot in (
        ("FY23", (20220630, 20220930, 20221231, 20230331), 437.33, 42.23),
        ("FY24", (20230630, 20230930, 20231231, 20240331), 297.66, 59.56),
    ):
        p = sum(SERIES[q][0] for q in qs)
        m = sum(SERIES[q][1] for q in qs)
        o = sum(SERIES[q][2] for q in qs)
        ok = abs(p - per_tot) < 0.02 and abs(m - mi_tot) < 0.02 and abs(o - (per_tot - mi_tot)) < 0.02
        print(
            "  {} period {:.2f}/{:.2f}  minority {:.2f}/{:.2f}  owners {:.2f}/{:.2f}  {}".format(
                fy, p, per_tot, m, mi_tot, o, per_tot - mi_tot, "OK" if ok else "*** BROKEN"
            )
        )
        if not ok:
            sys.exit("FY identity broken -- refusing to write")

    n = 0
    for path in FUND:
        d = json.load(open(path, encoding="utf-8"))
        for q, (tot, mi, own, was, note) in changes.items():
            row = next((r for r in d.get("KIRLFER", []) if r[0] == q), None)
            if not row or len(row) <= FUND_IDX:
                continue
            cur = row[FUND_IDX]
            if cur is not None and abs(cur - own) < 0.005:
                continue
            if cur is not None and abs(cur - was) > 0.005:
                sys.exit("GUARD %d in %s: %s, expected %s" % (q, path, cur, was))
            row[FUND_IDX] = own
            n += 1
        if not dry:
            json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    for path in REVOP:
        d = json.load(open(path, encoding="utf-8"))
        for q, (tot, mi, own, was, note) in changes.items():
            row = (d.get("KIRLFER") or {}).get(str(q))
            if not row or len(row) <= REVOP_IDX:
                continue
            cur = row[REVOP_IDX]
            if cur is not None and abs(cur - own) < 0.005:
                continue
            if cur is not None and abs(cur - was) > 0.005:
                sys.exit("GUARD %d revop: %s, expected %s" % (q, cur, was))
            row[REVOP_IDX] = own
            n += 1
        if not dry:
            json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))

    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    json.dump(
        {
            "_README": [
                "KIRLFER consolidated PAT, rebuilt onto ONE convention (owners-attributable) 2026-08-09.",
                "owners = profit for the period - minority interest, read from each quarter's OWN filing.",
                "Both FY23 and FY24 reconcile exactly on the period row, the minority row and the owners",
                "total; screener's consolidated series (which quotes TOTAL PAT) independently reproduces",
                "every extracted total. Pre-2022 is untouched -- con == std there is real, KIRLFER had",
                "nothing to consolidate before ISMT. Runbook §68.",
            ],
            "generated": "2026-08-09",
            "series": {
                str(q): {
                    "total": v[0],
                    "minority": v[1],
                    "owners": v[2],
                    "stored_before": v[3],
                    "note": v[4],
                    "changed": q in changes,
                }
                for q, v in SERIES.items()
            },
        },
        open(LEDGER, "w", encoding="utf-8"),
        indent=1,
    )
    print(f"ledger -> {LEDGER}")
    jr = json.load(open(HEALS, encoding="utf-8"))
    for k, q in (("KIRLFER|20230630|patC", 20230630), ("KIRLFER|20240630|patC", 20240630)):
        if k in jr:
            jr[k] = {
                "readjudicated": "2026-08-09",
                "value": SERIES[q][2],
                "reason": "superseded by the whole-series rebuild onto the owners convention; "
                "see kirlfer_con_series.json",
                "route": "BSE announcement stream, own filing per quarter (§58/§68)",
            }
    json.dump(jr, open(HEALS, "w", encoding="utf-8"), indent=1)
    print("con_copy_heals updated")


if __name__ == "__main__":
    main()

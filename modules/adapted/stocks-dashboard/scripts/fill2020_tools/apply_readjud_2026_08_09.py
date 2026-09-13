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
"""Corrections from re-adjudicating the con-copy heals against the BSE announcement stream.

All 17 active heals were re-read from the primary record (§58 rung 3). 12 confirmed, 2 corrected
here, 2 escalated (KIRLFER), 1 pair left alone as immaterial. Full verdicts in
`_con_copy_readjudication.json`.

ACUTAAS 2023-06-30 revC : 153.72 -> 142.35   NOT A COPY -- A RESTATEMENT
    The company's OWN Jun-2023 filing prints consolidated revenue 142.35 (Total income 143.45),
    and its consolidated XBRL says RevenueFromOperations 142.35 / TotalIncome 143.45 -- both
    matching what we already stored. 153.72 appears only as a RESTATED comparative in the
    Sep-2023 filing (which also restates the H1 pair: 172.36 + 153.72 = 326.08). ACUTAAS had not
    yet consolidated Tanfac in Jun-2023, so con == std was legitimate there and the tripwire's
    premise did not hold. Adopting 153.72 would also leave Mar-2023 at its as-reported 186.38 --
    a mixed as-reported/restated series (§40b). Reverting to the as-reported figure.

ATUL 2023-06-30 patC : 102.05 -> 103.35      TOTAL WRITTEN WHERE WE STORE OWNERS
    The filing's own split, at the Jun-2023 column of the consolidated page:
        owners 103.35 + NCI (-1.30) = 102.05 = the post-tax line, exactly.
    102.05 is the TOTAL. We store owners-attributable consolidated PAT, so 103.35 is the value.
    Confirmed identically on a second document (the Sep-2023 filing's comparative column).
    NOTE: ATUL's stored series is itself mixed -- 2023-03-31 holds 92.21, which is that quarter's
    TOTAL (owners 93.56). That is a pre-existing defect in a cell outside this batch; it is
    reported, not silently changed here.

  python -X utf8 scripts/fill2020_tools/apply_readjud_2026_08_09.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
JOURNAL = os.path.join(SCRIPTS, "con_copy_heals.json")
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
IDX = {"patC": (3, 5), "revC": (None, 1)}  # (fundamentals npCon idx, revop idx)

FIX = {
    "ACUTAAS|20230630|revC": {
        "from": 153.72,
        "to": 142.35,
        "reason": "restatement, not a copy: the own Jun-2023 filing and its XBRL both print "
        "142.35 (Total income 143.45); 153.72 is only the Sep-2023 filing's restated "
        "comparative. con==std was legitimate before Tanfac was consolidated.",
    },
    "ATUL|20230630|patC": {
        "from": 102.05,
        "to": 103.35,
        "reason": "the heal wrote the TOTAL. Filing: owners 103.35 + NCI -1.30 = 102.05 exactly, "
        "at the Jun-2023 column, on two documents. We store owners-attributable.",
    },
}


def main():
    dry = "--apply" not in sys.argv
    n = 0
    for key, f in FIX.items():
        sym, qe, field = key.split("|")
        fi, ri = IDX[field]
        if fi is not None:
            for p in FUND:
                d = json.load(open(p, encoding="utf-8"))
                row = next((r for r in d.get(sym, []) if r[0] == int(qe)), None)
                if not row or len(row) <= fi:
                    continue
                if abs((row[fi] if row[fi] is not None else 1e9) - f["to"]) < 0.005:
                    continue
                if row[fi] is not None and abs(row[fi] - f["from"]) > 0.005:
                    sys.exit("GUARD {} in {}: {}, expected {}".format(key, p, row[fi], f["from"]))
                print("  %-24s %-26s %s -> %s" % (key, os.path.basename(p), row[fi], f["to"]))
                row[fi] = f["to"]
                n += 1
                if not dry:
                    json.dump(d, open(p, "w", encoding="utf-8"), separators=(",", ":"))
        for p in REVOP:
            d = json.load(open(p, encoding="utf-8"))
            row = (d.get(sym) or {}).get(qe)
            if not row or len(row) <= ri:
                continue
            if abs((row[ri] if row[ri] is not None else 1e9) - f["to"]) < 0.005:
                continue
            # an EMPTY slot is a fill, not a correction -- the earlier heal reached
            # sf_fundamentals but not sf_revop for some cells, so the two disagreed
            if row[ri] is not None and abs(row[ri] - f["from"]) > 0.005:
                sys.exit("GUARD {} in {}: {}, expected {}".format(key, p, row[ri], f["from"]))
            print("  %-24s %-26s %s -> %s" % (key, os.path.basename(p), row[ri], f["to"]))
            row[ri] = f["to"]
            n += 1
            if not dry:
                json.dump(d, open(p, "w", encoding="utf-8"), separators=(",", ":"))

    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    jr = json.load(open(JOURNAL, encoding="utf-8"))
    for key, f in FIX.items():
        old = jr.get(key, {})
        jr[key] = {
            "readjudicated": "2026-08-09",
            "value": f["to"],
            "was_healed_to": f["from"],
            "original": old.get("was"),
            "reason": f["reason"],
            "route": "BSE announcement stream (§58 rung 3)",
        }
    json.dump(jr, open(JOURNAL, "w", encoding="utf-8"), indent=1)
    print(f"journalled -> {JOURNAL}")


if __name__ == "__main__":
    main()

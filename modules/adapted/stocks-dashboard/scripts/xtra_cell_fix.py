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
"""Proven values for single deep-detail cells (scripts/xbrl_extra.json → docs/fin/<SYM>.json key x) — runbook §214a F3.

THE DEFECT. The detail ledger copies each filer's XBRL tags as filed, and some filers typed the wrong number into a
tag: a loss's EPS without its minus sign (SWIGGY Jun-2025 con +5.04, the PDF prints (5.04)), the continuing EPS typed
into the discontinued tag as well so the total doubles (MARUTI Mar-2024 con 251.42, printed 125.71), the printed CASH
EPS in the basic tag (SHREECEM Jun-2024 std 259.84, printed basic 88.06), the before-exceptional line where the
after-exceptional one belongs (GLAXO Dec-2023 con 9.89 vs 2.70), or a later filing whose contexts are dated to an
earlier quarter (SIEMENS Jun-2025 con 7.80 = the Dec-2025 quarter; printed 11.89). No reader rule can tell these
from a real figure, so THIS ledger holds the figure each cell was proven to have.

THE PROOF, per entry (`why` names the readers and their values): reader 1 = the quarter's own result PDF, reader 2 =
an independent re-print (the next filing's comparative column, Moneycontrol, screener) — two readers that agree.
The EPS entries also reconcile with the stored PAT ÷ the quarter-end share count (fund_eps_shares, within 5 %).

ENTRY  {sym, qe, basis "s"/"c", field, was, fixed, why, found}.

RE-ASSERT. Every writer that can rewrite a filer-XBRL cell re-applies this ledger next to xtra_fc_fix (§211) —
build_xbrl_extra.main (nightly --incremental top-up and full rebuild) and xtra_nse_html.apply_reads — and
build_stock_fin applies it once more at serve time, so a replay of an older ledger copy cannot bring the filer's
slip back onto the page. Directional: an entry lands only while the cell holds `was` or has no value for the field;
a cell holding anything else (a revised filing re-read, another heal) is left alone and reported. A landed field is
listed under the cell's `src_fix` (per-field provenance, like `src_mc`).

Run:  python3 scripts/xtra_cell_fix.py            dry run: what a re-assert would change on the local/committed ledger
      python3 scripts/xtra_cell_fix.py --apply    write scripts/xbrl_extra.json + .gz
"""
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "xtra_cell_fix.json")
LEDGER = os.path.join(HERE, "xbrl_extra.json")
MARK = "src_fix"


def entries():
    try:
        return json.load(open(FIX, encoding="utf-8")).get("fixes") or []
    except FileNotFoundError:
        return []


def reassert(data, report=None):
    """Apply every entry to the ledger dict {sym: {qe: {s|c: cell}}} in place; -> number of cells changed."""
    n = 0
    for e in entries():
        cell = ((data.get(e["sym"]) or {}).get(str(e["qe"])) or {}).get(e["basis"])
        if not isinstance(cell, dict):
            if report is not None:
                report.append(("skip-no-cell", e["sym"], e["qe"], e["basis"], e["field"]))
            continue
        f, cur = e["field"], cell.get(e["field"])
        marked = f in (cell.get(MARK) or [])
        if cur == e["fixed"]:
            if not marked:
                cell[MARK] = sorted(set(cell.get(MARK) or []) | {f})
                n += 1
            continue
        if cur is not None and cur != e["was"]:
            if report is not None:
                report.append(("skip-cell-moved", e["sym"], e["qe"], e["basis"], f, cur))
            continue
        cell[f] = e["fixed"]
        cell[MARK] = sorted(set(cell.get(MARK) or []) | {f})
        n += 1
        if report is not None:
            report.append(("set", e["sym"], e["qe"], e["basis"], f, cur, e["fixed"]))
    return n


def main():
    apply = "--apply" in sys.argv
    if os.path.exists(LEDGER):
        data = json.load(open(LEDGER))
    else:
        data = json.loads(gzip.decompress(open(LEDGER + ".gz", "rb").read()))
    rep = []
    n = reassert(data, rep)
    kinds = {}
    for r in rep:
        kinds[r[0]] = kinds.get(r[0], 0) + 1
    print("%d entries; %d cells would change; %s" % (len(entries()), n, kinds))
    for r in [r for r in rep if r[0] != "set"][:20]:
        print("  ", r)
    if apply and n:
        json.dump(data, open(LEDGER, "w"), separators=(",", ":"))
        open(LEDGER + ".gz", "wb").write(gzip.compress(open(LEDGER, "rb").read(), 9))
        print(f"wrote {os.path.basename(LEDGER)} (+gz)")


if __name__ == "__main__":
    main()

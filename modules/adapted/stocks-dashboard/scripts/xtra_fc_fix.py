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
"""Finance costs for the NSE-archive cells whose page printed the TAX in its "(f) Finance costs" row (runbook §211).

THE DEFECT. NSE's archived results pages in the Ind-AS 2016-17 template (financial_res_<SYM>_<id>.html; the
Mar-2016 → Dec-2017 quarters) print the "Tax expense" figure a second time in the "(f) Finance costs" row. ARE&M
Mar-2017 (financial_res_ARE&M_1023437): "(f) Finance costs 4885" and "Tax expense 4885" lakh, PBT 14,804 − 4,885 =
PAT 9,919, while the company's own results print finance costs 150 lakh. xtra_nse_html.py read that cell as printed,
so the detail ledger (scripts/xbrl_extra.json.gz → docs/fin/<SYM>.json key x) carried fc == tax on those cells and
the stock page's "Finance costs" / P&L "Interest" rows showed the tax. The reader now refuses the cell (fc stays
blank); THIS ledger holds the figure each cell was proven to have.

THE PROOF, per entry (`why` names the readers and their values):
  page residual  the same page's "Total expenses" minus every other itemised expense row — the page's own arithmetic,
                 never the "(f)" cell. It equals the filing's finance costs only when the filer spread its expenses over
                 NSE's form exactly (NCC Dec-2017 std: residual 92.72 cr, while the Mar-2018 XBRL year minus the two
                 proven quarters and Moneycontrol both give 104.32), so it is never enough alone.
  Moneycontrol   the quarterly table's "Interest" row, gated like xtra_mc (the table's PAT reproduces our stored PAT).
  FY18 closure   Jun + Sep + Dec-2017 + the Mar-2018 XBRL's own quarter == the Mar-2018 XBRL's year (FourD).
  BSE PDF        the company's printed results (the quarter's own filing, or the next filings' comparative column),
                 the column anchored by our stored PAT.
  An entry needs two independent readers that agree.

RE-ASSERT. Every writer of these cells re-applies this ledger — xtra_nse_html.apply_reads (a re-read of the pages) and
build_xbrl_extra.main (the nightly top-up and a full rebuild) — so a replay of an older ledger copy cannot bring the
tax back (memory: a heal must be re-asserted at serve time). Directional: an entry lands only while the cell is still
the archive read it was measured on (`src` nse-html) and holds `was` or no fc; an XBRL cell for the quarter outranks
it and is left alone. A healed cell carries `src_fc: "xtra_fc_fix"` (per-field provenance, like `src_mc`). An entry
with `fixed: null` BLANKS the cell — the stored number was the tax and no reader proved a figure yet — so the page
shows no finance costs for that quarter rather than the tax.

CORRECTIONS. An entry may list `supersedes`: figures THIS ledger landed earlier that a later read disproved (LTM
Jun-2017 std: 3.50 came from the Jun-2018 filing's reclassified comparative; the quarter's own statement prints no
finance costs -> 0.00). A cell still carrying our marker (`src_fc` "xtra_fc_fix") and holding a superseded figure is
treated like `was`; a cell holding anything else is still another writer's and is left alone.

Run:  python3 scripts/xtra_fc_fix.py            dry run: what a re-assert would change on the committed ledger
      python3 scripts/xtra_fc_fix.py --apply    write scripts/xbrl_extra.json + .gz
"""
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "xtra_fc_fix.json")
LEDGER = os.path.join(HERE, "xbrl_extra.json")
MARK = "xtra_fc_fix"


def entries():
    try:
        return json.load(open(FIX, encoding="utf-8")).get("fixes") or []
    except FileNotFoundError:
        return []


def superseded(e, cell, cur):
    """True when the cell holds a figure this ledger landed earlier and the entry now corrects (`supersedes`)."""
    return cur is not None and cell.get("src_fc") == MARK and cur in (e.get("supersedes") or [])


def reassert(data, report=None):
    """Apply every entry to the ledger dict in place; -> number of cells changed (fc and/or its marker)."""
    n = 0
    for e in entries():
        cell = ((data.get(e["sym"]) or {}).get(e["qe"]) or {}).get(e["basis"])
        if not isinstance(cell, dict) or not str(cell.get("src", "")).startswith("nse-html:"):
            if report is not None:
                report.append(("skip-not-archive-cell", e["sym"], e["qe"], e["basis"]))
            continue
        cur = cell.get("fc")
        if e["fixed"] is None:
            # no reader proved a figure: the stored number was the tax, so the cell carries no finance costs
            if cur is not None and (cur == e["was"] or superseded(e, cell, cur)):
                del cell["fc"]
                cell["src_fc"] = MARK
                n += 1
                if report is not None:
                    report.append(("blank", e["sym"], e["qe"], e["basis"], cur))
            elif cur is None and cell.get("src_fc") != MARK:
                cell["src_fc"] = MARK
                n += 1
            elif cur is not None and report is not None:
                report.append(("skip-cell-moved", e["sym"], e["qe"], e["basis"], cur))
            continue
        if cur == e["fixed"]:
            if cell.get("src_fc") != MARK:
                cell["src_fc"] = MARK
                n += 1
            continue
        if cur is not None and cur != e["was"] and not superseded(e, cell, cur):
            if report is not None:
                report.append(("skip-cell-moved", e["sym"], e["qe"], e["basis"], cur))
            continue
        cell["fc"] = e["fixed"]
        cell["src_fc"] = MARK
        n += 1
        if report is not None:
            report.append(("set", e["sym"], e["qe"], e["basis"], cur, e["fixed"]))
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

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
"""Third pass over the NSE archived-results pages: the revenue row is PRESENT and printed as a
DASH, which is a filed NIL — not a missing row.

THE DEFECT THIS FIXES. `_nse_archive_revop.parse_detail` turns every cell into a float and drops
what it cannot parse, so a revenue line printed "-" disappears entirely and the caller records
`no-rev-row`. The row is right there in the page:

    Net Income from sales / services :: -
    ...
    Net Profit (+) / Loss (-) for the period :: 62.00          (Amount: Rs. in lakhs)

NEXTMEDIA 2009-06-30 is the worked case — Mid-Day Multimedia slump-sold its printing/publishing
business to a subsidiary effective 2008-07-01, so the STANDALONE entity genuinely had no operating
revenue afterwards while the consolidated statement still shows plenty. Its own BSE attachment
carries only the consolidated statement and says outright "Standalone results can be viewed on the
sites of BSE, NSE", so this page is the only standalone source and it answers the question.

WHY A DASH IS SAFE TO READ AS 0.00 HERE (and a MISSING row is not): the label is present in the
page's own label/value list. NSE emits every line of the filed format, so a dash is the filer
declaring nil, exactly like the 0.00 printed one row below it in Gross Profit.

GATES, all required:
  1. The revenue label must be PRESENT in the raw page with an empty/dash value. A label that is
     absent from the page is left alone (that is a different, unproven thing).
  2. PAT anchor — the page's own PAT must equal the stored sf_fundamentals std PAT.
  3. EVERY other operating line must also be nil or absent. If any operating expense/income line
     carries a real number while revenue is a dash, the dash is NOT self-evidently nil and the
     cell is skipped for a human read. (Gross Profit == 0.00 counts as corroboration, not as an
     operating number.)

Output: scripts/_nsearch_reads_nilrev.json, the shape _apply_reads.py already globs.

Run: python -X utf8 scripts/_nsearch_nil_rev.py [--gaps <file>] [--only SYM,SYM]
"""
import contextlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

_spec = importlib.util.spec_from_file_location("nar", os.path.join(HERE, "_nse_archive_revop.py"))
M = importlib.util.module_from_spec(_spec)
with contextlib.suppress(SystemExit):
    _spec.loader.exec_module(M)

OUT = os.path.join(HERE, "_nsearch_reads_nilrev.json")
SKIPS = os.path.join(HERE, "_nsearch_nilrev_skips.json")

REV_LABELS = (
    "net income from sales / services",
    "net income from sales/services",
    "net sales/income from operation",
    "net sales / income from operation",
    "total income from operations",
    "revenue from operations",
)
# lines that would make a dash-revenue implausible if they carried a real number
OPERATING = (
    "increase/decrease in stock in trade and work in progress",
    "consumption of raw materials",
    "purchase of traded goods",
    "other operating income",
    "cost of sales",
)
PAT_LABELS = (
    "net profit (+) / loss (-) for the period",
    "net profit(+)/loss(-) for the period",
    "net profit / (loss) for the period",
    "net profit(+)/loss(-) from ordinary activities after tax",
)


def raw_pairs(html):
    """[(label, raw_value_string)] straight off the page, dashes preserved."""
    txt = re.sub(r"<[^>]+>", "|", html)
    cells = [c.strip() for c in re.split(r"\|+", txt) if c.strip()]
    out = []
    for i in range(len(cells) - 1):
        out.append((cells[i].lower(), cells[i + 1]))
    return out, cells


def val(s):
    s = (s or "").replace(",", "").strip()
    if s in ("-", "", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main():
    argv = sys.argv
    gapf = argv[argv.index("--gaps") + 1] if "--gaps" in argv else os.path.join(HERE, "_gaps_n500_stdfill.json")
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    gaps = json.load(open(gapf))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    skips = {}
    M.JAR = M.BF.nse_jar()
    todo = []
    for sym, qs in gaps.items():
        if only and sym not in only:
            continue
        for q in qs:
            cell = (revop.get(sym) or {}).get(str(q))
            if cell and cell[0] is not None:
                continue  # already filled by another route
            todo.append((sym, int(q)))
    print("candidates: %d" % len(todo), flush=True)
    nfill = 0
    for sym, qe in sorted(todo):
        key = "%s|%d" % (sym, qe)
        frow = fmap.get(sym, {}).get(qe)
        if not frow or frow[1] is None:
            skips[key] = "no-stored-std-pat"
            continue
        stored = frow[1]
        try:
            rows = M.list_rows(sym)
        except Exception:
            skips[key] = "list-failed"
            continue
        hit = False
        for r in rows:
            if M.iso_qe(r.get("toDate")) != qe or "Non" not in (r.get("consolidated") or "Non"):
                continue
            if not r.get("resultDetailedDataLink"):
                continue
            link = r["resultDetailedDataLink"]
            dp = os.path.join(M.CACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link.rsplit("/", 1)[-1]))
            try:
                html = M.get_detail(link, sym, dp)
            except Exception:
                continue
            hit = True
            pairs, _cells = raw_pairs(html)
            lut = {}
            for lab, v in pairs:
                lut.setdefault(lab, v)
            unit = 100.0 if "lakhs" in html.lower() else 1.0
            revlab = next((l for l in REV_LABELS if l in lut), None)
            if revlab is None:
                skips[key] = "revenue label ABSENT from page (not a dash) - left alone"
                break
            if val(lut[revlab]) is not None:
                skips[key] = f"revenue row carries a number ({lut[revlab]}) - not this class"
                break
            pat = next((val(lut[l]) for l in PAT_LABELS if l in lut and val(lut[l]) is not None), None)
            if pat is None:
                skips[key] = "no readable PAT row"
                break
            if abs(pat / unit - stored) > max(0.02, abs(stored) * 0.02):
                skips[key] = f"pat-anchor {pat:.2f}/{unit:.0f} vs stored {stored}"
                break
            live = [l for l in OPERATING if l in lut and val(lut[l]) not in (None, 0.0)]
            if live:
                skips[key] = f"dash revenue but operating lines carry numbers {live} - needs a human read"
                break
            out.setdefault(sym, {})[str(qe)] = {
                "rev": 0.0,
                "op": None,
                "pat_seen": round(pat / unit, 4),
                "basis": "std",
                "fin": 0,
                "src": (
                    "nse-archive {}: revenue row '{}' PRINTED AS {!r} = filed nil; every other operating "
                    "line nil/absent; PAT {} scale = {:.4f} anchors stored {}".format(
                        link.rsplit("/", 1)[-1], revlab, lut[revlab], unit, pat / unit, stored
                    )
                ),
            }
            nfill += 1
            print("%-12s %d std -> rev 0.00 (nil dash; PAT %.4f vs %s)" % (sym, qe, pat / unit, stored), flush=True)
            break
        if not hit and key not in skips:
            skips[key] = "no std archive row for this quarter"
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=1, sort_keys=True)
    print("DONE: %d cells, %d skipped" % (nfill, len(skips)), flush=True)


if __name__ == "__main__":
    main()

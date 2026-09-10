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
"""FILL-2020: standalone REVENUE for 2015-2019 gap cells via the BSE detailed-results JSON (§42).

Companion to fill_std_pat_detres.py, which closed the standalone-PAT window the same way. Same
source, same quarter-keyed id space, same as-filed values in Rs MILLION (/10 -> crore).

THE GATE IS FREE HERE, AND IT IS THE STRONG ONE. Revenue is the gap, so it has no stored anchor of
its own -- but the SAME detres row prints Net Profit, and we already hold standalone PAT for these
quarters (that is why they are revenue-only gaps). So:

    the page's Net Profit (/10) must match our STORED std PAT within max(2cr, 3%)
    -> the row is proven to be this company, this quarter, this basis, at this scale
    -> only then is its revenue read

That is runbook §42's landing rule verbatim, and it is stronger than any revenue-side heuristic:
a mis-scaled or mis-periodised row cannot match a stored PAT by accident. 188 of the 191 gap cells
have such an anchor; the 3 that do not are reported, never guessed.

BANK/NBFC FORMAT. 25 target companies are financials, whose top line is "Interest Earned", not
"Revenue from Operations" -- §42 notes detres serves those rows first-class, so they are read from
the bank field when the industrial one is absent. The PAT anchor gates them identically, so a
wrong-field read cannot land.

Writes REVENUE ONLY (slot 0) plus the PAT mirror (slot 4) into docs/sf_revop.json AND
scripts/revop_fundamentals.json. Operating profit is deliberately left alone: it is a
reconstruction from expense components, and a wrong OPM is a visible site bug -- out of scope for
a fill pass.

⚠️ CONCURRENCY: another session is filling POST-2020 revenue in these same two files, and CI
rewrites them constantly. Fill-only + push small, and always re-verify against origin (§6 of
FILL2020_CAMPAIGN.md).

Run:  python -X utf8 scripts/fill2020_tools/fill_std_rev_detres.py [--apply] [--only SYM,SYM]
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SCRIPS = os.path.join(SCRIPTS, "bse_scrips.json")
TARGETS = os.path.join(HERE, "_revstd_targets.json")
LEDGER = os.path.join(SCRIPTS, "std_rev_detres_fills.json")

API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd=%s&qtr=%s"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PAT_ABS, PAT_REL = 2.0, 0.03  # §42 landing rule
MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
SCRIP_OVERRIDE = {"ADVANTA": "532840", "DISHMAN": "532526", "CAPF": "532938"}

REV_FIELDS = (
    "Net Sales/Revenue From Operations",
    "Net Sales / Income from Operations",
    "Net Sales/ Income from Operations",
    "Revenue From Operations",
    "Net Sales/Income from Operations",
    "Total Income From Operations",
)
BANK_FIELDS = ("Interest Earned", "Interest earned", "Total Income from Operations")
NP_FIELDS = (
    "Net Profit",
    "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax",
    "Net Profit (+)/ Loss (-) from Ordinary Activities after Ta",
)


def qid(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return "%d.00" % (85 + (y - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m])


def get(scrip, q):
    req = urllib.request.Request(API % (scrip, q), headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_dt(s):
    try:
        d, mo, y = s.split("-")
        return (2000 + int(y)) * 10000 + MONTHS[mo] * 100 + int(d)
    except Exception:
        return None


def fields(js):
    out = {}
    for r in js.get("table1") or []:
        out.setdefault(r.get("fld_desc", "").strip(), r.get("Value"))
    return out


def fnum(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def check(scrip, qe, stored_pat):
    """-> (rev_cr, note) or (None, reason)."""
    f = fields(get(scrip, qid(qe)))
    if not f:
        return None, "empty-response"
    b, e = parse_dt(f.get("Date Begin", "")), parse_dt(f.get("Date End", ""))
    if not b or not e:
        return None, "no-date-span"
    if e != qe:
        return None, f"date-end={e}"
    span = (e // 10000 * 12 + (e // 100) % 100) - (b // 10000 * 12 + (b // 100) % 100)
    if span != 2:
        return None, "span=%dm" % (span + 1)
    np = fnum(f, *NP_FIELDS)
    if np is None:
        return None, "no-net-profit-row"
    # THE ANCHOR: this row must be the quarter we already hold a PAT for.
    d = abs(np / 10.0 - stored_pat)
    if d > max(PAT_ABS, abs(stored_pat) * PAT_REL):
        return None, f"pat-anchor off {d:.2f} (page {np / 10.0:.2f} vs stored {stored_pat:.2f})"
    rev = fnum(f, *REV_FIELDS)
    src = "rev-from-ops"
    if rev is None:
        rev = fnum(f, *BANK_FIELDS)
        src = "interest-earned(bank)"
    if rev is None:
        return None, "no-revenue-row"
    if rev < 0:
        return None, "negative-revenue"
    return round(rev / 10.0, 2), f"pat-anchor {d:.2f} cr; {src}"


def main():
    args = sys.argv[1:]
    apply_it = "--apply" in args
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    fund = json.load(open(FUND))
    by_id = json.load(open(SCRIPS, encoding="utf-8"))["by_id"]
    targets = json.load(open(TARGETS))
    ok, bad, journal = [], [], {}
    for sym, qes in sorted(targets.items()):
        if only and sym not in only:
            continue
        scrip = SCRIP_OVERRIDE.get(sym) or by_id.get(sym)
        if not scrip:
            bad.append((sym, "-", "no-bse-scrip"))
            continue
        frows = {r[0]: r for r in fund.get(sym, [])}
        for qe in qes:
            fr = frows.get(qe)
            stored = fr[1] if fr else None
            if stored is None:
                bad.append((sym, qe, "no-stored-pat-anchor"))
                continue
            try:
                rev, note = check(str(scrip), qe, stored)
            except Exception as ex:
                rev, note = None, f"fetch-error:{type(ex).__name__}"
            time.sleep(0.45)
            if rev is None:
                bad.append((sym, qe, note))
                print("  SKIP %-12s %d  %s" % (sym, qe, note), flush=True)
            else:
                ok.append((sym, qe, rev, stored))
                journal["%s|%d" % (sym, qe)] = {
                    "revS": rev,
                    "src": "bse-detres-§42",
                    "qid": qid(qe),
                    "gate": note,
                    "anchor_pat": stored,
                    "applied": "2026-08-06 FILL-2020 revS-2015-2019",
                }
                print("  OK   %-12s %d  rev=%-12.2f (%s)" % (sym, qe, rev, note), flush=True)
    print("\nPASS %d | SKIP %d" % (len(ok), len(bad)))
    if not apply_it:
        print("DRY RUN -- nothing written.")
        return
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for sym, qe, rev, stored in ok:
            row = d.setdefault(sym, {}).get(str(qe)) or [None] * 6 + [0, None, None]
            while len(row) < 9:
                row.append(None)
            if row[0] is None:  # fill-only
                row[0] = rev
                n += 1
            if row[4] is None:
                row[4] = stored  # PAT mirror, same convention as backfill_revop_gaps
            d[sym][str(qe)] = row
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("wrote %-30s %d cells" % (os.path.basename(path), n))
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    led.update(journal)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()

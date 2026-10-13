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
"""Re-read the NSE archive pages listed in xtra_unit_fix.json under their PROVEN unit (runbook §215).

THE DEFECT. The archive prints "Amount(Rs. in lakhs)" on every results page (4,701 of 4,701 cached) — template text —
and a few filers typed millions or crores under it. xtra_nse_html.py scaled every money row as lakhs, and the PAT anchor
(_nse_archive_revop.close: max 2 cr, 3%) let the 10x/100x reading through wherever the stored PAT is under ~2.2 cr:
RAIN Dec-2017 std, PAT -3.98 millions read as -0.04 cr against the stored -0.40, landed pbt -0.04 / emp 0.34 /
dep 0.01 (Moneycontrol: -0.40 / 3.43 / 0.10).
The reader's anchor now carries a relative cap (xtra_nse_html.anchor_ok), so no power of ten passes it again, and
names the unit that would have passed in its refusal note.

THE HEAL. Nothing is patched by hand: each listed page is read again through xtra_nse_html.read_page with its proven
unit, the PAT anchor must pass against the stored PAT, and the read lands through xtra_nse_html.apply_reads (which
re-asserts xtra_fc_fix.json, §211). An entry whose anchor refuses (the stored PAT carries the same error - TTKPRESTIG
Sep-2017) changes nothing until the stored PAT is healed.

Pages: XTRA_PAGES=<dir> (default scripts/_nsearch_cache); a missing page is fetched one request at a time.
Run:  python3 scripts/xtra_unit_fix.py            dry run: the cells a re-read would change, field by field
      python3 scripts/xtra_unit_fix.py --apply    write scripts/xbrl_extra.json + .gz
"""
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _nse_archive_revop as NAR
import xtra_nse_html as X

BASE = "https://nsearchives.nseindia.com/archives/financial_results/"


def stored_pat(fund, sym, qe, basis):
    r = next((r for r in fund.get(sym, []) if str(r[0]) == str(qe)), None)
    if not r:
        return None
    return r[1] if basis == "s" else (r[3] if len(r) > 3 else None)


def page_of(entry, pages_dir):
    p = os.path.join(pages_dir, re.sub(r"[^A-Za-z0-9_.]", "_", entry["file"]))
    if os.path.exists(p) and os.path.getsize(p):
        return open(p, encoding="utf8", errors="replace").read()
    if NAR.__dict__.get("JAR") is None:
        import build_fundamentals as BF

        NAR.JAR = BF.nse_jar()
    return NAR.get_detail(BASE + entry["file"], entry["sym"], p)


def main():
    apply = "--apply" in sys.argv
    pages_dir = os.environ.get("XTRA_PAGES") or NAR.CACHE
    fixes = list(X.unit_fix().values())
    fund = json.load(open(X.FUND))
    ledger = X.load_ledger()
    before = json.loads(json.dumps(ledger))
    reads, refused = {}, []
    for e in fixes:
        sp = stored_pat(fund, e["sym"], e["qe"], e["basis"])
        page = page_of(e, pages_dir)
        basis, fields, note = X.read_page(
            page,
            e["sym"],
            int(e["qe"]),
            {e["basis"]: sp} if sp is not None else {},
            fname=e["file"],
        )
        if fields is None or basis != e["basis"]:
            refused.append(
                (e["sym"], e["qe"], e["basis"], note if fields is None else f"basis {basis}")
            )
            continue
        reads.setdefault(e["sym"], {}).setdefault(e["qe"], {})[basis] = {
            "fields": fields,
            "src": "nse-html:{}".format(e["file"]),
            "chk": note,
        }
    X.apply_reads(reads, ledger)
    changed = []
    for sym in sorted(set(before) | set(ledger)):
        for qe in sorted(set(before.get(sym, {})) | set(ledger.get(sym, {}))):
            for b in ("s", "c"):
                o = (before.get(sym, {}).get(qe) or {}).get(b) or {}
                n = (ledger.get(sym, {}).get(qe) or {}).get(b) or {}
                d = {
                    f: (o.get(f), n.get(f)) for f in sorted(set(o) | set(n)) if o.get(f) != n.get(f)
                }
                if d:
                    changed.append((sym, qe, b, d))
    print(
        "%d entries: %d re-read, %d refused by the anchor"
        % (len(fixes), len(fixes) - len(refused), len(refused))
    )
    for r in refused:
        print("   refused {} {} {}: {}".format(*r))
    print("%d cells change:" % len(changed))
    for sym, qe, b, d in changed:
        print(
            "   {} {} {}  {}".format(
                sym, qe, b, "  ".join(f"{f} {v[0]} -> {v[1]}" for f, v in d.items())
            )
        )
    if apply and changed:
        json.dump(ledger, open(X.LEDGER, "w"), separators=(",", ":"))
        open(X.LEDGER_GZ, "wb").write(gzip.compress(open(X.LEDGER, "rb").read(), 9))
        print(f"wrote {os.path.basename(X.LEDGER)} (+gz)")


if __name__ == "__main__":
    main()

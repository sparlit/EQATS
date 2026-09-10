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
"""§117 F-02 CAMPAIGN — the §109 provenance test over the rows OUTSIDE the healed window.

§109 proved the restated-vintage class (§108) was ONE backfill pass with no vintage rule and
healed the 20150630..20170331 window. §117 (StockView R5, BAYERCROP FY19) measured ~2,188
NSE-archive-sourced fill rows sitting OUTSIDE that window — 2017 Jun-Dec, Mar-2015-and-earlier —
same pass family, same exposure. This is vintage108_provenance.py with the window COMPLEMENTED:
for every vision_rev_fills row citing an NSE archive page whose qe is NOT in the §109 window,
order NSE's filings of that (period, basis) by filingDate and ask which one the pass read.

VERDICTS  src-is-earliest (clean) · src-is-later-vintage (DEFECT) · single-row (nothing to choose)
          src-not-in-list / no-list (measured absence of the route, never a claim about the cell)

OUT: scripts/_vintage117_prov.json
RUN: python3 scripts/vintage117_provenance.py [--limit N] [--only SYM,SYM]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _nse_archive_revop as NA  # noqa: E402
import build_fundamentals as BF  # noqa: E402

VRF = os.path.join(HERE, "vision_rev_fills.json")
OUT = os.path.join(HERE, "_vintage117_prov.json")
QS_109 = (20150630, 20150930, 20151231, 20160331, 20160630, 20160930, 20161231, 20170331)
SEQ = re.compile(r"financial_res_[A-Za-z0-9&._-]+_(\d+)\.html", re.IGNORECASE)
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}


def dt(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", str(s or ""))
    return int(m.group(3)) * 10000 + MON[m.group(2)] * 100 + int(m.group(1)) if m else None


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    try:
        NA.JAR = BF.nse_jar()
    except Exception as ex:
        # cached lists still serve; only a symbol with NO cached list needs the live API
        print(f"  ! nse_jar failed ({type(ex).__name__}) — running cache-only")

    vrf = json.load(open(VRF, encoding="utf-8"))
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    for k in [k for k, v in out.items() if v.get("verdict") == "no-list"]:
        del out[k]  # transport failure is not a result

    todo = []
    for key, v in sorted(vrf.items()):
        try:
            sym, qe = key.split("|")
            qe = int(qe)
        except Exception:
            continue
        if qe in QS_109 or (only and sym not in only):
            continue  # §109 already audited its window
        for basis in ("std", "con"):
            src = (v.get(basis) or {}).get("src") or ""
            m = SEQ.search(src)
            if m and f"{key}|{basis}" not in out:
                todo.append((key, sym, qe, basis, m.group(1), v[basis]))
    todo = todo[:limit]
    print("provenance rows to check: %d (ledger holds %d)" % (len(todo), len(out)))

    lists, n = {}, 0
    for key, sym, qe, basis, seq, cell in todo:
        k2 = f"{key}|{basis}"
        if sym not in lists:
            try:
                lists[sym] = NA.list_rows(sym)
            except Exception:
                lists[sym] = None
        if lists[sym] is None:
            out[k2] = {"verdict": "no-list", "sym": sym, "qe": qe, "basis": basis}
            n += 1
            continue
        want = "Consolidated" if basis == "con" else "Non-Consolidated"
        rows = [r for r in lists[sym] if (r.get("consolidated") or "") == want and _qe(r) == qe]
        rec = {
            "sym": sym,
            "qe": qe,
            "basis": basis,
            "src_seq": seq,
            "stored_rev": cell.get("rev"),
            "stored_op": cell.get("op"),
            "n_rows": len(rows),
        }
        if not rows:
            rec["verdict"] = "src-not-in-list"
        else:
            ordered = sorted(rows, key=lambda r: (dt(r.get("filingDate")) or 0, str(r.get("seqNumber") or "")))
            rec["rows"] = [
                {"seq": r.get("seqNumber"), "filed": dt(r.get("filingDate")), "indAs": r.get("indAs")} for r in ordered
            ]
            seqs = [str(r.get("seqNumber")) for r in ordered]
            if len(ordered) == 1:
                rec["verdict"] = "single-row" if seqs[0] == seq else "src-not-in-list"
            elif seqs[0] == seq:
                rec["verdict"] = "src-is-earliest"
            elif seq in seqs:
                rec["verdict"] = "src-is-later-vintage"
                rec["earliest_seq"] = seqs[0]
            else:
                rec["verdict"] = "src-not-in-list"
        out[k2] = rec
        n += 1
        if n % 200 == 0:
            json.dump(out, open(OUT, "w"), indent=1)
            print("  .. %d/%d" % (n, len(todo)))
    json.dump(out, open(OUT, "w"), indent=1)
    from collections import Counter

    print("done: %d rows" % n)
    for k, c in Counter(v.get("verdict") for v in out.values()).most_common():
        print("   %-24s %d" % (k, c))


def _qe(r):
    d = dt(r.get("toDate"))
    return d if d and d % 100 >= 28 else None


if __name__ == "__main__":
    main()

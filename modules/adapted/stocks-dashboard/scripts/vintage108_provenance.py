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
"""§108 PASS 0 — the ROOT CAUSE, read straight off the provenance we already store.

WHAT THIS FOUND. `vision_rev_fills.json` records, per filled cell, the document each value came
from. For the 2026-07-27 "vision-manual band3/4" pass that document is an NSE archive page, cited
by filename — and the id in the filename is NSE's `seqNumber`. Cross-checking those ids against
the archive list shows the pass read the LATER-vintage page:

    INFY|20150930        src financial_res_INFY_1014609.html
                         seq 1002074 filed 2015-10-13 Non-Ind-AS  pat 6306.0  <- as filed
                         seq 1014609 filed 2016-12-22 Ind-AS      pat 3248.0  <- what it read
    BAJAJ-AUTO|20150630  src ..._1014247.html = the Ind-AS row filed 2016-10-04 (957.36)
    ABB|20160630         src ..._1027851.html = the Ind-AS New row filed 2017-08-04 (55.64)

So §108 is not a scatter of unlucky cells: it is ONE pass with no vintage rule, and the store
carries whichever row NSE happened to list. That makes the population enumerable EXACTLY, offline,
with no detection tolerance to calibrate — 5,059 rev/op fills in the FY16-FY17 window cite an NSE
archive page (3,447 std, 1,612 con).

Advantages over the PAT-based routes:
  * total recall over that pass, instead of whatever a max(2 cr, 3%) screen happens to catch;
  * it sees CON, which detres cannot serve at all (§42);
  * it sees a wrong-vintage REVENUE or OP read even when the quarter's PAT is unchanged between
    vintages — invisible to every PAT screen there is.

VERDICTS  src-is-earliest (clean) · src-is-later-vintage (DEFECT) · single-row (nothing to choose)
          src-not-in-list / no-list (measured absence of the route, never a claim about the cell)

OUT: scripts/_vintage108_prov.json
RUN: python3 scripts/vintage108_provenance.py [--limit N] [--only SYM,SYM]
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
OUT = os.path.join(HERE, "_vintage108_prov.json")
QS = (20150630, 20150930, 20151231, 20160331, 20160630, 20160930, 20161231, 20170331)
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
    NA.JAR = BF.nse_jar()

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
        if qe not in QS or (only and sym not in only):
            continue
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

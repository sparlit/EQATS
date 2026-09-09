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
"""SW-2 phase 2 — the PRE-XBRL selectable era (Dec-2013..Mar-2016 quarters, the ones SW-1's
announcement-stream dating made PIT-visible): fetch BSE's own Clause-35 aspx table for every
shp_history cell there and census the institutions block, so the Any-Other inflation class can
be adjudicated exactly like the XBRL era (see _shp_other_inst_sweep.py).

stage fetch:  aspx pages cached to _aspx_p2/cache (local), census to _shp_oth_p2_census.jsonl:
              per cell {stored, rows(parse_new), domestic_def = mf+banks+ins(+vcf), anyoth}.
stage adjudicate/apply live in _shp_other_inst_sweep-style logic run from the analysis session
(kept separate: the aspx page carries no holder names inline — classification uses the
Jun-2016 XBRL name census via same-size block continuity, plus the curated name_verdicts).
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv_backup, sys.argv = sys.argv, ["p2"]
import fetch_shp_bse_aspx as A
import fetch_shp_bse_hist as H

sys.argv = sys.argv_backup

A.CACHE_ONLY = False
DIRP = os.path.join(HERE, "_aspx_p2")
CENSUS = os.path.join(HERE, "_shp_oth_p2_census.jsonl")
QES = [
    "2013-12-31",
    "2014-03-31",
    "2014-06-30",
    "2014-09-30",
    "2014-12-31",
    "2015-03-31",
    "2015-06-30",
    "2015-09-30",
    "2015-12-31",
    "2016-03-31",
]
_lk = threading.Lock()


def fetch_one(sym, qe, code, stored):
    qtrid = A.qtrid_of(qe)
    html, _cached = A.fetch_page(DIRP, code, qtrid, "New")
    if not html:
        return {"sym": sym, "qe": qe, "code": code, "absent": "no-page"}
    try:
        parsed = A.parse_new(html)
    except Exception as e:
        return {"sym": sym, "qe": qe, "code": code, "absent": f"parse-fail {e!r}"}
    if not parsed:
        return {"sym": sym, "qe": qe, "code": code, "absent": "no-table"}
    rows, name = parsed
    if not isinstance(rows, dict):  # parse_new can return (None, name) — a shell page
        return {"sym": sym, "qe": qe, "code": code, "absent": "no-table-rows"}
    return {"sym": sym, "qe": qe, "code": code, "page_name": name, "stored": stored, "rows": dict(rows.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--adjudicate", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if a.adjudicate:
        p2_adjudicate(a.write)
        return
    hist = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))
    names = hist.get("_names", {})
    cmap, by_name = H.build_codemap(names)
    done = set()
    if os.path.exists(CENSUS):
        for line in open(CENSUS, encoding="utf-8"):
            try:
                r = json.loads(line)
                done.add((r["sym"], r["qe"]))
            except Exception:
                pass
    todo = []
    for sym, qs in hist.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        code = None
        for qe in QES:
            cell = qs.get(qe)
            if not isinstance(cell, list) or (sym, qe) in done:
                continue
            if code is None:
                code = H.resolve(sym, cmap, by_name, names)
            if code is None:
                continue
            todo.append((sym, qe, code, cell))
    if a.limit:
        todo = todo[: a.limit]
    print("p2 fetch: %d cells, %d threads" % (len(todo), a.threads), flush=True)
    fh = open(CENSUS, "a", encoding="utf-8")
    n = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        futs = [ex.submit(fetch_one, *t) for t in todo]
        for fu in as_completed(futs):
            try:
                r = fu.result()
            except Exception as e:
                r = {"sym": "?", "qe": "?", "absent": f"worker-crash {e!r}"}
            with _lk:
                fh.write(json.dumps(r, default=str) + "\n")
                n += 1
                if n % 200 == 0:
                    fh.flush()
                    print("  %d/%d (%.1f/s)" % (n, len(todo), n / max(1e-9, time.time() - t0)), flush=True)
    fh.close()
    print("p2 fetch done: %d" % n)


# ---------------------------------------------------------------- adjudicate + apply
# The pre-2016 store's own family convention (the Wayback-MC majority, ~22k cells) is
# dii = mf + banks + ins (+ vcf) — the Any-Other row is NOT part of dii. A stored cell whose
# dii equals dom + Any-Other got that block folded in by a minority route (trendlyne seam rows,
# the aspx reconciliation fold, or an era XBRL read) — heal dii back to the convention using the
# page's own %(A+B+C) values. No nationality call is needed for dii (unlike the XBRL-era fii
# heal); the fii side of these cells is left as authored and journalled open.
def p2_adjudicate(write=False):
    import datetime
    from collections import Counter

    hist = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))
    led = json.load(open(os.path.join(HERE, "shp_cell_fix.json"), encoding="utf-8"))
    fix = led.setdefault("fix", {})
    st = Counter()
    stamp = datetime.date.today().isoformat()
    n_new = 0
    for line in open(CENSUS, encoding="utf-8"):
        r = json.loads(line)
        if "absent" in r:
            st["absent"] += 1
            continue
        sym, qe = r["sym"], r["qe"]
        cur = (hist.get(sym) or {}).get(qe)
        if cur is None:
            st["cell-gone"] += 1
            continue
        rows = r["rows"]

        def val(slot):
            p = rows.get(slot)
            if not p:
                return None
            return p[1] if p[1] is not None else p[0]

        anyoth, fpi = val("anyoth"), val("fpi")
        oth = 0.0
        if anyoth is not None and fpi is not None:
            oth = 0.0 if abs(anyoth - fpi) <= 0.02 else max(0.0, anyoth - fpi)
        elif anyoth is not None:
            oth = anyoth
        dom = round((val("mf") or 0.0) + (val("banks") or 0.0) + (val("ins") or 0.0) + (val("vcf") or 0.0), 4)
        if oth < 0.25:
            st["no-material-block"] += 1
            continue
        try:
            dii = float(cur[2])
        except (TypeError, ValueError):
            st["bad-stored"] += 1
            continue
        if abs(dii - dom) <= 0.06:
            st["already-convention"] += 1
            continue
        if abs(dii - (dom + oth)) > 0.06:
            st["matches-neither"] += 1
            continue
        if qe in (fix.get(sym) or {}):
            st["already-ledgered"] += 1
            continue
        new = list(cur)
        new[2] = dom
        fix.setdefault(sym, {})[qe] = {
            "cell": new,
            "was": list(cur),
            "src": "bseaspx:%s:qtrid%d" % (r["code"], A.qtrid_of(qe)),
            "why": (
                f"SW-2 phase-2 {stamp}: pre-2016 family convention is dii = mf+banks+ins(+vcf); "
                f"this cell's dii equals that PLUS the institutions Any-Other row ({oth:.2f}pp) "
                "folded in by a minority route. Healed to the page's own domestic rows "
                f"({dom:.4f}). fii left as authored (block nationality not adjudicated here). "
                "Census: _shp_oth_p2_census.jsonl"
            ),
        }
        st["HEAL"] += 1
        n_new += 1
    print("p2 adjudication:", dict(st))
    if write and n_new:
        json.dump(
            led, open(os.path.join(HERE, "shp_cell_fix.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False
        )
        print("wrote shp_cell_fix.json (+%d)" % n_new)
    elif not write:
        print("(dry run — use adjudicate --write)")


if __name__ == "__main__":
    main()

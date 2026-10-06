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


#!/usr/bin/env python3
"""§164q — mid-quarter EVENT rows (scripts/shp_events.json, §22k) in the SEBI form used Dec-2015..2022 never went through
the row-level rules the quarterly cells did (§158 R1/R2/R3, §159 R2-FII, §164c D1, §164j/§164n proof rules). They were
read by parse_shp alone, so an unlabelled institutional Any-Other block sat in dii: IDFCFIRSTB 06-Apr-2021 fii 10.33 / dii
19.26 beside the Mar-2021 quarter's 20.19 / 9.2; POONAWALLA 12-Apr-2018 23.77 / 38.98 beside 47.73. The engine serves an
event row whenever it is the newest visible as-on date (1,271 old-form rows are served at >= 1 month-end).

This runner feeds those filings through scripts/_shp_d1_rowfix.py's classify UNCHANGED (full chain: R1/R2/R3 + R2-FII + D1,
the "first read" path former members took in §164d/§164n): the event store stands in for shp_history, and BSE's own list
rows for the event ("06 Apr 2021", qtrid 109.01) stand in for the quarterly files. Every event date gets the filing(s) BSE
lists for exactly that date; the one whose parse matches the stored row is used (_shp_dii_rowfix.match_filing).
Stages (caches ~/stocks-cache/shp/ev164q; XBRLs fetched there by its fetch.py with scripts/bse_headers.py):
  classify <out.json> [SYM,...]   run the chain, export proposals (was/cell/src/why) + stats
  write    <out.json>   merge into scripts/shp_cell_fix.json `fix` under the event date key (apply_cell_fix_events applies
                        them) — only while the event row still equals `was`; evidence into scripts/_shp_164_audit.json"""
import glob
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
C = os.path.expanduser("~/stocks-cache/shp")
W = os.path.join(C, "ev164q")
LO, HI = (
    "2015-12-01",
    "2022-12-31",
)  # old-form filings only: match_filing refuses 2022-form XBRLs by their members
_dirs = sorted(
    {d for d in glob.glob(os.path.join(C, "**", "xbrl*"), recursive=True) if os.path.isdir(d)}
    | {os.path.join(C, "ex_xbrl"), os.path.join(C, "fii_session/shp_src/xbrl_bse")}
)
os.environ["DII_ROWFIX_CACHES"] = os.pathsep.join(
    [os.path.join(W, "xbrl_bse"), os.path.join(W, "xbrl_nse")]
    + [d for d in _dirs if os.path.isdir(d)]
)
os.environ.setdefault("DII_ROWFIX_WORK", W)
# bse_all + symbol-keyed links to §180b's code-keyed lists (all_fill/bse_lists_v2) for event symbols bse_all lacks
os.environ.setdefault(
    "DII_ROWFIX_LISTS",
    os.path.join(W, "lists_all")
    if os.path.isdir(os.path.join(W, "lists_all"))
    else os.path.join(C, "bse_all"),
)
os.environ.setdefault("D1_ROWFIX_WORK", W)
os.environ.setdefault("FII_ROWFIX_WORK", W)
os.environ.setdefault(
    "DII_ROWFIX_ALLOW_MISSING_LISTS", "1"
)  # symbols without a list are counted and reported, not guessed
MON = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}


def date_of(qtr):
    m = re.match(r"(\d{1,2}) (\w{3}) (\d{4})$", str(qtr or "").strip())
    return (
        "%s-%02d-%02d" % (m.group(3), MON[m.group(2)], int(m.group(1)))
        if m and m.group(2) in MON
        else None
    )


def event_files(bse_rows, lo=LO, hi=HI):
    by = {}
    for r in bse_rows or []:
        d = date_of(r.get("qtr"))
        f = (r.get("XbrlFile") or "").strip()
        if d and f and lo <= d <= hi:
            by.setdefault(d, []).append(
                ((r.get("filing_date_time") or r.get("revised_date_time") or ""), f)
            )
    return {q: sorted(v) for q, v in by.items()}


NEAR_DAYS = 7


def _days(a, b):
    from datetime import date

    def f(x):
        return date(int(x[:4]), int(x[5:7]), int(x[8:10]))

    return abs((f(a) - f(b)).days)


def near_date_files(by, store_dates):
    """A stored event date BSE labels a day or two differently (NSE as-on vs BSE's 'DD Mon YYYY') takes the BSE event
    filing(s) within NEAR_DAYS, nearest first. Safe: match_filing still requires the file's parse to equal the stored row."""
    out = dict(by)
    for d in store_dates:
        if d in by:
            continue
        near = sorted((_days(bd, d), bd) for bd in by if _days(bd, d) <= NEAR_DAYS)
        if near:
            out[d] = [x for _, bd in near for x in by[bd]]
    return out


def classify(out, only=None):
    import _shp_d1_rowfix as D1

    D = D1.D
    import fetch_shareholding as F

    ev = F.load_events()  # fills (§164r) + re-dates (§164m) applied
    ev = {s: v for s, v in ev.items() if not s.startswith("_") and isinstance(v, dict)}
    nse = {}  # rows read from a supplied NSE file: their own file
    for s_, rows in ev.items():
        for d_, row in rows.items():
            m = re.search(
                r"nse:(SHP_\d+_\d+_(\d{14})_WEB\.xml)", str(row[7] if len(row) > 7 else "")
            )
            if m:
                nse.setdefault(s_, {})[d_] = [(m.group(2), m.group(1))]
    code2sym = {}
    for s in ev:
        lp = os.path.join(D.LISTS, s + ".json")
        if not os.path.exists(lp):
            continue
        t = json.load(open(lp))
        rows = t.get("Table") if isinstance(t, dict) else t
        for r in rows or []:
            f = (r.get("XbrlFile") or "").strip()
            if f:
                code2sym[f.split("_")[0]] = s
                break

    def files_for(bse_rows, lo=LO, hi=HI):
        by = event_files(bse_rows, lo, hi)
        code = next(
            (
                (r.get("XbrlFile") or "").split("_")[0]
                for r in bse_rows or []
                if (r.get("XbrlFile") or "").strip()
            ),
            None,
        )
        sym = code2sym.get(code)
        out = near_date_files(by, [d for d in (ev.get(sym) or {}) if lo <= d <= hi]) if sym else by
        for d_, fl in (nse.get(sym) or {}).items():
            if lo <= d_ <= hi:
                out.setdefault(d_, [])
                out[d_] = fl + [x for x in out[d_] if x not in fl]
        return out

    tmp = tempfile.mkdtemp(prefix="ev164q_")
    os.makedirs(os.path.join(tmp, "scripts"))
    json.dump(
        ev, open(os.path.join(tmp, "scripts", "shp_history.json"), "w")
    )  # the event store stands in for the history
    shutil.copy2(
        os.path.join(HERE, "shp_cell_fix.json"), os.path.join(tmp, "scripts", "shp_cell_fix.json")
    )
    D1.REPO = tmp
    D.quarter_files = files_for
    # SCOPE = the population whose QUARTERLY cells went through the same rules: the Nifty 500 roster + every former member
    # (§158/§159 current, §164d/§164n/§164o former; the D1 runner's exmember_scope.json), old tickers folded by FUND_ALIAS.
    # Outside it the quarterly cells are raw parse_shp readings, and healing only the event rows would make one series
    # disagree with itself (ARMANFIN Oct/Dec-2019 events 0.05 -> 21-22 beside its own raw 0.06 quarters).
    sc = json.load(open(os.path.join(C, "w164n_d1", "exmember_scope.json")))
    scope = set(sc["current"]) | set(sc["ex"])
    import fetch_shareholding as F

    fa = getattr(F, "FUND_ALIAS", None) or json.load(
        open(os.path.join(C, "quantmac", "fund_alias.json"))
    )
    syms = sorted(
        s
        for s, v in ev.items()
        if any(LO <= d <= HI for d in v)
        and (not only or s in only)
        and (s in scope or fa.get(s) in scope)
    )
    tag = "ev164q" if not only else "ev164q_one"
    D1.classify(syms, tag, set(syms))  # every event row: first row-level read
    D1.export(tag, out, section="§164q event rows")
    P = json.load(open(out))
    for _k, v in P.items():
        v["why"] = (
            v["why"]
            .replace("FORMER Nifty 500 member", "mid-quarter EVENT row, first row-level read")
            .replace(f"{D1.MARK} (", f"{D1.MARK} — §164q event row (", 1)
        )
    json.dump(P, open(out, "w"), indent=0, ensure_ascii=False)
    shutil.rmtree(tmp, ignore_errors=True)
    print("classify: %d proposals" % len(P))


def write(path):
    import fetch_shareholding as F

    P = json.load(open(path))
    ev = F.load_events()
    lp = os.path.join(HERE, "shp_cell_fix.json")
    raw = open(lp, encoding="utf-8").read()
    led = json.loads(raw)
    fix = led.setdefault("fix", {})
    ap = os.path.join(HERE, "_shp_164_audit.json")
    audit = (
        json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {"_doc": [], "cells": {}}
    )
    audit.setdefault("cells", {})
    n_new = n_sup = n_skip = 0
    for k, v in sorted(P.items()):
        s, d = k.split("|")
        if d[5:] in ("03-31", "06-30", "09-30", "12-31"):
            n_skip += 1
            continue  # quarter-end keys are shp_history's
        cur = (ev.get(s) or {}).get(d)
        if cur is None or not F._cell_eq(cur, v["was"]):
            n_skip += 1
            continue
        ent = {"cell": list(v["cell"]), "was": list(cur), "src": v["src"], "why": v["why"]}
        prior = (fix.get(s) or {}).get(d)
        if prior:
            if not F._cell_eq(cur, prior.get("cell")):
                n_skip += 1
                continue
            ent["superseded"] = prior
            n_sup += 1
        else:
            n_new += 1
        fix.setdefault(s, {})[d] = ent
        audit["cells"][k] = {x: v[x] for x in v if x not in ("was", "cell", "why")}
        audit["cells"][k]["label"] = "164q-events"
    json.dump(led, open(lp, "w", encoding="utf-8"), indent=1, ensure_ascii=("\\u00" in raw))
    json.dump(audit, open(ap, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print("164q write: %d new, %d superseding, %d skipped" % (n_new, n_sup, n_skip))


if __name__ == "__main__":
    st = sys.argv[1]
    if st == "classify":
        classify(sys.argv[2], set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None)
    elif st == "write":
        write(sys.argv[2])
    else:
        sys.exit(__doc__)

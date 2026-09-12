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
"""Emit the open rev cells (point-in-time Nifty-500) as a target file for universal_read.py.

Uses the SAME gap definition as audit_coverage.py -- the no_con_filing ledger and the rolling
4-quarter divergence rule -- so the reader is pointed at exactly the cells the scoreboard counts,
and nothing that is legitimately not-applicable.

`ann` is optional for the reader (it derives an own-season window from the quarter itself, §63e),
so a missing announce date is not a reason to skip a cell.

  python -X utf8 scripts/fill2020_tools/build_targets.py --from 20200101 --to 20260331 [--out P]
"""
import contextlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def scrip_map():
    """symbol -> BSE scrip code. bse_scrips.json is {"by_id": {SYM: code}, "by_isin": {...}};
    _scrip_extra.json is a flat {SYM: code} of hand-resolved and delisted names (§52b)."""
    out = {}
    with contextlib.suppress(Exception):
        out.update({k.upper(): int(v) for k, v in load("scripts/bse_scrips.json")["by_id"].items() if str(v).isdigit()})
    with contextlib.suppress(Exception):
        out.update({k.upper(): int(v) for k, v in load("scripts/_scrip_extra.json").items() if str(v).isdigit()})
    return out


def back4(qe):
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    s = set()
    for k in range(4):
        yy, r = divmod(i - k, 4)
        mm = [3, 6, 9, 12][r]
        s.add(yy * 10000 + mm * 100 + LAST_DAY[mm])
    return s


def main():
    a = int(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 20200101
    b = int(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else 20260331
    out_p = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "/tmp/targets.json"

    idx = load("scripts/indices_history.json")
    rmap = load("scripts/_rename_map.json")
    revop = load("docs/sf_revop.json")
    fund = load("docs/sf_fundamentals.json")
    nc = load("scripts/no_con_filing.json")
    never = set(nc.get("never_filed_con", []))
    stopped = nc.get("stopped_filing_con", {})
    started = nc.get("started_filing_con", {})  # con cells BEFORE this quarter are n/a
    ceased = nc.get("ceased_filing", {})
    # Positive-evidence consolidated-filer set -- replaces the circular trailing-4-quarter
    # divergence test that excluded ONGC, ITC, HDFCBANK and ~4,000 other pre-2020 cells as
    # "does not file consolidated" purely because we lacked their con PAT.
    try:
        EV = load("scripts/con_filer_evidence.json")
    except Exception:
        EV = {}
    scrips = scrip_map()

    divq = {}
    for s, rows in fund.items():
        d = [
            r[0]
            for r in rows
            if len(r) > 3 and r[1] is not None and r[3] is not None and abs(r[3] - r[1]) > max(0.05, abs(r[1]) * 0.001)
        ]
        if d:
            divq[s] = set(d)

    def resolve(sym):
        cur, seen = sym, set()
        while cur not in revop:
            if cur in seen or cur not in rmap:
                return None
            seen.add(cur)
            cur = rmap[cur]
        return cur

    snaps = sorted(idx["Nifty 500"], key=lambda s: s["effectiveDate"])
    members = {}
    for snap in snaps:
        q0 = int(snap["effectiveDate"].replace("-", ""))
        for sym in snap["symbols"]:
            if not sym.upper().startswith("DUMMY"):
                members.setdefault(sym, q0)

    out, noscrip = {}, set()
    for sym in members:
        k = resolve(sym)
        if not k:
            continue
        for qe, row in (revop.get(k) or {}).items():
            q = int(qe)
            if not (a <= q <= b) or not row:
                continue
            for field, i in (("revS", 0), ("revC", 1)):
                if len(row) <= i or row[i] is not None:
                    continue
                if field == "revC":
                    if k in never or (stopped.get(k) and q >= stopped[k]):
                        continue
                    if started.get(k) and q < started[k]:
                        continue  # before the company began consolidating — n/a, not a gap
                    if ceased.get(k) and q >= ceased[k]:
                        continue
                    ev = EV.get(k)
                    if ev is not None:
                        if not ev.get("files_con"):
                            continue
                        fy = ev.get("first_con_fy")
                        if fy and q < (fy - 1) * 10000 + 401:
                            continue
                    elif not (divq.get(k, set()) & back4(q)):
                        continue
                code = scrips.get(k.upper()) or scrips.get(sym.upper())
                if not code:
                    noscrip.add(k)
                    continue
                out["%s|%d|%s" % (k, q, field)] = {"scrip": code, "ann": None}
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print("targets: %d  -> %s" % (len(out), out_p))
    if noscrip:
        print("no BSE scrip for %d symbols (skipped): %s" % (len(noscrip), ", ".join(sorted(noscrip)[:12])))


if __name__ == "__main__":
    main()

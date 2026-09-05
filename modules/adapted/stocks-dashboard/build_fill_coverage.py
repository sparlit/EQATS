# -*- coding: utf-8 -*-
"""Bake docs/fill_coverage.json — the live scoreboard behind docs/fill-coverage.html.

Same gap definition as scripts/fill2020_tools/audit_coverage.py (point-in-time Nifty-500 membership,
the no_con_filing ledger, the rolling 4-quarter divergence rule), so the page and the campaign agree
by construction rather than by me keeping two copies in sync.

Emits, per quarter: member count, empty cells by field, and the NOT-APPLICABLE counts — plus the
actual company list per quarter/field, because "11 open in Mar-2025" is useless without the names.

Regenerated in CI (refresh-fundamentals.yml) so a browser refresh shows current state.

  python -X utf8 scripts/build_fill_coverage.py [--out docs/fill_coverage.json]
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW_START = 20191231
BASELINE = {"revS": 222, "revC": 1502, "patS": 6, "patC": 19}
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}
MAX_NAMES = 60          # per quarter/field, so the payload stays small


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def back4(qe):
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    s = set()
    for k in range(4):
        yy, r = divmod(i - k, 4)
        mm = [3, 6, 9, 12][r]
        s.add(yy * 10000 + mm * 100 + LAST_DAY[mm])
    return s


def quarter_ends(first=20150331, last=20260630):
    out = []
    for y in range(first // 10000, last // 10000 + 1):
        for m in (3, 6, 9, 12):
            qe = y * 10000 + m * 100 + LAST_DAY[m]
            if first <= qe <= last:
                out.append(qe)
    return out


def main():
    out_p = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else \
        os.path.join(ROOT, "docs", "fill_coverage.json")

    idx = load("scripts/indices_history.json")
    rmap = load("scripts/_rename_map.json")
    fund_raw = load("docs/sf_fundamentals.json")
    revop_raw = load("docs/sf_revop.json")
    try:
        nc = load("scripts/no_con_filing.json")
        never = set(nc.get("never_filed_con", []))
        stopped = nc.get("stopped_filing_con", {})
        started = nc.get("started_filing_con", {})
        ceased = nc.get("ceased_filing", {})
    except Exception:
        never, stopped, started, ceased = set(), {}, {}, {}
    # POSITIVE-EVIDENCE consolidated-filer set. Replaces the trailing-4-quarter divergence test,
    # which was circular: it read divergence from OUR OWN stored con PAT, so a company whose con
    # data was merely MISSING produced no signal and got recorded as "does not file consolidated".
    # Measured against screener on 158 company/FY pairs it had excluded: 63% WRONG, including ONGC,
    # ITC, HDFCBANK, NTPC, IOC, HINDALCO and M&M. See build_con_filer_evidence.py.
    try:
        EV = load("scripts/con_filer_evidence.json")
    except Exception:
        EV = {}

    fund = {s: {int(r[0]): (r[1], r[3]) for r in rows if len(r) > 3}
            for s, rows in fund_raw.items()}
    revop = {s: {int(q): (v[0], v[1]) for q, v in d.items()} for s, d in revop_raw.items()}
    divq = {}
    for s, rows in fund_raw.items():
        d = [r[0] for r in rows if len(r) > 3 and r[1] is not None and r[3] is not None
             and abs(r[3] - r[1]) > max(0.05, abs(r[1]) * 0.001)]
        if d:
            divq[s] = set(d)

    def resolve(sym, target):
        cur, seen = sym, set()
        while cur not in target:
            if cur in seen or cur not in rmap:
                return None
            seen.add(cur)
            cur = rmap[cur]
        return cur

    snaps = sorted(idx["Nifty 500"], key=lambda s: s["effectiveDate"])

    def members_at(qe):
        ds = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        best = None
        for s in snaps:
            if s["effectiveDate"] <= ds:
                best = s
            else:
                break
        return [x for x in (best or snaps[0])["symbols"] if not x.upper().startswith("DUMMY")]

    def files_con(sym, qe):
        """True when a consolidated cell at this quarter is a REAL GAP.

        The user-verified ledger still wins where it applies -- those entries were checked against
        screener by hand, and a stop date is positive evidence of a stop. Everything else is decided
        by POSITIVE evidence that the company consolidates at all (own-history divergence in any
        quarter ever, or screener's consolidated annual differing from its standalone). One
        divergent quarter anywhere PROVES consolidation exists; absence in four quarters proves
        nothing about the company, only about our coverage."""
        if sym in never:
            return False
        st = stopped.get(sym)
        if st and qe >= st:
            return False
        # SYMMETRIC COUNTERPART of the stop date: quarters BEFORE a company began filing
        # consolidated are not-applicable, not gaps. IOB filed standalone-only until Mar-2022
        # (runbook §51c: all 8 quarters Mar-2020..Dec-2021 checked against BSE announcements with
        # a glyph-tolerant detector, positive-controlled at Mar-2022) -- its Jun/Sep/Dec-2021 con
        # cells were the last three "open" PAT cells in the 2020+ window and were never fillable.
        # POSITIVE evidence only; never inferred from our own null cells (measured 63% wrong).
        sc = started.get(sym)
        if sc and qe < sc:
            return False
        ev = EV.get(sym)
        if ev is not None:
            if not ev.get("files_con"):
                return False
            fy = ev.get("first_con_fy")
            # Before the earliest evidence we have, we genuinely do not know -- do not claim a gap.
            if fy and qe < (fy - 1) * 10000 + 401:
                return False
            return True
        return bool(divq.get(sym, set()) & back4(qe))

    rows, tot = [], {"revS": 0, "revC": 0, "patS": 0, "patC": 0}
    for qe in quarter_ends():
        mem = members_at(qe)
        c = {"revS": [], "revC": [], "patS": [], "patC": []}
        na = {"patC": 0, "revC": 0}
        for sym in mem:
            fk = resolve(sym, fund)
            if (ceased.get(fk or sym) and qe >= ceased[fk or sym]) or \
               (ceased.get(sym) and qe >= ceased[sym]):
                na["patC"] += 1
                na["revC"] += 1
                continue
            std, con = fund[fk].get(qe, (None, None)) if fk else (None, None)
            if std is None:
                c["patS"].append(sym)
            if con is None:
                if files_con(fk or sym, qe):
                    c["patC"].append(sym)
                else:
                    na["patC"] += 1
            rk = resolve(sym, revop)
            rs, rc = revop[rk].get(qe, (None, None)) if rk else (None, None)
            if rs is None:
                c["revS"].append(sym)
            if rc is None:
                if files_con(rk or sym, qe):
                    c["revC"].append(sym)
                else:
                    na["revC"] += 1
        row = {"qe": qe, "members": len(mem), "na": na,
               "n": {k: len(v) for k, v in c.items()},
               "who": {k: sorted(v)[:MAX_NAMES] for k, v in c.items() if v}}
        rows.append(row)
        if WINDOW_START <= qe <= 20260331:
            for k in tot:
                tot[k] += len(c[k])

    payload = {
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M IST"),
        "window": {"start": WINDOW_START, "end": 20260331},
        "baseline": BASELINE, "totals": tot,
        "closed": {k: BASELINE[k] - tot[k] for k in BASELINE},
        "pct_closed": round(100.0 * (sum(BASELINE.values()) - sum(tot.values()))
                            / sum(BASELINE.values()), 1),
        "max_names": MAX_NAMES,
        "rows": rows,
    }
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print("wrote %s (%d quarters, %d open in window, %.1f%% closed)"
          % (os.path.relpath(out_p, ROOT), len(rows), sum(tot.values()), payload["pct_closed"]))


if __name__ == "__main__":
    main()

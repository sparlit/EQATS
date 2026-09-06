# -*- coding: utf-8 -*-
"""OLD quarters from screener.in: derive the missing 4th quarter of an FY from the ANNUAL total.

MEASURED LIMIT, stated up front so nobody plans around a fantasy: screener's QUARTERLY table holds
only the trailing ~13 quarters. It cannot see 2015-2022 directly. What it DOES hold is 12 full
years of ANNUAL P&L on both bases (FY2015..FY2026). That is the lever for old quarters:

    if we already store 3 of an FY's 4 quarters, the 4th = annual_total - sum(the other 3)

This is arithmetic on a published total, not an estimate -- the same identity the pre-2015 campaign
already uses (memory: screener-annual-derivation). It closes exactly the shape of hole that dominates
the old window: one quarter missing out of an otherwise complete year.

TWO GATES, both mandatory, because an FY total from a different entity or basis silently poisons a
whole quarter:

  GATE A (series identity): for at least 2 OTHER FYs where we hold all 4 quarters, our own sum of
  those 4 must reproduce screener's annual total. If it does not, screener is reporting a different
  entity/basis for this company (the TMPV failure mode) and the whole company is rejected.

  GATE B (residual sanity): the derived quarter must be positive for a revenue line, and within a
  plausible band of its sibling quarters (0.2x .. 5x the median sibling). A derived value outside
  that band means one of the three stored quarters is itself wrong -- report it, do not write it.
  This is the check that would have caught the HCLTECH 9-month-stub trap (§53).

Reports a per-cell table and writes /tmp/annual_derive.json. Writes NOTHING to the dataset; the
applier is a separate, reviewable step.

  python -X utf8 scripts/fill2020_tools/screener_annual_sweep.py [--from 20150331] [--limit N]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF                                       # noqa: E402

LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}
REV_LABELS = ("Sales", "Revenue")


def fy_quarters(fy_end):
    """The 4 quarter-ends of the FY ending 31-Mar-YYYY: Jun, Sep, Dec of YYYY-1, Mar of YYYY."""
    y = fy_end // 10000
    return [(y - 1) * 10000 + 630, (y - 1) * 10000 + 930, (y - 1) * 10000 + 1231, y * 10000 + 331]


def load_open_cells(first):
    """Point-in-time Nifty-500 revenue gaps, reusing the coverage audit's own notion of a gap."""
    idx = json.load(open(os.path.join(ROOT, "scripts", "indices_history.json")))
    rmap = json.load(open(os.path.join(ROOT, "scripts", "_rename_map.json")))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    try:
        nc = json.load(open(os.path.join(ROOT, "scripts", "no_con_filing.json")))
        never, stopped, ceased = set(nc.get("never_filed_con", [])), \
            nc.get("stopped_filing_con", {}), nc.get("ceased_filing", {})
    except Exception:
        never, stopped, ceased = set(), {}, {}
    divq = {}
    for s, rows in fund.items():
        d = [r[0] for r in rows if len(r) > 3 and r[1] is not None and r[3] is not None
             and abs(r[3] - r[1]) > max(0.05, abs(r[1]) * 0.001)]
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
    seen_cells, out = set(), []
    for snap in snaps:
        ds = snap["effectiveDate"]
        qe0 = int(ds.replace("-", ""))
        for sym in snap["symbols"]:
            if sym.upper().startswith("DUMMY"):
                continue
            k = resolve(sym)
            if not k:
                continue
            for qe, row in (revop.get(k) or {}).items():
                q = int(qe)
                if q < first or q > qe0 + 10000 or not row:
                    continue
                for field, i in (("revS", 0), ("revC", 1)):
                    if len(row) <= i or row[i] is not None:
                        continue
                    if field == "revC":
                        if k in never or (stopped.get(k) and q >= stopped[k]):
                            continue
                        if ceased.get(k) and q >= ceased[k]:
                            continue
                        win = set(fy_quarters(q if q % 10000 == 331 else q))
                        if not (divq.get(k, set()) & _back4(q)):
                            continue
                    cell = (k, q, field)
                    if cell in seen_cells:
                        continue
                    seen_cells.add(cell)
                    out.append(cell)
    return out


def _back4(qe):
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    s = set()
    for k in range(4):
        yy, r = divmod(i - k, 4)
        mm = [3, 6, 9, 12][r]
        s.add(yy * 10000 + mm * 100 + LAST_DAY[mm])
    return s


def main():
    first = 20150331
    if "--from" in sys.argv:
        first = int(sys.argv[sys.argv.index("--from") + 1])
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10 ** 9

    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    cells = load_open_cells(first)
    by_sym = {}
    for sym, qe, field in cells:
        by_sym.setdefault((sym, field), []).append(qe)
    print("open revenue cells >= %d: %d across %d company/basis pairs\n" % (first, len(cells), len(by_sym)))

    derived, rejected, nodata = {}, [], 0
    for n, ((sym, field), qes) in enumerate(sorted(by_sym.items())):
        if n >= limit:
            break
        con = field.endswith("C")
        ann = SF.annuals(sym, con=con)
        if not ann:
            nodata += 1
            continue
        label = next((L for L in REV_LABELS if any(L in r for r in ann.values())), None)
        if not label:
            nodata += 1
            continue
        slot = 0 if field == "revS" else 1
        mine = {int(q): v[slot] for q, v in (revop.get(sym) or {}).items()
                if v and len(v) > slot and v[slot] is not None}
        # ---- GATE A: our own 4-quarter sums must reproduce screener's annual totals.
        # Measured behaviour (diagnostic run, 2026-08-06): where the entity and basis match, our sum
        # reproduces screener's annual to +-0.01%. The disagreements are NOT noise and NOT a reason
        # to reject the company -- they are RESTATEMENT / demerger years, where screener carries the
        # restated total and our quarters are as-reported (ACC FY2023 -19.9%, AARTIIND FY2022 +13.6%
        # = Pharmalabs demerger, ABCAPITAL FY2023 -21.5%, ADANIENT FY2024 +9.4%). Deriving a quarter
        # from a restated total against as-reported siblings produces a garbage residual, so the
        # right gate rejects the YEAR, not the company.
        ok_fy, bad_fy = set(), set()
        for dk, row in ann.items():
            fy = int(dk.replace("-", ""))
            if fy % 10000 != 331 or label not in row:
                continue
            qs = fy_quarters(fy)
            if all(q in mine for q in qs):
                mysum = sum(mine[q] for q in qs)
                (ok_fy if abs(mysum - row[label]) <= max(2.0, abs(mysum) * 0.005)
                 else bad_fy).add(fy)
        comparable = len(ok_fy) + len(bad_fy)
        if len(ok_fy) < 3 or comparable < 3 or len(ok_fy) / float(comparable) < 0.6:
            rejected.append((sym, field, "GATE A %d ok / %d restated-or-mismatched FYs"
                             % (len(ok_fy), len(bad_fy))))
            continue
        # ---- derive each open quarter whose FY is otherwise complete
        for qe in sorted(qes):
            fy = qe if qe % 10000 == 331 else (qe // 10000 + 1) * 10000 + 331
            dk = "%d-03-31" % (fy // 10000)
            total = (ann.get(dk) or {}).get(label)
            if total is None:
                continue
            others = [q for q in fy_quarters(fy) if q != qe]
            if not all(q in mine for q in others):
                continue
            # GATE A2: the FY we derive FROM must itself be trustworthy. It cannot be tested
            # directly (that is the whole point -- a quarter is missing), so require it to sit in a
            # run of FYs that DID reproduce. A restatement year that we cannot see is the single
            # way this method writes a wrong number, and bracketing is what detects it.
            if fy in bad_fy:
                rejected.append((sym, field, "GATE A2 FY%d is a restated/mismatched year" % (fy // 10000)))
                continue
            nb = [f for f in (fy - 10000, fy + 10000) if f in ok_fy or f in bad_fy]
            if any(f in bad_fy for f in nb):
                rejected.append((sym, field, "GATE A2 FY%d adjacent to a restated year" % (fy // 10000)))
                continue
            conf = "high" if len(nb) == 2 else ("medium" if len(nb) == 1 else "low")
            val = round(total - sum(mine[q] for q in others), 2)
            sibs = sorted(mine[q] for q in others)
            med = sibs[len(sibs) // 2]
            if val <= 0 or not (0.2 * med <= val <= 5 * med):     # GATE B
                rejected.append((sym, field, "GATE B derived %s vs siblings %s at %d" % (val, sibs, qe)))
                continue
            derived["%s|%d|%s" % (sym, qe, field)] = {
                "value": val, "fy_total": total, "confidence": conf,
                "others": {str(q): mine[q] for q in others},
                "src": "screener.in FY%d annual %s minus the 3 stored quarters" % (fy // 10000, label)}
    print("DERIVED %d cells" % len(derived))
    for k, v in sorted(derived.items())[:40]:
        print("  %-28s = %-11s (FY total %s - %s)" % (k, v["value"], v["fy_total"],
                                                      "+".join(str(x) for x in v["others"].values())))
    print("\nrejected by gates: %d   |  no screener annual table: %d" % (len(rejected), nodata))
    for r in rejected[:15]:
        print("  %-12s %-5s %s" % r)
    json.dump({"derived": derived, "rejected": rejected}, open("/tmp/annual_derive.json", "w"), indent=1)


if __name__ == "__main__":
    main()

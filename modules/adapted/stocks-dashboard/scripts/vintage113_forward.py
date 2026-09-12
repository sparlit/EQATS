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
"""§113g — a FORWARD reader: read the owners row's target column, whatever it says.

★ WHY THE §113 READER COULD NOT DO THIS. `vintage111_read.py` is inverted on purpose: it searches
for the two candidate values (the ledger's `was` and `fixed`) and reports where they land. That is
the right shape for adjudicating BETWEEN two numbers, and it is why it needed no general table
parser. But it is structurally blind to a THIRD value — and §112b's P2 population is literally
named "identity reconciles to NEITHER", so a third value is the expected answer there. Run over
those 53 cells the candidate locator returned 0 reads; COX&KINGS Mar-2017's carrying filing prints
`Net Profit attributable to / Owners of the Company ... (365)` = -3.65 cr against a live -35.53, and
the locator could not see it because neither candidate is -3.65.

So this reads FORWARD: find the owners row, fit the column layout, report the target column.

THE COLUMN MAP IS FITTED, NOT ASSUMED (§59d). A results statement uses one of a few layouts:
    5 cols  [this Q, prev Q, year-ago Q, this FY, last FY]
    4 cols  [this Q, year-ago Q, this FY, last FY]        (Q4 statements that omit the prev quarter)
    3 cols  [this Q, prev Q, year-ago Q]
    4 cols  [this Q, prev Q, year-ago Q, this FY]         (Q1-Q3 statements)
Each layout is tested by ANCHORS: a column whose value reproduces the consolidated cell we already
hold for that quarter. A layout is accepted only if at least one anchor lands where it predicts and
NO anchor lands somewhere it contradicts; then the target quarter's column is read off it.

OUT: _vintage113_forward.json
RUN: python3 -X utf8 vintage113_forward.py
"""
import glob
import json
import os
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W = os.environ["V111_WORK"]
sys.path.insert(0, HERE)
import vintage111_read as RD  # noqa: E402
from vintage111_adjudicate import prevq, quarter_of  # noqa: E402

SCALES = (("crore", 1.0), ("lakh", 0.01), ("million", 0.1), ("thousand", 1e-5))
NEAR_A, NEAR_R = 0.06, 0.004  # tight: this is a READ, not a locator


def near(a, b):
    return a is not None and b is not None and abs(a - b) <= max(NEAR_A, abs(b) * NEAR_R)


def fy(q):
    """('FY', year-ending) for quarter q. A LABEL, not a date: an FY column must never be compared
    against a quarterly stored value, and using 20180331 for both the Mar quarter and FY18 made the
    year-ended column contradict itself out of every layout."""
    y, md = q // 10000, q % 10000
    return ("FY", y if md <= 331 else y + 1)


def layouts(q0):
    p, ya = prevq(q0), q0 - 10000
    f0, f1 = fy(q0), (fy(q0)[0], fy(q0)[1] - 1)
    return [[q0, p, ya, f0, f1], [q0, ya, f0, f1], [q0, p, ya, f0], [q0, p, ya], [q0, ya]]


def variants(nums):
    """The row's figures, with and without a leading ROW INDEX (§59d: numbers to the left of the
    label are indices, not data — COX&KINGS' total row reads [9, -4548, 8546, ...])."""
    yield nums
    if len(nums) > 1 and float(nums[0]).is_integer() and 0 < nums[0] < 40:
        yield nums[1:]


def fit_layout(rows, scale, q0, qe, con):
    """★ THE COLUMN MAP IS A PROPERTY OF THE PAGE, NOT OF ONE ROW.

    The owners row usually CANNOT anchor itself here: for these cells our store holds the TOTAL, so
    the owners figures match nothing we hold, and a row-local fit rejects the very row we want.
    Fit the layout on whichever row on the page does anchor — normally the total — then read the
    owners row at the same column index. Two anchors on ONE row fix the map (§59d tier A).
    """
    best = None
    for lay in layouts(q0):
        if qe not in lay:
            continue
        for _, lab, nums in rows:
            for v in variants(nums):
                if len(v) != len(lay):
                    continue
                anc = [
                    (q, round(con[q], 2), i)
                    for i, q in enumerate(lay)
                    if not isinstance(q, tuple) and q != qe and q in con and near(v[i] * scale, con[q])
                ]
                if len(anc) >= 2 and (best is None or len(anc) > len(best[1])):
                    best = (lay, anc, lab[:60])
    return best


def read_owners(rows, owners_rows, scale, q0, qe, con):
    fit = fit_layout(rows, scale, q0, qe, con)
    if not fit:
        return []
    lay, anc, anchor_lab = fit
    ix = lay.index(qe)
    out = []
    for lab, nums in owners_rows:
        for v in variants(nums):
            if len(v) == len(lay):
                out.append(
                    {
                        "label": lab[:70],
                        "row": v[:8],
                        "value": round(v[ix] * scale, 4),
                        "anchors": anc,
                        "anchor_row": anchor_lab,
                        "layout_len": len(lay),
                        "ix": ix,
                        "tier": "A" if len(anc) >= 2 else "B",
                    }
                )
                break
    return out


def main():
    sel = json.load(open(os.path.join(W, "declined67.json"), encoding="utf-8"))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    mani = {}
    for mp in sorted(glob.glob(os.path.join(W, "_vintage111_docs*.json"))):
        for k, v in json.load(open(mp, encoding="utf-8")).items():
            mani.setdefault(k, {}).update(v.get("docs", {}))
    out = {}
    for key, v in sorted(sel.items()):
        f = v["fix"]
        sym, qe = f["sym"], int(f["qe"])
        con = {r[0]: r[3] for r in fund.get(sym, []) if len(r) > 3 and r[3] is not None}
        live = con.get(qe)
        found = []
        for fn, m in sorted(mani.get("%s|%d" % (sym, qe), {}).items()):
            path = os.path.join(W, "_vintage111_docs", fn)
            if not os.path.exists(path):
                continue
            try:
                doc = fitz.open(path)
            except Exception:
                continue
            q0 = quarter_of(m["ann"])
            for p in range(len(doc)):
                txt = doc[p].get_text()
                if len(txt) < 300:
                    continue
                unm, _ = RD.unit_of(txt)
                rows = RD.page_rows(doc[p])
                attr, orows = None, []
                for i, (_y, lab, nums) in enumerate(rows):
                    if RD.R_ATTR.search(lab):
                        head = (
                            lab
                            if not lab.strip().lower().startswith("attributable")
                            else (rows[i - 1][1] + " " + lab if i else lab)
                        )
                        attr = (bool(RD.R_COMP.search(head)), i)
                    if not nums:
                        continue
                    kind, block = RD.classify(rows, i, attr)
                    if kind in ("owners", "owners~ocr") and block == "profit":
                        orows.append((lab, nums))
                if not orows:
                    continue
                numeric = [r for r in rows if len(r[2]) >= 3]
                for sc_nm, sc in [(unm, dict(SCALES)[unm])] if unm in dict(SCALES) else list(SCALES):
                    got = read_owners(numeric, orows, sc, q0, qe, con)
                    if got:
                        for g in got:
                            g.update({"doc": fn, "win": m["win"], "ann": m["ann"], "page": p, "unit": sc_nm})
                            found.append(g)
                        break
        vals = sorted({round(h["value"], 2) for h in found})
        out[key] = {
            "sym": sym,
            "qe": qe,
            "pri": f.get("_pri"),
            "live": live,
            "was": f["was"],
            "fixed": f["fixed"],
            "reads": found,
            "distinct_values": vals,
            "verdict": (
                "NO-READ"
                if not found
                else "READS-DISAGREE"
                if len(vals) > 1
                else "CONFIRMS-LIVE"
                if near(vals[0], live)
                else "CONTRADICTS-LIVE"
            ),
        }
    json.dump(out, open(os.path.join(W, "_vintage113_forward.json"), "w"), indent=1)
    from collections import Counter

    print("cells %d   %s\n" % (len(out), dict(Counter(x["verdict"] for x in out.values()))))
    for k, x in sorted(out.items(), key=lambda t: (t[1]["verdict"], t[0])):
        if x["verdict"] == "NO-READ":
            continue
        t = "".join(sorted({h["tier"] for h in x["reads"]}))
        print(
            "%-11s %-9s %-3s live=%-10s was=%-9s fixed=%-9s -> filing %-10s [%s] %s"
            % (x["sym"], x["qe"], x["pri"], x["live"], x["was"], x["fixed"], x["distinct_values"], t, x["verdict"])
        )


if __name__ == "__main__":
    main()

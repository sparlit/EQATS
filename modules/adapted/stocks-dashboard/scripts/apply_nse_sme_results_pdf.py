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
"""NSE SME half-years read from result PDFs → sf_fundamentals / sf_revop / revop_fundamentals, FILL-ONLY (runbook §210a).

INPUT  ~/stocks-cache/nse_sme_pdf/reads.json (fetch_nse_sme_results_pdf.py --read: every statement read, raw).

RULES (every one measured on real filings; nothing is taken from a page that does not prove itself)
  1. A statement contributes only YEARS THAT CLOSE (read_sme_result_pdf.decide): revenue H1 + H2 = FY to the filing's
     own rounding, profit too when printed; an OCR'd page only when BOTH close (§168h). A September filing contributes
     the PRIOR year it reprints (H1 prev, H2 prev, FY prev) as well as its own H1 if that year closes later.
  2. The UNIT printed on the page ("in Lakhs", "Amount in Rs." …) is applied, and a filing counts only once its unit is
     PROVEN: one of its closed figures equals (±0.5 %, min ₹0.02 cr) a value we already hold (sf_revop revenue / sf_fundamentals
     profit — the XBRL-era cells), or a figure of another proven filing. Proof spreads backward through the prior-year
     columns each filing reprints (Sep-2024 XBRL cell → the Sep-2024 PDF → its FY24 columns → the Mar-2024 PDF → FY23 …).
     A figure that matches only at another power of ten is a UNIT CONFLICT and holds the filing.
  3. Series convention (§181d): the Sep cell holds H1 (Apr–Sep), the Mar cell holds H2 (Oct–Mar).
  4. Point in time: a cell's `ann` is the date of the EARLIEST proven filing that printed that same figure.
  5. Fill-only. A value we hold is never changed; a disagreement is reported, never written.

  python3 scripts/apply_nse_sme_results_pdf.py [--dry]
"""
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import read_sme_result_pdf as R

ROOT = os.path.dirname(HERE)
C = os.path.expanduser(os.environ.get("NSE_SME_PDF_CACHE", "~/stocks-cache/nse_sme_pdf"))


def near(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.02, 0.005 * abs(b))


def main():
    dry = "--dry" in sys.argv
    reads = json.load(open(os.path.join(C, "reads.json")))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    rv = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    rl = json.load(open(os.path.join(HERE, "revop_fundamentals.json")))
    targets = json.load(open(os.path.join(C, "targets.json")))
    olds = {t["sym"]: t["olds"] for t in targets}
    want = {(t["sym"], t["qe"]) for t in targets}

    def held(sym, qe, basis):
        """(rev, pat) we already hold for the cell, over every symbol the company traded as"""
        rev = pat = None
        for o in olds.get(sym, [sym]):
            r = (rv.get(o) or {}).get(str(qe))
            if r:
                rev = rev if rev is not None else r[0 if basis == "s" else 1]
            f = next((x for x in fund.get(o, []) if x[0] == qe), None)
            if f:
                pat = pat if pat is not None else f[1 if basis == "s" else 3]
        return rev, pat

    # 1. closed triples per statement (unit NOT applied yet)
    stm = []  # [{"sym","basis","unit","dt","file","trip": {fy: {H1,H2,FY}}}]
    for _key, rec in reads.items():
        sym = rec["sym"]
        for st in rec["stmts"]:
            trip = {}
            years = {
                c["date"] // 10000 + (1 if c["date"] % 10000 == 930 else 0) for c in st["cols"]
            }
            for fy in years:
                d = R.decide(st, fy)
                if "FY" in d:
                    trip[fy] = d
            if trip:
                qtr = any(c["date"] % 10000 in (630, 1231) for c in st["cols"])
                stm.append(
                    {
                        "sym": sym,
                        "basis": st["basis"],
                        "unit": st["unit"],
                        "unit_txt": st["unit_txt"],
                        "dt": st["dt"],
                        "file": st["file"],
                        "ocr": st.get("ocr"),
                        "trip": trip,
                        "eps": st.get("eps"),
                        "quarterly": qtr,
                    }
                )
    # 2. unit proof: anchors = held cells; spread through agreeing figures
    proven = [False] * len(stm)
    conflict = [None] * len(stm)
    nodes = {}  # (sym, basis, fy, part) -> (rev, pat) in crore, from proven sources

    def figs(s):
        for fy, d in s["trip"].items():
            for part in ("H1", "H2", "FY"):
                yield fy, part, d[part]

    for i, s in enumerate(stm):
        if not s["unit"]:
            continue
        for fy, part, (r, p) in figs(s):
            if part == "FY":
                continue
            qe = (fy - 1) * 10000 + 930 if part == "H1" else fy * 10000 + 331
            hr, hp = held(s["sym"], qe, s["basis"])
            for a, b in ((r, hr), (p, hp)):
                if a is None or b is None or a == 0:
                    continue
                if near(a * s["unit"], b):
                    proven[i] = True
                elif any(near(a * s["unit"] * 10**k, b) for k in (-5, -3, -2, -1, 1, 2, 3, 5)):
                    conflict[i] = f"figure {a} matches a held {b} only at another power of ten"
    # unit proof by EPS (rupees per share, unit-free): the year's profit in rupees under the printed unit ÷ its basic EPS
    # is the share count; it must sit within 2× of the company's nearest share count on record (scripts/
    # shares_history.json, SHP filings). Units differ by ≥10×, so a count from another year still tells them apart.
    SH = json.load(open(os.path.join(HERE, "shares_history.json")))

    def shares_near(sym, fy):
        best = None
        for o in olds.get(sym, [sym]):
            for d, v in (SH.get(o) or {}).items():
                gap = abs(int(d[:4]) * 12 + int(d[5:7]) - (fy * 12 + 3))
                if v and v[0] and (best is None or gap < best[0]):
                    best = (gap, v[0])
        return best[1] if best else None

    for i, s in enumerate(stm):
        if proven[i] or not s["unit"] or not s["eps"]:
            continue
        for fy, d in s["trip"].items():
            j = d.get("idx", {}).get("FY")
            e = s["eps"][j] if j is not None and j < len(s["eps"]) else None
            p = d["FY"][1]
            sh = shares_near(s["sym"], fy)
            if not (e and p and sh) or abs(e) < 0.05:
                continue
            ratio = p * s["unit"] * 1e7 / e / sh
            if 0.5 <= ratio <= 2.0:
                proven[i] = True
                s["eps_proof"] = round(ratio, 3)
            elif any(0.5 <= ratio * 10**k <= 2.0 for k in (-5, -3, -2, -1, 1, 2, 3, 5)):
                conflict[i] = (
                    conflict[i]
                    or f"EPS × shares puts the unit at another power of ten (ratio {ratio:.4g})"
                )
            break
    changed = True
    while changed:
        changed = False
        for i, s in enumerate(stm):
            if proven[i] and s["unit"]:
                for fy, part, (r, p) in figs(s):
                    k = (s["sym"], s["basis"], fy, part)
                    if k not in nodes:
                        nodes[k] = (
                            r * s["unit"] if r is not None else None,
                            p * s["unit"] if p is not None else None,
                        )
                        changed = True
        for i, s in enumerate(stm):
            if proven[i] or not s["unit"] or conflict[i]:
                continue
            for fy, part, (r, p) in figs(s):
                n = nodes.get((s["sym"], s["basis"], fy, part))
                if n and ((r and near(r * s["unit"], n[0])) or (p and near(p * s["unit"], n[1]))):
                    proven[i] = True
                    changed = True
                    break
    # 3. cells from proven statements; ann = earliest proven filing printing the same figure
    proofs = {}  # (sym, qe, basis) -> the closed year that proves the half
    for i, s in enumerate(stm):
        if not proven[i] or conflict[i]:
            continue
        for fy, d in s["trip"].items():
            u = s["unit"]
            rr = [
                round(d[k][0] * u, 4) if d[k][0] is not None else None for k in ("H1", "H2", "FY")
            ]
            pp = [
                round(d[k][1] * u, 4) if d[k][1] is not None else None for k in ("H1", "H2", "FY")
            ]
            if s["quarterly"]:
                continue
            for qe in ((fy - 1) * 10000 + 930, fy * 10000 + 331):
                proofs.setdefault(
                    (s["sym"], qe, s["basis"]),
                    {
                        "rev": rr,
                        "pat": pp,
                        "how": d["how"],
                        "f": s["file"],
                        "dt": s["dt"][:10],
                        "ocr": bool(s["ocr"]),
                    },
                )
    cells = {}
    disagree = []
    Cn_q = [0]

    def quarterly_year(sym, fy):
        """the company reports QUARTERS that year: a stored Jun / Dec row (our series then holds quarters in Sep / Mar)"""
        for o in olds.get(sym, [sym]):
            for q in ((fy - 1) * 10000 + 630, (fy - 1) * 10000 + 1231):
                if str(q) in (rv.get(o) or {}) or any(x[0] == q for x in fund.get(o, [])):
                    return True
        return False

    for i, s in enumerate(stm):
        if not proven[i] or conflict[i]:
            continue
        for fy, part, (r, p) in figs(s):
            if part == "FY":
                continue
            if s["quarterly"] or quarterly_year(s["sym"], fy):
                Cn_q[0] += 1  # a quarterly filer's Sep / Mar cells are quarters, not halves
                continue
            qe = (fy - 1) * 10000 + 930 if part == "H1" else fy * 10000 + 331
            k = (s["sym"], qe, s["basis"])
            v = (
                round(r * s["unit"], 2) if r is not None else None,
                round(p * s["unit"], 2) if p is not None else None,
            )
            d = int(s["dt"][:10].replace("-", ""))
            if k in cells:
                c = cells[k]
                if (v[0] is not None and c["v"][0] is not None and not near(v[0], c["v"][0])) or (
                    v[1] is not None and c["v"][1] is not None and not near(v[1], c["v"][1])
                ):
                    c["restated"] = True  # a later filing reprints a different figure
                if d < c["ann"]:
                    c.update(v=v, ann=d, file=s["file"])
            else:
                cells[k] = {"v": v, "ann": d, "file": s["file"], "ocr": s["ocr"]}
    Cn = collections.Counter()
    Cn["statements that close"] = len(stm)
    Cn["half figures not used: the company reports quarters that year"] = Cn_q[0]
    Cn["  unit proven"] = sum(proven)
    Cn["  unit conflict"] = sum(1 for c in conflict if c)
    Cn["  no unit printed"] = sum(1 for s in stm if not s["unit"])
    Cn["  unit printed, not yet proven"] = sum(
        1 for i, s in enumerate(stm) if s["unit"] and not proven[i] and not conflict[i]
    )
    # 4. write fill-only
    from build_revop import strip_lender_ebit

    # ORIGINAL FILING RULE (2026-09-28, runbook §210c): a comparative column in a later filing may be RESTATED (14 of 53
    # cross-checkable halves differed — EMKAYTOOLS Sep-24 54.76 → 0.82 after its demerger). A half is written only when the
    # filing that first published it (H1: the Oct–Jan filing; H2: the Apr–Sep filing) prints that same figure as a current
    # period — read as text or image — and `ann` is that filing's date.
    def original_ok(sym, qe, b, v):
        y, m = qe // 10000, qe // 100 % 100
        lo, hi = (
            (y * 10000 + 401, y * 10000 + 930)
            if m == 3
            else (y * 10000 + 1001, (y + 1) * 10000 + 131)
        )
        best = None
        for _key, rec in reads.items():
            if rec["sym"] != sym:
                continue
            for st in rec["stmts"]:
                d = int(st["dt"][:10].replace("-", ""))
                if (
                    st["basis"] != b
                    or not st.get("unit")
                    or not (lo <= d <= hi)
                    or not st.get("rev")
                ):
                    continue
                cols = [c_["date"] for c_ in st["cols"]]
                if qe not in cols:
                    continue
                x = st["rev"][cols.index(qe)]
                if (
                    x is not None
                    and v is not None
                    and near(x * st["unit"], v)
                    and (best is None or d < best)
                ):
                    best = d
        return best

    for (sym, qe, b), c in sorted(cells.items()):
        rev, pat = c["v"]
        od = original_ok(sym, qe, b, rev)
        if od is None:
            Cn["held: the original filing does not print this figure (or was not read)"] += 1
            continue
        c["ann"] = od
        hr, hp = held(sym, qe, b)
        if hr is not None or hp is not None:
            ok = (rev is None or hr is None or near(rev, hr)) and (
                pat is None or hp is None or near(pat, hp)
            )
            Cn["cells already held — %s" % ("agree" if ok else "DISAGREE")] += 1
            if not ok:
                disagree.append([sym, qe, b, [hr, hp], [rev, pat], c["file"]])
            continue
        if (sym, qe) not in want:
            Cn["cell not a target (outside SME era / before listing)"] += 1
            continue
        if c.get("restated"):
            Cn["held: a later filing reprints another figure"] += 1
            continue
        rec = fund.setdefault(sym, [])
        row = next((r for r in rec if r[0] == qe), None)
        if pat is not None:
            i = 1 if b == "s" else 3
            if row is None:
                row = [qe, None, None, None, None]
                rec.append(row)
                rec.sort(key=lambda r: r[0])
            if row[i] is None:
                row[i], row[i + 1] = pat, c["ann"]
                Cn[f"profit cells filled ({b})"] += 1
        for store in (rv, rl):
            d = store.setdefault(sym, {})
            rr = list(d.get(str(qe)) or [None] * 6 + [0, None, None])
            rr += [None] * (9 - len(rr))
            before = list(rr)
            if rev is not None and rr[0 if b == "s" else 1] is None:
                rr[0 if b == "s" else 1] = rev
            if pat is not None and rr[4 if b == "s" else 5] is None:
                rr[4 if b == "s" else 5] = pat
            strip_lender_ebit(sym, rr)
            if rr != before:
                d[str(qe)] = rr
                if store is rv:
                    Cn[f"revenue/profit rows filled ({b})"] += 1
    # proof ledger for build_row_periods (src "nse-pdf"): every half whose stored revenue on its basis now equals the
    # proven one — re-checked there (h1 + h2 = fy, stored = h1 / h2) every run, never trusted as a flag
    P = {}
    for (sym, qe, b), pr in sorted(proofs.items()):
        hr, hp = held(sym, qe, b)
        half = pr["rev"][0 if qe % 10000 == 930 else 1]
        if hr is not None and half is not None and near(hr, half):
            P.setdefault(sym, {}).setdefault(str(qe), {})[b] = pr
    Cn["proof ledger: halves whose stored revenue equals a proven PDF half"] = sum(
        len(v) for v in P.values()
    )
    for k, v in sorted(Cn.items()):
        print("%6d  %s" % (v, k))
    json.dump(
        {
            "disagree": disagree,
            "conflict": [[stm[i]["sym"], stm[i]["file"], c] for i, c in enumerate(conflict) if c],
        },
        open(os.path.join(C, "apply_report.json"), "w"),
        indent=1,
    )
    if disagree:
        print("DISAGREE with a held value (not written):", disagree[:10])
    if not dry:
        json.dump(
            fund,
            open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), "w"),
            separators=(",", ":"),
        )
        json.dump(rv, open(os.path.join(ROOT, "docs", "sf_revop.json"), "w"), separators=(",", ":"))
        json.dump(
            rl, open(os.path.join(HERE, "revop_fundamentals.json"), "w"), separators=(",", ":")
        )
        json.dump(
            {
                "_note": "NSE SME half-years proven from result PDFs (runbook §210a): {SYM: {qEnd: {s|c: {rev: [h1, h2, fy], "
                "pat: [h1, h2, fy], how, f: filing, dt, ocr}}}} in ₹ crore — scripts/apply_nse_sme_results_pdf.py",
                **P,
            },
            open(os.path.join(HERE, "nse_sme_pdf_proofs.json"), "w"),
            separators=(",", ":"),
        )
        print("written")


if __name__ == "__main__":
    main()

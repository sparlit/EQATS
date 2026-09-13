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
"""P0 — REV/PAT coverage vs POINT-IN-TIME Nifty-500, 2002-12-31 -> latest closed quarter.

Denominator = who was IN the index on each quarter-end (nearest-prior snapshot of
indices_history "Nifty 500"), rename-normed, DUMMY* dropped. Same join recipe as
audit_shp_coverage.py (runbook 22f), applied to four fields instead of one.

Fields audited SEPARATELY (they have different walls):
  revS  = sf_revop[sym][qe][0]      revC = sf_revop[sym][qe][1]
  patS  = sf_fundamentals npStd     patC = sf_fundamentals npCon
  patE  = backtest-EFFECTIVE PAT = patC if present else patS   (engine tries=[[3,4],[1,2]])

PAT authority is sf_fundamentals.json, NOT sf_revop's slots 4/5 --- build_quarterly_results.py
takes PAT from fundamentals ("NEVER revop's PAT") and backtest-engine.js consumes the same
[qe,npStd,annStd,npCon,annCon] rows. The revop PAT slots are cross-checked separately below.

Reads the PINNED worktree (checked out AT origin/main), never the shared checkout.
"""
import collections
import contextlib
import csv
import json
import os
import sys

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root of THIS checkout
OUT = os.path.dirname(os.path.abspath(__file__))

ERAS = [
    ("Dec-2002..Dec-2014", 20021231, 20141231),
    ("Mar-2015..Dec-2019", 20150331, 20191231),
    ("Mar-2020..date", 20200331, 20991231),
]


def jload(rel):
    with open(os.path.join(TREE, rel), encoding="utf-8") as fh:
        return json.load(fh)


def qe_list(first, last):
    """All calendar quarter-ends from first to last inclusive, as YYYYMMDD ints."""
    out, y = [], first // 10000
    while y <= last // 10000:
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            v = y * 10000 + m * 100 + d
            if first <= v <= last:
                out.append(v)
        y += 1
    return out


def main():
    IH = jload("scripts/indices_history.json")
    RMAP = jload("scripts/_rename_map.json")
    REVOP = jload("docs/sf_revop.json")
    FUND = jload("docs/sf_fundamentals.json")

    def norm(s):
        s = str(s).strip().upper()
        seen = set()
        while s in RMAP and s not in seen and RMAP[s] != s:
            seen.add(s)
            s = RMAP[s]
        return s

    snaps = sorted(
        (s["effectiveDate"], [norm(x) for x in s["symbols"] if not str(x).upper().startswith("DUMMY")])
        for s in IH["Nifty 500"]
    )
    print("N500 snapshots: %d, %s .. %s" % (len(snaps), snaps[0][0], snaps[-1][0]))

    def members(qe_iso):
        best = []
        for ed, syms in snaps:
            if ed <= qe_iso:
                best = syms
            else:
                break
        return best

    # ---- index our two stores by normalised symbol -------------------------
    rev_by = collections.defaultdict(dict)  # sym -> qe -> row
    for sym, d in REVOP.items():
        n = norm(sym)
        for k, v in d.items():
            with contextlib.suppress(Exception):
                rev_by[n][int(k)] = v
    pat_by = collections.defaultdict(dict)  # sym -> qe -> (npStd, npCon)
    for sym, rows in FUND.items():
        n = norm(sym)
        for r in rows:
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int):
                pat_by[n][r[0]] = (r[1], r[3])

    # latest closed quarter present anywhere
    allq = set()
    for d in rev_by.values():
        allq |= set(d)
    last_q = max(q for q in allq if q <= 20260630)
    quarters = qe_list(20021231, last_q)
    print("quarters: %d, %d .. %d" % (len(quarters), quarters[0], quarters[-1]))

    FIELDS = ["revS", "revC", "patS", "patC", "patE"]
    per_q = []
    era_tot = {e[0]: collections.Counter() for e in ERAS}

    for q in quarters:
        iso = "%04d-%02d-%02d" % (q // 10000, (q // 100) % 100, q % 100)
        mem = members(iso)
        n = len(mem)
        c = collections.Counter()
        for sym in mem:
            row = rev_by.get(sym, {}).get(q)
            ps, pc = pat_by.get(sym, {}).get(q, (None, None))
            revS = row[0] if row else None
            revC = row[1] if row else None
            if revS is not None:
                c["revS"] += 1
            if revC is not None:
                c["revC"] += 1
            if ps is not None:
                c["patS"] += 1
            if pc is not None:
                c["patC"] += 1
            if (pc if pc is not None else ps) is not None:
                c["patE"] += 1
        per_q.append((q, n, dict(c)))
        for name, lo, hi in ERAS:
            if lo <= q <= hi:
                era_tot[name]["den"] += n
                for f in FIELDS:
                    era_tot[name][f] += c[f]

    # ---- report ------------------------------------------------------------
    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("# P0 — REV/PAT coverage vs point-in-time Nifty-500")
    import subprocess

    try:
        pin = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=TREE, capture_output=True, text=True
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        pin = "unknown"
    emit(f"Tree read at commit {pin}. Denominator = point-in-time N500 membership.")
    emit("PAT from sf_fundamentals (the authority build_quarterly_results + backtest-engine use).")
    emit("")
    emit("| era | member-qtrs | revS | revC | patS | patC | patE(backtest) |")
    emit("|---|---|---|---|---|---|---|")
    for name, lo, hi in ERAS:
        t = era_tot[name]
        den = t["den"] or 1
        emit(
            "| {} | {} | {} | {} | {} | {} | {} |".format(
                name, "{:,}".format(t["den"]), *["%.1f%%" % (100.0 * t[f] / den) for f in FIELDS]
            )
        )
    tot = collections.Counter()
    for t in era_tot.values():
        tot.update(t)
    den = tot["den"] or 1
    emit(
        "| **ALL** | **{}** | {} |".format(
            "{:,}".format(tot["den"]), " | ".join("**%.1f%%**" % (100.0 * tot[f] / den) for f in FIELDS)
        )
    )
    emit("")
    emit("Absolute cells held: " + ", ".join("{}={}".format(f, f"{tot[f]:,}") for f in FIELDS))
    emit("Absolute cells MISSING: " + ", ".join("{}={}".format(f, "{:,}".format(tot["den"] - tot[f])) for f in FIELDS))

    with open(os.path.join(OUT, "coverage_by_quarter.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["qe", "n500_members"] + FIELDS + [f + "_pct" for f in FIELDS])
        for q, n, c in per_q:
            w.writerow(
                [q, n]
                + [c.get(f, 0) for f in FIELDS]
                + ["%.1f" % (100.0 * c.get(f, 0) / n) if n else "" for f in FIELDS]
            )

    # ---- free internal cross-check: sf_revop PAT slots vs sf_fundamentals ---
    emit("")
    emit("## Internal cross-check — sf_revop[4]/[5] vs sf_fundamentals (zero network)")
    agree = collections.Counter()
    examples = {"std": [], "con": []}
    for sym, d in rev_by.items():
        pd_ = pat_by.get(sym) or {}
        for q, row in d.items():
            for idx, pi, lbl in ((4, 0, "std"), (5, 1, "con")):
                a = row[idx]
                b = (pd_.get(q) or (None, None))[pi]
                if a is None and b is None:
                    continue
                if a is None or b is None:
                    agree[lbl + "_one_sided"] += 1
                    continue
                tol = max(0.5, abs(b) * 0.005)
                if abs(a - b) <= tol:
                    agree[lbl + "_match"] += 1
                else:
                    agree[lbl + "_DIFFER"] += 1
                    if len(examples[lbl]) < 15:
                        examples[lbl].append((sym, q, a, b))
    for lbl in ("std", "con"):
        m, dfr, one = agree[lbl + "_match"], agree[lbl + "_DIFFER"], agree[lbl + "_one_sided"]
        tot2 = m + dfr
        emit(
            "- **{}**: {} match, **{} DIFFER** ({:.3f}%), {} present in only one store".format(
                lbl, f"{m:,}", f"{dfr:,}", 100.0 * dfr / tot2 if tot2 else 0, f"{one:,}"
            )
        )
    for lbl in ("std", "con"):
        if examples[lbl]:
            emit(f"  - {lbl} examples (sym, qe, revop, fundamentals):")
            for e in examples[lbl][:10]:
                emit("    - {} {}  revop={}  fund={}".format(*e))

    with open(os.path.join(OUT, "P0_FINDINGS.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\nwrote P0_FINDINGS.md + coverage_by_quarter.csv")


if __name__ == "__main__":
    main()

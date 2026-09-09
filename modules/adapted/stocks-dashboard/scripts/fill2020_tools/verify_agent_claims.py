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
"""Verify every agent OURS-WRONG claim by INDEPENDENT arithmetic, then apply only what survives.

Why this exists. I sliced the 768 suspects so each of the six triage agents got a DISJOINT set --
fastest, but it left every cell with exactly one opinion, so a consensus-by-count rule fires almost
never (2 of 219). The answer is not more agents voting; it is to stop treating an agent's verdict as
evidence at all and instead RE-DERIVE it here. An agent's real contribution is the CANDIDATE VALUE
and the mechanism it spotted; whether that candidate is right is a question arithmetic can settle.

Each claim (sym, quarter, field, suggested) must pass at least one STRONG test:

  T1 SCREENER-QUARTER   the suggested value matches screener's own figure for that quarter
                        (only available inside its ~13-quarter window).
  T2 FY-IDENTITY        substituting the suggestion makes our four quarters sum to screener's
                        annual total, where the current value does NOT. This is the strongest test
                        available before ~2023, and it is independent of T1.
  T3 CUMULATIVE         ours == the earlier stored quarters of that FY + the suggestion.
                        Self-contained: needs no outside source at all.
  T4 POWER-OF-TEN       ours / suggested is exactly 10, 100 or 1000 AND the suggestion sits inside
                        the neighbour band while the current value does not.

Plus the standing guards: the cell must still hold what the claim was computed against, the
suggestion must be positive, and it must fall within [0.2x, 5x] of the company's own neighbouring
quarters on the same basis.

A claim that passes NOTHING is not written -- it goes to the review list with the tests it failed.
That is the honest outcome for "an agent thought so but nothing corroborates it".

  python -X utf8 scripts/fill2020_tools/verify_agent_claims.py [--apply]
"""
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import screener_fetch as SF  # noqa: E402

DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER_DATA = os.path.join(SCRIPTS, "revop_fundamentals.json")
JOURNAL = os.path.join(SCRIPTS, "agent_verified_heals.json")
REVIEW = os.path.join(SCRIPTS, "_agent_claims_review.json")
SLOT = {"revS": 0, "revC": 1}


def close(a, b, tol=0.012, floor=1.0):
    return a is not None and b is not None and abs(a - b) <= max(floor, abs(b) * tol)


def fy_of(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return y + 1 if m > 3 else y


def fy_quarters(fy):
    return [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930, (fy - 1) * 10000 + 1231, fy * 10000 + 331]


def band(revop, sym, qe, field):
    slot = SLOT[field]
    have = []
    for q, row in (revop.get(sym) or {}).items():
        if int(q) == qe or not row or len(row) <= slot or row[slot] is None or row[slot] <= 0:
            continue
        have.append((abs(int(q) - qe), row[slot]))
    vals = sorted(v for _d, v in sorted(have)[:8])
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def main():
    dry = "--apply" not in sys.argv
    revop = json.load(open(DOCS))

    claims = {}
    for f in sorted(glob.glob("/tmp/triage_out_*.json")):
        for r in json.load(open(f)):
            if r.get("bucket") != "OURS-WRONG" or r.get("suggested_value") is None:
                continue
            try:
                qe = int(r["qe"])
            except Exception:
                continue
            claims["%s|%d|%s" % (r["sym"], qe, r["field"])] = {
                "suggested": float(r["suggested_value"]),
                "conf": r.get("confidence"),
                "reason": r.get("reason", "")[:120],
                "src": os.path.basename(f),
            }

    ok, bad = [], []
    cache = {}
    for key, c in sorted(claims.items()):
        sym, qe, field = key.split("|")
        qe = int(qe)
        slot = SLOT[field]
        row = (revop.get(sym) or {}).get(str(qe))
        cur = row[slot] if row and len(row) > slot else None
        new = c["suggested"]
        if cur is None:
            bad.append(dict(c, cell=key, current=None, failed="cell is empty, not a correction"))
            continue
        if new <= 0 or close(new, cur, 0.005):
            bad.append(dict(c, cell=key, current=cur, failed="no change / non-positive"))
            continue
        med = band(revop, sym, qe, field)
        if med and not (0.2 * med <= new <= 5 * med):
            bad.append(dict(c, cell=key, current=cur, failed=f"suggestion outside neighbour band (median {med:.2f})"))
            continue

        con = field.endswith("C")
        ck = (sym, con)
        if ck not in cache:
            try:
                cache[ck] = (SF.quarters(sym, con=con), SF.annuals(sym, con=con))
            except Exception:
                cache[ck] = ({}, {})
        sq, sa = cache[ck]
        passed = []

        # T1 screener quarter
        lab = next((L for L in ("Sales", "Revenue") if any(L in r for r in sq.values())), None) if sq else None
        dk = "%d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        t = (sq.get(dk) or {}).get(lab) if lab else None
        if t is not None and close(new, t):
            passed.append(f"T1 screener-quarter {t:.2f}")

        # T2 FY identity (must FIX the year, not merely be inside it)
        alab = next((L for L in ("Sales", "Revenue") if any(L in r for r in sa.values())), None) if sa else None
        fy = fy_of(qe)
        tot = (sa.get("%d-03-31" % fy) or {}).get(alab) if alab else None
        if tot is not None:
            sibs = []
            for q in fy_quarters(fy):
                if q == qe:
                    continue
                rr = (revop.get(sym) or {}).get(str(q))
                sibs.append(rr[slot] if rr and len(rr) > slot else None)
            if all(s is not None for s in sibs):
                now_ok = close(sum(sibs) + cur, tot, 0.015, 2.0)
                new_ok = close(sum(sibs) + new, tot, 0.015, 2.0)
                if new_ok and not now_ok:
                    passed.append("T2 FY%d identity fixed (%.2f vs annual %s)" % (fy, sum(sibs) + new, tot))

        # T3 cumulative (self-contained)
        qs = fy_quarters(fy)
        if qe in qs and qs.index(qe) > 0:
            earlier = [(revop.get(sym) or {}).get(str(q)) for q in qs[: qs.index(qe)]]
            vals = [e[slot] if e and len(e) > slot else None for e in earlier]
            if all(v is not None for v in vals) and close(cur, sum(vals) + new, 0.02):
                passed.append(f"T3 cumulative: ours == earlier {sum(vals):.2f} + suggestion")

        # T4 power of ten
        if new:
            ratio = cur / new
            for p in (10.0, 100.0, 1000.0):
                if abs(ratio - p) < 0.02 * p or abs(ratio - 1.0 / p) < 0.02 / p:
                    if med and not (0.2 * med <= cur <= 5 * med):
                        passed.append(f"T4 power-of-ten x{p:g}, current value outside neighbour band")
                    break

        # T1 IS NOT INDEPENDENT EVIDENCE. The agents' suggested values ARE screener's numbers, so
        # "suggestion == screener" merely proves the agent transcribed correctly -- it says nothing
        # about who is right. Accept T1 alone ONLY when our CURRENT value is itself outside the
        # company's neighbour band, which independently shows the stored cell is broken. Otherwise
        # require a genuinely independent test: T2 (the FY total only reconciles WITH the
        # suggestion), T3 (self-contained cumulative identity) or T4 (clean power of ten).
        strong = [p for p in passed if p[:2] in ("T2", "T3", "T4")]
        if not strong and passed:
            if med and not (0.2 * med <= cur <= 5 * med):
                strong = [*passed, f"current value outside neighbour band (median {med:.2f})"]
        if strong:
            ok.append((sym, str(qe), field, cur, new, strong, c))
        else:
            bad.append(
                dict(
                    c,
                    cell=key,
                    current=cur,
                    failed="only T1 (matches screener) -- circular, and our stored value is plausible; needs the filing"
                    if passed
                    else "no test passed (T1-T4)",
                )
            )

    print("agent OURS-WRONG claims: %d | VERIFIED: %d | unverified: %d\n" % (len(claims), len(ok), len(bad)))
    tests = collections.Counter(p.split()[0] for _s, _q, _f, _c, _n, ps, _cc in ok for p in ps)
    print("verified by:", dict(tests), "\n")
    for sym, qe, field, cur, new, passed, c in ok[:60]:
        print("  %-12s %-9s %-5s %13.2f -> %-12.2f  %s" % (sym, qe, field, cur, new, passed[0][:52]))
    if dry:
        json.dump(bad, open(REVIEW, "w"), indent=1)
        print(f"\nDRY RUN -- nothing written. unverified -> {os.path.basename(REVIEW)}")
        return

    journal = {}
    for path in (DOCS, LEDGER_DATA):
        d = json.load(open(path))
        n = 0
        for sym, qe, field, cur, new, passed, c in ok:
            row = (d.get(sym) or {}).get(qe)
            if not row or len(row) <= SLOT[field]:
                continue
            if row[SLOT[field]] is None or not close(row[SLOT[field]], cur, 0.001, 0.02):
                continue
            row[SLOT[field]] = round(new, 2)
            d[sym][qe] = row
            n += 1
            journal[f"{sym}|{qe}|{field}"] = {
                "was": cur,
                "now": round(new, 2),
                "verified_by": passed,
                "agent_reason": c["reason"],
                "agent_confidence": c["conf"],
                "agent_slice": c["src"],
                "applied": "2026-08-07 agent-claim verification",
            }
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-30s healed %d" % (os.path.basename(path), n))
    led = json.load(open(JOURNAL)) if os.path.exists(JOURNAL) else {}
    led.update(journal)
    json.dump(led, open(JOURNAL, "w"), indent=1, sort_keys=True)
    json.dump(bad, open(REVIEW, "w"), indent=1)
    print("journalled %d -> %s | %d unverified held" % (len(journal), os.path.basename(JOURNAL), len(bad)))


if __name__ == "__main__":
    main()

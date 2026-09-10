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
"""PAT from the SAME Moneycontrol payload the revenue pass already downloaded  (2026-08-11)

THE MISS THIS FIXES, stated plainly: the revenue sweep pulled `Net Sales/Income from operations`
out of a payload that also carries the whole P&L — and threw the rest away. PAT was in every one of
the ~190 responses already on disk. The user caught it: "why u didnt try this from moneycontrol?"
There is no new fetch for a cached symbol, and the same one-request-per-(symbol,basis) cost for the
rest. Open at the time of writing: 2,943 standalone PAT and 4,638 consolidated PAT member-cells.

★ THE BASIS ROW MATTERS MORE HERE THAN FOR REVENUE (§2d, memory project-stocks-profit-basis).
Our stored consolidated PAT is OWNERS-ATTRIBUTABLE. Moneycontrol prints the chain:

    Net Profit/(Loss) For the Period      <- total PAT, BEFORE minority interest
    Minority Interest
    Share Of P/L Of Associates
    Net P/L After M.I & Associates        <- OWNERS basis. THIS is our consolidated cell.

Taking the first row for a consolidated cell is the total-vs-owners error that §67 re-adjudicated 18
heals over and §76c caught arriving through a tolerance. So: consolidated prefers
`Net P/L After M.I & Associates` and only falls back to `Net Profit/(Loss) For the Period` when the
company prints no minority-interest line at all (wholly-owned structures — GICRE's statements print
no NCI row, §55c). Standalone uses `Net Profit/(Loss) For the Period`, where the distinction does
not arise.
As with revenue, the row is CHOSEN BY REPRODUCTION where we have stored values to test against —
label preference decides only when both reproduce equally.

Gates are the revenue ones, unchanged, because they are about series identity not about the field:
no disagreement within ±6 quarters of the target, ≥3 anchors in that window, <15% global. PAT gets
one extra guard of its own: a PAT can legitimately be negative or near zero, so the revenue
positivity test is dropped and the §83 magnitude band is applied on ABSOLUTE value and only when the
neighbourhood is itself substantial (a band around a loss-making quarter means nothing).

Writes docs/sf_fundamentals.json slots 1 (std) and 3 (con), fill-only, NEVER creating a row that
does not exist. Ledger scripts/mc_pat_fills.json (tracked).
Run: python -X utf8 scripts/fill2020_tools/mc_pat_fetch.py [--only SYM,SYM] [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)

import mc_quarterly_fetch as MC  # noqa: E402

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
FILLS = os.path.join(SCRIPTS, "mc_pat_fills.json")
SKIPS = os.path.join(HERE, "_mc_pat_skips.json")

PAT_SLOT = {"std": 1, "con": 3}
TOTAL_ROW = "Net Profit/(Loss) For the Period"
OWNERS_ROW = "Net P/L After M.I & Associates"
MI_ROW = "Minority Interest"
BAND_LO, BAND_HI = 0.2, 5.0
NEIGHBOURS = 6
BAND_FLOOR = 5.0  # crore; below this a magnitude band is meaningless


def pat_series(code, basis, ours):
    """({qe: pat}, label). Consolidated prefers the OWNERS row; see the module docstring."""
    raw = MC.series_raw(code, basis, limit=400)
    if not raw:
        return {}, None
    labels = [OWNERS_ROW, TOTAL_ROW] if basis == "con" else [TOTAL_ROW, OWNERS_ROW]
    best, best_label, best_score = {}, None, -1
    for label in labels:
        cand = {}
        for row in raw:
            qe = MC.qe_of(row.get("yrc0"))
            v = MC.num(row.get(label))
            if qe and v is not None:
                cand[qe] = v
        if not cand:
            continue
        score = sum(
            1
            for qe, v in (ours or {}).items()
            if qe in cand and abs(cand[qe] - v) <= max(MC.TOL_ABS, MC.TOL_REL * max(abs(v), abs(cand[qe])))
        )
        # preference order breaks ties, reproduction wins outright
        if score > best_score:
            best, best_label, best_score = cand, label, score
    return best, best_label


def band_ok(ours, qe, v):
    near = sorted(ours.items(), key=lambda kv: abs(kv[0] - qe))[:NEIGHBOURS]
    vals = sorted(abs(x) for _, x in near)
    if not vals:
        return True, None
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2.0
    if med < BAND_FLOOR:  # a band around near-zero PATs proves nothing
        return True, None
    r = abs(v) / med
    return (BAND_LO <= r <= BAND_HI), round(r, 3)


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    apply_it = "--apply" in argv

    fund = json.load(open(FUND))
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    codes = json.load(open(MC.CODES)) if os.path.exists(MC.CODES) else {}

    work = []
    for sym, rows in fund.items():
        if only and sym not in only:
            continue
        for basis in ("std", "con"):
            slot = PAT_SLOT[basis]
            have = {r[0]: r[slot] for r in rows if len(r) > slot and r[slot] is not None}
            gaps = [r[0] for r in rows if len(r) > slot and r[slot] is None]
            if len(have) >= 6 and gaps:
                work.append((sym, basis, sorted(gaps, reverse=True), have))
    work.sort(key=lambda t: (-len(t[2]), t[0]))
    print(
        "gateable (symbol,basis) PAT pairs: %d | open PAT cells in scope: %d"
        % (len(work), sum(len(g) for _, _, g, _ in work)),
        flush=True,
    )

    read = 0
    for n, (sym, basis, gaps, ours) in enumerate(work, 1):
        pre = sym in codes
        code = MC.resolve_code(sym, codes)
        if not pre:
            MC._jitter(0.4, 0.9)
        if not code:
            skips[f"{sym}|{basis}"] = "no verified moneycontrol code"
            continue
        cached = os.path.exists(os.path.join(MC.CACHE, f"{code}_{basis}_400.json"))
        mc, label = pat_series(code, basis, ours)
        if not cached:
            MC._jitter()
        if not mc:
            skips[f"{sym}|{basis}"] = f"RETRYABLE empty {basis} series (run-time, not evidence)"
            continue
        got = 0
        for qe in gaps:
            key = "%s|%d|%s" % (sym, qe, basis)
            if key in fills or qe not in mc:
                continue
            v = mc[qe]
            ok, match, bad, why = MC.gate(mc, ours, target=qe)
            if not ok:
                skips[key] = f"GATE({label}): {why}"
                continue
            bok, ratio = band_ok(ours, qe, v)
            if not bok:
                skips[key] = f"§83 band: {v:.2f} is {ratio}x the nearest-6 |median|"
                continue
            fills[key] = {
                "pat": round(v, 2),
                "row_label": label,
                "sc_id": code,
                "basis": basis,
                "neighbour_ratio": ratio,
                "gate": "%d anchors, %d distant disagreements, none within ±6 quarters" % (len(match), len(bad)),
                "src": "moneycontrol appfeeds quarterly_results_responsive limit=400",
            }
            read += 1
            got += 1
        if got:
            print("%-13s %-3s +%-3d PAT cells (%s, %d anchors)" % (sym, basis, got, label, len(ours)), flush=True)
        if n % 25 == 0:
            json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
            print("  [%d/%d pairs] %d PAT cells read" % (n, len(work), read), flush=True)

    json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
    print("\nREAD %d PAT cells (%d ledgered)" % (read, len(fills)))
    if not apply_it:
        print("(dry run — ledgers written, data files untouched. Re-run with --apply)")
        return

    applied = 0
    held = 0
    for key, v in sorted(fills.items()):
        # HELD by the con-fallback screen (mc_con_fallback_screen.py): Moneycontrol's consolidated
        # table repeats the STANDALONE figure in quarters with no consolidated filing.
        if v.get("held"):
            held += 1
            continue
        sym, qe_s, basis = key.split("|")
        qe, slot = int(qe_s), PAT_SLOT[basis]
        for row in fund.get(sym, []):
            if row[0] == qe and len(row) > slot and row[slot] is None:
                row[slot] = v["pat"]
                applied += 1
                break
    json.dump(fund, open(FUND, "w"), separators=(",", ":"))
    print("APPLIED %d cells; HELD %d by the con-fallback screen" % (applied, held))


if __name__ == "__main__":
    main()

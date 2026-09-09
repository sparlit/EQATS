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
"""FILL THE CELLS OUR ANCHORS CANNOT REACH — gate on the SOURCE's own FY identity  (2026-08-11)

THE BLOCK THIS OPENS. Every Moneycontrol pass so far gated on anchors: the series must reproduce >=3
of our own stored quarters near the target. That is the right test and it is useless for exactly the
companies with the widest gaps, because it needs six stored quarters on that basis before it means
anything. Measured: 1,441 (symbol, basis) pairs, 34,993 open cells below that floor, 2,164 of them
member-scoped real gaps. They were never ATTEMPTED — not refused, not proven absent, skipped before a
request went out. This is the largest untried block left in the store.

THE SUBSTITUTE, which asks nothing of our store: make the SOURCE prove itself.
    sum(the four quarters of a financial year) == that FY's annual, SAME LABEL, both from MC.
A series that reconciles cannot contain a duplicated quarter, a stray period, or a lakh-vs-crore
scale error in that year — any of those blows the sum apart.

★ CALIBRATED, NOT GUESSED (2026-08-11, 271 FY rows from 22 pairs the ANCHOR gate already trusts, so
every failure there is the identity's own noise rather than a bad series):
    median |sum - annual| = 0.00        p90 = 0.71%        p99 = 28.3%        max = 52.5%
The distribution is BIMODAL — either exact to the cent or off by whole percent, with almost nothing
between. The tail is structural, not noisy: ADANIENT std 28%, ADANIPORTS con 25%, 3IINFOLTD 50% —
restatement years where the annual was restated after a merger and the quarterly table was not. So
the gate runs PER FY, not per series: a company with one restated year still yields every other year.
tol = max(2.0 crore, 0.2%) accepts 89.7% of anchor-trusted FYs.

★★ WHAT THIS GATE CANNOT DO, and the caller must respect it: it cannot choose the revenue ROW. Net
Sales and Total Income each reconcile against their own annual, so the identity holds for BOTH and
distinguishes NEITHER. The row is still chosen by reproduction against our stored quarters — scored
across BOTH bases, because how we store revenue is a property of the company, not of the basis — and
a company with no stored quarter anywhere is REFUSED rather than defaulted. Guessing the row would
reproduce SIEMENS (Net Sales 2753.3 vs Total Income 2825.9, both real, both plausible) at scale.

Every con cell additionally passes §85 (MC con must differ from MC's OWN std on the same label) and
the §83 magnitude band against MC's own neighbouring quarters.

★★★ AND THE ONE THE IDENTITY CANNOT SEE: §51a, WAS A CONSOLIDATED RESULT EVER FILED? An internally
consistent consolidated series proves the SOURCE is coherent. It says nothing about whether the
company filed a consolidated quarterly result at all — and quarterly consolidateds only became
compulsory from FY2020, so for the pre-2016 cells this route reaches, non-filing is the norm. Caught
on the first full run: 21 of 258 candidates belonged to companies our own filing evidence records as
never_filed_con (TATAMETALI 15, SAKHTISUG 4) or predated their first consolidated filing (PUNJLLOYD
2), while Moneycontrol served a table for them that reconciles against its own annual AND differs
from its own standalone. Both sources cannot be right. Those cells are HELD as a documented conflict
— not written, and not treated as proof our ledger is wrong. Resolving one needs the filing itself.

Run: python -X utf8 scripts/fill2020_tools/mc_fy_identity_fill.py [--members-only] [--limit-pairs N] [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)

import mc_annual as MA  # noqa: E402
import mc_quarterly_fetch as MC  # noqa: E402

REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FILLS = os.path.join(SCRIPTS, "mc_fyident_fills.json")
SKIPS = os.path.join(HERE, "_mc_fyident_skips.json")
IDXH = os.path.join(SCRIPTS, "indices_history.json")

# ★ SHARED, never a local copy. A private list here silently omitted the DERIVED bank row and refused
# every bank with "no candidate row reproduces" — which reads like a wrong-company map (§49) and was
# really this list being out of step with the reader's.
REV_ROWS = MC.REV_ROWS
SLOT = {"std": 0, "con": 1}
TOL_ABS_FY, TOL_REL_FY = 2.0, 0.002
BAND_LO, BAND_HI = 0.2, 5.0
MIN_STORED_FOR_LABEL = 1  # one stored quarter is enough to CHOOSE a row; zero is not


def pick_label(code, sym, revop):
    """Score every candidate row against our stored quarters on BOTH bases; return the winner.

    Both bases feed one score because our storage convention (net sales vs total income) is a
    property of the COMPANY. A consolidated cell for a company with 2 stored standalone quarters and
    none consolidated is still row-decidable; without either it is not, and we refuse."""
    ours = {}
    for basis in ("std", "con"):
        slot = SLOT[basis]
        ours[basis] = {
            int(q): r[slot] for q, r in (revop.get(sym) or {}).items() if len(r) > slot and r[slot] is not None
        }
    total_stored = len(ours["std"]) + len(ours["con"])
    if total_stored < MIN_STORED_FOR_LABEL:
        return None, 0, 0, total_stored
    best, best_score, runner = None, -1, -1
    for label in REV_ROWS:
        score = 0
        for basis in ("std", "con"):
            if not ours[basis]:
                continue
            raw = MC.series_raw(code, basis, 400)
            ser = {}
            for row in raw:
                qe = MC.qe_of(row.get("yrc0"))
                v = MC.row_value(row, label)
                if qe and v is not None:
                    ser[qe] = v
            score += sum(
                1
                for qe, v in ours[basis].items()
                if qe in ser and abs(ser[qe] - v) <= max(MC.TOL_ABS, MC.TOL_REL * max(abs(v), abs(ser[qe])))
            )
        if score > best_score:
            best, runner, best_score = label, best_score, score
        elif score > runner:
            runner = score
    return best, best_score, runner, total_stored


def filing_conflict(sym, qe, ncf, ce):
    """§51a: our own filing evidence says no consolidated result existed for this quarter. Returns a
    reason string when writing would contradict that evidence, else None. This is a CONFLICT, not a
    verdict either way — the source and our ledger disagree and only a filing settles it."""
    e = ce.get(sym)

    def fy(q):
        y, m = q // 10000, (q // 100) % 100
        return y if m <= 3 else y + 1

    if sym in set(ncf["never_filed_con"]) or (e and e.get("files_con") is False):
        return (
            "§51a CONFLICT: our filing evidence records this company as never filing a "
            "consolidated result, yet Moneycontrol serves a consolidated table that reconciles "
            "against its own annual and differs from its own standalone. Both cannot be right; "
            "held until a filing settles it."
        )
    st = ncf["started_filing_con"].get(sym)
    if st and qe < st:
        return (
            "§51a CONFLICT: our filing index puts this company's first consolidated filing at "
            "%d, after this quarter." % st
        )
    sp = ncf["stopped_filing_con"].get(sym)
    if sp and qe >= sp:
        return (
            "§51a CONFLICT: our filing index has this company ceasing consolidated filings at "
            "%d, before this quarter." % sp
        )
    if e and e.get("first_con_fy") and fy(qe) < e["first_con_fy"]:
        return "§51a CONFLICT: measured first consolidated FY is %d, after this quarter." % e["first_con_fy"]
    return None


def band_ok(series, qe, v):
    near = sorted((q for q in series if q != qe), key=lambda q: abs(q - qe))[:6]
    vals = sorted(series[q] for q in near if series[q] > 0)
    if not vals:
        return True, None
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2.0
    if med <= 0:
        return True, None
    return (BAND_LO <= v / med <= BAND_HI), round(v / med, 3)


def members_by_quarter():
    snaps = sorted(json.load(open(IDXH))["Nifty 500"], key=lambda s: s["effectiveDate"])
    cache = {}

    def f(qe):
        if qe not in cache:
            ds = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
            best = None
            for s in snaps:
                if s["effectiveDate"] <= ds:
                    best = s
                else:
                    break
            cache[qe] = {x for x in best["symbols"] if not x.upper().startswith("DUMMY")} if best else set()
        return cache[qe]

    return f


def main():
    argv = sys.argv
    apply_it = "--apply" in argv
    members_only = "--members-only" in argv
    lim = int(argv[argv.index("--limit-pairs") + 1]) if "--limit-pairs" in argv else None

    revop = json.load(open(REVOP))
    ledger = json.load(open(LEDGER))
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    codes = json.load(open(MC.CODES)) if os.path.exists(MC.CODES) else {}
    ncf = json.load(open(os.path.join(SCRIPTS, "no_con_filing.json")))
    ce = json.load(open(os.path.join(SCRIPTS, "con_filer_evidence.json")))
    mem = members_by_quarter()

    work = []
    for sym, qmap in revop.items():
        for basis in ("std", "con"):
            slot = SLOT[basis]
            have = sum(1 for r in qmap.values() if len(r) > slot and r[slot] is not None)
            if have >= 6:
                continue  # the anchor gate owns these
            gaps = [int(q) for q, r in qmap.items() if len(r) > slot and r[slot] is None]
            if members_only:
                gaps = [q for q in gaps if sym in mem(q)]
            if gaps:
                work.append((sym, basis, sorted(gaps, reverse=True)))
    work.sort(key=lambda t: (-len(t[2]), t[0]))
    if lim:
        work = work[:lim]
    print(
        "ungateable-by-anchor pairs in scope: %d | open cells: %d" % (len(work), sum(len(g) for _, _, g in work)),
        flush=True,
    )

    read = 0
    for n, (sym, basis, gaps) in enumerate(work, 1):
        pre = sym in codes
        code = MC.resolve_code(sym, codes)
        if not pre:
            MC._jitter(0.4, 0.9)
        if not code:
            skips[f"{sym}|{basis}"] = "no verified moneycontrol code"
            continue
        label, score, runner, stored = pick_label(code, sym, revop)
        if label is None:
            skips[f"{sym}|{basis}"] = (
                "ROW UNDECIDABLE: company has 0 stored revenue quarters on "
                "either basis, so no anchor can choose between Net Sales and "
                "Total Income. Refused rather than defaulted (§85 SIEMENS)."
            )
            continue
        if score == 0:
            skips[f"{sym}|{basis}"] = (
                "ROW UNDECIDABLE: %d stored quarters but NO candidate row "
                "reproduces any of them — the series may not be this "
                "company. Refused." % stored
            )
            continue
        if score == runner:
            skips[f"{sym}|{basis}"] = (
                "ROW TIE at %d anchors between candidate rows — the anchors "
                "cannot tell the revenue definitions apart. Unresolved, not "
                "defaulted." % score
            )
            continue
        series = {}
        for row in MC.series_raw(code, basis, 400):
            qe = MC.qe_of(row.get("yrc0"))
            v = MC.row_value(row, label)
            if qe and v is not None:
                series[qe] = v
        if not series:
            skips[f"{sym}|{basis}"] = f"RETRYABLE empty {basis} series (run-time, not evidence)"
            continue
        ident = MA.fy_identity(code, basis, label, 400, TOL_REL_FY, TOL_ABS_FY)
        MC._jitter()
        if not ident:
            skips[f"{sym}|{basis}"] = (
                "no FY in MC's annual table is fully spanned by its own quarterly table — the identity cannot be run"
            )
            continue
        std_series = None
        got = 0
        for qe in gaps:
            key = "%s|%d|%s" % (sym, qe, basis)
            if key in fills or qe not in series:
                continue
            fy = [y for y, (ok, av, s, qs) in ident.items() if qe in qs]
            if not fy:
                skips[key] = "quarter falls in no FY the annual table covers"
                continue
            ok, av, s, _qs = ident[fy[0]]
            if not ok:
                skips[key] = (
                    "FY IDENTITY FAILS for FY%d: MC's own four quarters sum to %.2f against "
                    "its own annual %.2f (%.2f%% apart) — a restated year or a bad quarter, "
                    "either way not writable" % (fy[0], s, av, 100.0 * abs(s - av) / max(abs(av), 1e-9))
                )
                continue
            v = series[qe]
            if v <= 0:
                continue
            if basis == "con":
                conflict = filing_conflict(sym, qe, ncf, ce)
                if conflict:
                    skips[key] = conflict
                    continue
                if std_series is None:
                    std_series = {}
                    for row in MC.series_raw(code, "std", 400):
                        q2 = MC.qe_of(row.get("yrc0"))
                        v2 = MC.row_value(row, label)
                        if q2 and v2 is not None:
                            std_series[q2] = v2
                    MC._jitter()
                twin = std_series.get(qe)
                if twin is not None and abs(v - twin) <= 0.005:
                    skips[key] = (
                        "§85: MC's consolidated equals MC's OWN standalone to the cent for this "
                        "quarter — indistinguishable from the aggregator repeating standalone. "
                        "UNRESOLVED, not written."
                    )
                    continue
            bok, ratio = band_ok(series, qe, v)
            if not bok:
                skips[key] = f"§83 band: {v:.2f} is {ratio}x the nearest-6 median of MC's own series"
                continue
            fills[key] = {
                "rev": round(v, 2),
                "row_label": label,
                "sc_id": code,
                "type_format": MC.FMT[basis],
                "neighbour_ratio": ratio,
                "gate": (
                    "SOURCE FY IDENTITY: MC's own four quarters of FY%d sum to %.2f "
                    "against its own annual %.2f. Row chosen by reproduction: %d "
                    "anchors vs %d for the runner-up, across %d stored quarters."
                    % (fy[0], s, av, score, max(runner, 0), stored)
                ),
                "src": "moneycontrol quarterly_results_responsive + yearly_results_responsive",
            }
            read += 1
            got += 1
        if got:
            print("%-13s %-3s +%-3d cells (%s, FY-identity)" % (sym, basis, got, label), flush=True)
        if n % 20 == 0:
            json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
            print("  [%d/%d pairs] %d cells read" % (n, len(work), read), flush=True)

    json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    json.dump(codes, open(MC.CODES, "w"), indent=1, sort_keys=True)
    print("\nREAD %d cells (%d ledgered)" % (read, len(fills)))
    if not apply_it:
        print("(dry run — ledgers written, data files untouched. Re-run with --apply)")
        return

    applied = 0
    for key, v in sorted(fills.items()):
        if v.get("held"):
            continue
        sym, qe_s, basis = key.split("|")
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None or len(row) <= SLOT[basis] or row[SLOT[basis]] is not None:
            continue
        row[SLOT[basis]] = v["rev"]
        applied += 1
        lr = ledger.setdefault(sym, {}).get(qe_s)
        if lr is None:
            ledger[sym][qe_s] = list(row)
        elif len(lr) > SLOT[basis] and lr[SLOT[basis]] is None:
            lr[SLOT[basis]] = v["rev"]
    json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
    json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
    print("APPLIED %d cells" % applied)


if __name__ == "__main__":
    main()

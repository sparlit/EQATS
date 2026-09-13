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
"""Apply gated aggregator STANDALONE-PAT fills into docs/sf_fundamentals.json.

apply_agg_fills.py writes sf_revop (revS/revC slots 0/1) and refuses anything else; patS lives in
a different file with a different row shape, so it gets its own applier rather than a flag.

  row shape   [qEnd, npStd, annStd, npCon, annCon]   (build_fundamentals.py:14)
  we write    slot 1 only, and slot 2 when we create the row

WHY ROWS MAY BE CREATED HERE, when apply_agg_fills.py refuses to create them: in sf_revop a missing
row means the quarter is outside the dataset's frame. In sf_fundamentals the pre-2015 era IS the
frame -- 21,788 of its rows are pre-2015 and the twin scripts/fundamentals.json holds only 968 of
them, because that era was assembled by backfill campaigns, one appended row at a time
(scripts/apply_early_backfill.py is the same shape). A 2004 quarter with no row is a hole, not an
out-of-frame quarter.

⚠️ THE ANN-DATE SLOT IS A CONVENTION, NOT A MEASUREMENT. Moneycontrol's quarterly feed carries no
filing date. docs/backtest-engine.js:530 selects a quarter with `q[annIdx] <= dateInt`, so:
    ann = 0     -> "available since the epoch"  -> a look-ahead in every backtest
    ann = None  -> the cell is invisible to the engine, unlike its neighbours
    ann = qe+45d-> what this era's rows already say: MEASURED 2026-08-12, 20,818 of the 21,515
                   dated pre-2015 cells sit at exactly quarter-end + 45 days (runbook §52 records
                   the same default from the other side: "stored announce dates for old quarters
                   are not filing dates ... a quarter-end+45d default").
So qe+45d it is, and every ledger entry says `ann_basis: convention` in as many words. It is an
availability convention inherited from the surrounding rows, and no one should ever read it as the
date the company filed.

⚠️⚠️ AND FOR A PRE-LISTING QUARTER THAT CONVENTION FABRICATES AN EARLY DATE (added 2026-08-13,
runbook §99). Aggregators carry quarters from BEFORE a company listed or demerged -- restated
comparatives out of the prospectus or the demerger scheme -- and qe+45d then claims the number was
public months before the company had a tape. Measured on this repo's own ledger: SBICARD's Mar-2019
quarter was written with ann 2019-05-15 against a first traded bar of 2020-03-16, ten months early.
It is the §91c defect wearing a different date.

    ann = max(qe + 45d, the symbol's FIRST TRADED BAR)   <- agg_tools/_first_bar.json

Both directions of that floor are safe. It cannot CREATE a look-ahead: for an IPO the prospectus is
public before listing and for a demerger the scheme is public before the record date, so the true
public date is at or before the first bar. It cannot HIDE a cell from a date that mattered either:
nothing can screen, hold or price a stock before its first bar, so no earlier ann date is reachable
by any backtest. Where the floor binds, the ledger says so per cell (`ann_floor`), and the value is
still a convention -- a floor makes it defensible, not measured.

Safety, per §72 / the shape of scripts/_stdpat_apply.py:
  * FILL-ONLY -- a non-null npStd is never overwritten, only reported;
  * blast radius -- the patched file is diffed against the original and the run aborts unless the
    only differences are the intended cells;
  * idempotent -- a second run writes 0 (memory: feedback-a-heal-that-reapplies);
  * journal -- scripts/agg_pat_cell_fills.json, keyed SYM|QE (TWO parts: verify_fills_live.py
    rsplits a ledger key once, so a three-part key makes it read the field as the quarter and
    check nothing), registered in that script's LEDGERS at creation time.

  python3 -X utf8 scripts/agg_tools/apply_agg_pat_fills.py --props /tmp/final.json          # dry
  python3 -X utf8 scripts/agg_tools/apply_agg_pat_fills.py --props /tmp/final.json --apply
"""
import argparse
import copy
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "agg_pat_cell_fills.json")
FIRST_BAR = os.path.join(HERE, "_first_bar.json")
SITE_NAME = {"mc": "moneycontrol", "tl": "trendlyne", "tt": "tickertape"}
SLOT = {"patS": 1, "patC": 3}
BASIS_KEY = {"patS": "std", "patC": "con"}  # the key verify_fills_live.py LEDGERS registers
ANN_SLOT = {"patS": 2, "patC": 4}
ANN_BASIS = (
    "CONVENTION, not a filing date: quarter-end+45d, the default 20,818 of the 21,515 "
    "dated pre-2015 cells already carry (runbook §52), FLOORED at the symbol's first "
    "traded bar so a pre-listing quarter cannot claim it was public before the company "
    "had a tape (§99). Moneycontrol's feed carries no filing date."
)


def ann_default(qe):
    """quarter-end + 45 days, the convention this era's rows already carry (see module docstring)."""
    d = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100) + datetime.timedelta(days=45)
    return d.year * 10000 + d.month * 100 + d.day


def load_first_bar(path):
    """{SYM: first-traded-bar as YYYYMMDD int}. Regenerate: node scripts/build_first_bar_map.js."""
    d = json.load(open(path))["first_bar"]
    return {s: int(v.replace("-", "")) for s, v in d.items()}


def ann_for(qe, sym, first_bar, seam_syms=()):
    """-> (ann, floored_from or None). See the module docstring: max(qe+45d, first traded bar).

    A symbol with NO entry in the map has no tape at all in the bin -- nothing can select it at any
    date, so the floor has nothing to protect and qe+45d stands. That case is counted and printed,
    never silent: an absent symbol must look different from a floor that did not bind.

    `seam_syms` is the --seam-syms escape, and it is the WRITE-side twin of the warning already on
    --repair-syms: a first bar is not always a listing date. BBOX (2010-06-08 in this bin) is the
    named example there, and it is provable rather than assumed -- sf_fundamentals already stores
    BBOX 2002-12 and 2003-03 with REAL announce dates 2003-01-09 / 2003-05-21, so the company was
    public and filing seven years before its first bar here; the 2010 date is a rename/tape seam
    (_rename_map AGCNET->BBOX, FUND_ALIAS AVAYAGCL/TATATELECM->BBOX). Flooring there would push a
    2003 quarter's availability to 2010, i.e. HIDE a cell whose siblings are visible in 2003.
    ⚠️ Only list a symbol here when you have READ that evidence for it. The default stays the floor.
    """
    base = ann_default(qe)
    if sym in seam_syms:
        return base, "SEAM"
    fb = first_bar.get(sym)
    if fb is None:
        return base, "NO-TAPE"
    return (fb, base) if fb > base else (base, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--props", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--first-bar", default=FIRST_BAR)
    ap.add_argument(
        "--repair-ann",
        action="store_true",
        help="also re-floor ann dates ALREADY WRITTEN by this ledger that precede the "
        "symbol's first traded bar (the cells written before the floor existed)",
    )
    ap.add_argument(
        "--repair-syms",
        help="comma-separated symbols the repair may touch. ⚠️ USE IT. A first bar is "
        "not always a listing date: KIRLOSBROS first trades 2010-04-20 in this "
        "bin and BBOX 2010-06-08, and both companies were listed years earlier -- "
        "those are a tape/rename seam (§93/§95 shape), NOT a pre-listing quarter. "
        "Flooring there would move a probably-correct filing date to a wrong one, "
        "and under a rename the old symbol's row can still reach the quarter "
        "through FUND_ALIAS, so it could even hide data. Repair the symbols whose "
        "listing you have checked; report the rest (§58d), never patch in passing.",
    )
    ap.add_argument("--stamp", default=time.strftime("%Y-%m-%d"))
    # ⚠️ THE JOURNAL MUST SAY WHICH CAMPAIGN WROTE THE CELL. The default below is this script's
    # first caller (the pre-2015 sweep) and is kept so old ledger entries stay reproducible; any
    # other campaign passes its own, because "aggregator pre-2015 std-PAT sweep" stamped on a 2019
    # cell is provenance that misdirects the next reader (memory: provenance-every-backfill).
    ap.add_argument("--label", default="aggregator pre-2015 std-PAT sweep")
    ap.add_argument(
        "--seam-syms",
        help="comma-separated symbols whose FIRST BAR is a proven tape/rename seam "
        "rather than a listing date -- the §99 floor is skipped for them and "
        "qe+45d stands. Read ann_for()'s docstring before adding one: it needs "
        "evidence (older stored rows with REAL announce dates, or a rename map "
        "entry), never a hunch.",
    )
    # ⚠️ THE GATE'S CALIBRATION BASE BELONGS IN THE LEDGER, NOT ONLY IN THE COMMIT MESSAGE.
    # A commit message is invisible to the next sweep; the ledger is what the next sweep reads.
    # GATE E2b was calibrated by hold-out against cells we ALREADY store, so its measured error
    # rate is only meaningful where such cells exist: the store holds 120 rows in 2001 and NONE
    # before, so a 2000-2001 fill is running an UNCALIBRATED gate and must say so per cell.
    # Same for a thin-anchor symbol inside a calibrated era.
    ap.add_argument(
        "--new-symbols",
        action="store_true",
        help="permit CREATING a symbol key that sf_fundamentals does not have. OFF by "
        "default and it must stay that way: refusing is what keeps a typo'd or "
        "HTML-escaped phantom ticker out of the store (project-stocks-phantom-"
        "escaped-symbols). Pass it only for a batch whose symbols you have "
        "VERIFIED are real -- present in a point-in-time index roll, carrying a "
        "first traded bar, and with the source document naming the company. The "
        "run prints every symbol it creates so the claim is auditable.",
    )
    ap.add_argument("--gate", help="the gate name to journal per cell, e.g. 'E2b'.")
    ap.add_argument(
        "--calibration",
        help="one sentence naming the hold-out this gate's setting was calibrated on "
        "(population, era, measured mismatch) -- or the word 'none' when there is "
        "no ground truth to calibrate against in the era being filled.",
    )
    a = ap.parse_args()

    props = json.load(open(a.props))["proposals"]
    orig = json.load(open(FUND))
    work = copy.deepcopy(orig)
    first_bar = load_first_bar(a.first_bar)
    seam_syms = set(a.seam_syms.split(",")) if a.seam_syms else set()

    journal, skipped, created, filled = {}, [], 0, 0
    created_syms = set()
    floored, no_tape, repaired, out_of_scope, seamed = [], [], [], [], []
    touched = set()  # (sym, qe) we intend to change

    for key in sorted(props):
        sym, qe, field = key.split("|")
        qe = int(qe)
        if field not in SLOT:
            skipped.append(f"{key}: {field} is not an sf_fundamentals field")
            continue
        p = props[key]
        arr = work.get(sym)
        if arr is None and a.new_symbols:
            arr = work[sym] = []
            created_syms.add(sym)
        if arr is None:
            skipped.append(
                f"{key}: symbol absent from sf_fundamentals (pass --new-symbols only for VERIFIED-real symbols)"
            )
            continue
        i, ai = SLOT[field], ANN_SLOT[field]
        row = next((r for r in arr if r and r[0] == qe), None)
        if row is None:
            row = [qe, None, None, None, None]
            arr.append(row)
            arr.sort(key=lambda r: r[0])
            created += 1
        while len(row) < 5:
            row.append(None)
        if row[i] is not None:
            skipped.append(f"{key}: already = {row[i]}")
            continue
        row[i] = p["value"]
        ann, floor_from = ann_for(qe, sym, first_bar, seam_syms)
        # A proposal may carry a REAL public date (`ann`, YYYYMMDD int) -- e.g. the BSE announcement index's
        # NEWS_DT, the exchange's own dissemination timestamp of the result summary (runbook §129). It
        # replaces the qe+45d convention but is still floored at the first traded bar (§99): a real date
        # cannot precede the tape either. The ledger says which basis was written per cell.
        real_ann = p.get("ann")
        if isinstance(real_ann, int) and real_ann > 19900101:
            fb = first_bar.get(sym)
            if fb and sym not in seam_syms and fb > real_ann:
                ann, floor_from = fb, real_ann
            else:
                ann, floor_from = real_ann, None
        if row[ai] in (None, 0):
            row[ai] = ann
            if floor_from == "NO-TAPE":
                no_tape.append("%s %d" % (sym, qe))
            elif floor_from == "SEAM":
                seamed.append("%s %d: floor SKIPPED (declared tape seam), qe+45d = %d" % (sym, qe, ann))
            elif floor_from:
                floored.append("%s %d: %d -> %d (first bar)" % (sym, qe, floor_from, ann))
        filled += 1
        touched.add((sym, qe))

        # `chosen` is the aggregator gate's shape. A non-aggregator gate (e.g. the archived-exchange
        # reader in scripts/wayback_nse/) has no site/row/precision in that form, and inventing one
        # would put a Moneycontrol provenance string on a page that never came from Moneycontrol --
        # the same wrong-source-named defect the `evidence` fallback below was just fixed for.
        # So `chosen` is optional, and `src` is overridable by the proposal.
        ch = p.get("chosen") or {}
        jkey = "%s|%d" % (sym, qe)
        journal.setdefault(jkey, {})
        journal[jkey].update(
            {
                # ⚠️ THE VALUE KEY IS THE BASIS NAME, "std"/"con" -- NOT the field name. verify_fills_live
                # skips any entry where its registered key is absent (`key not in v: continue`), so a
                # ledger written under "patS" against a registration of "std" is checked ZERO times and
                # still reports MISSING 0. Caught here only because `checked` did not move when the
                # ledger grew by 309 entries. Same class as the three-part-key trap noted below.
                BASIS_KEY[field]: p["value"],
                "state": p["state"],
                "precision": ch.get("precision"),
                "src": p.get("src")
                or (
                    "{} quarterly-results API (runbook §81)".format(SITE_NAME.get(ch["site"], ch["site"]))
                    if ch.get("site")
                    else "unnamed source (proposal carried no src)"
                ),
                "row_label": ch.get("row"),
                "resolved_via": p.get("resolved_via", "symbol"),
                "ann_written": row[ai],
                "ann_basis": (
                    p.get("ann_basis")
                    or "REAL public date supplied by the proposal (see src), floored at the first traded bar (§99)"
                )
                if isinstance(p.get("ann"), int)
                else ANN_BASIS,
                "ann_floor": (
                    "qe+45d was %d, FLOORED UP to the first traded bar %d -- a pre-listing "
                    "quarter (§99)" % (floor_from, row[ai])
                )
                if isinstance(floor_from, int)
                else (
                    "no tape for this symbol in sf_stock_data.bin, so qe+45d stands unfloored"
                    if floor_from == "NO-TAPE"
                    else (
                        "first bar declared a TAPE SEAM (--seam-syms), not a listing date, "
                        "so the §99 floor is not applied and qe+45d stands"
                        if floor_from == "SEAM"
                        else None
                    )
                ),
                # A proposal may carry its OWN evidence sentence, and it SHOULD -- only the gate knows
                # which gate it ran. The old fallback here asserted "gate A/A2 passed" unconditionally,
                # and its own comment described that as a known limitation instead of fixing it, so
                # every GATE-E and GATE-E2b cell was journalled as a gate-A pass that never ran
                # (191 of this campaign's own cells among them, corrected 2026-08-26 from the
                # DECISION-TIME proposals, never from a re-run -- a re-run anchors against the cells
                # the batch itself wrote and reports stronger evidence than the decision had).
                # ★ A comment that explains a wrong output is the defect's alibi, not its documentation.
                # The fallback now claims only what it can see: a proposal carrying `fy_check` came
                # from an FY-identity gate, not from gate A, and an unnamed gate says so.
                "evidence": p.get("evidence")
                or (
                    "gate %s: that site's own %s series reproduces %d of our stored quarters, "
                    "worst anchor error %.4f. ⚠️ The GATE NAME was not supplied by the "
                    "proposal, so this entry records what the applier could verify and no "
                    "more -- re-derive it from the run that decided the cell if you need it."
                    % (
                        "with an FY-identity check (A5/E2-family)" if p.get("fy_check") else "UNNAMED",
                        field,
                        ch["anchors"],
                        ch["worst_anchor"],
                    )
                ),
                "field": field,
                "corroborated_by": [SITE_NAME.get(s, s) for s in p.get("corroborated_by", [])],
                "site_reach": p.get("sites", {}),
                "fy_check": p.get("fy_check"),
                "applied": f"{a.stamp} {a.label}",
            }
        )
        if a.gate:
            journal[jkey]["gate"] = a.gate
        if a.calibration:
            journal[jkey]["calibration"] = a.calibration

    # ---- REPAIR: ann dates this ledger wrote BEFORE the floor existed (§99)
    # Scoped three ways, because raising a date is still a write into a shared file:
    #   * only cells this ledger's own journal claims;
    #   * only where the stored date still EQUALS what the ledger wrote (a `was` guard -- if
    #     anything else has re-dated the cell since, that owner is not me and I leave it alone);
    #   * only upward, and only to the first bar.
    if a.repair_ann and os.path.exists(LEDGER):
        led0 = json.load(open(LEDGER))
        fmap = {s: {r[0]: r for r in rows} for s, rows in work.items()}
        only = set(a.repair_syms.split(",")) if a.repair_syms else None
        for jkey in sorted(led0):
            if jkey.count("|") != 1:
                continue
            sym, qes = jkey.split("|")
            v = led0[jkey]
            if not isinstance(v, dict):
                continue
            fld, was = v.get("field"), v.get("ann_written")
            if fld not in ANN_SLOT or not was:
                continue
            fb = first_bar.get(sym)
            if fb is None or fb <= was:
                continue
            if only is not None and sym not in only:
                out_of_scope.append(
                    "%s %s %s: ann %d precedes first bar %d — NOT repaired, "
                    "symbol out of scope" % (sym, qes, fld, was, fb)
                )
                continue
            row = fmap.get(sym, {}).get(int(qes))
            ai = ANN_SLOT[fld]
            if not row or len(row) <= ai or row[ai] != was:
                skipped.append(
                    f"{jkey}: ann repair skipped, stored {row[ai] if row and len(row) > ai else None} != ledger {was}"
                )
                continue
            row[ai] = fb
            touched.add((sym, int(qes)))
            repaired.append("%s %s %s: %d -> %d (first bar)" % (sym, qes, fld, was, fb))
            journal.setdefault(jkey, dict(v))
            journal[jkey].update(
                {
                    "ann_written": fb,
                    "ann_basis": ANN_BASIS,
                    "ann_floor": (
                        "qe+45d was %d and PRECEDED the first traded bar %d -- re-floored "
                        "%s, the cell was written before the floor existed (§99)" % (was, fb, a.stamp)
                    ),
                }
            )

    # ---- BLAST RADIUS: nothing may differ except the cells we meant to touch
    diffs = []
    for sym in set(list(orig) + list(work)):
        o = {r[0]: r for r in orig.get(sym, [])}
        w = {r[0]: r for r in work.get(sym, [])}
        for qe in set(list(o) + list(w)):
            if o.get(qe) != w.get(qe) and (sym, qe) not in touched:
                diffs.append(f"{sym} {qe}: {o.get(qe)} -> {w.get(qe)}")
    if diffs:
        print("ABORT -- %d unintended changes, e.g.:" % len(diffs))
        for d in diffs[:10]:
            print("   " + d)
        return 2

    print(
        "%-32s %s %d cells (%d new rows created)"
        % ("docs/sf_fundamentals.json", "filled" if a.apply else "would fill", filled, created)
    )
    print("  ann floored to the first traded bar: %d" % len(floored))
    if created_syms:
        # printed ALWAYS, never summarised away: creating a symbol key is the one write here that
        # a typo cannot be walked back from, so the claim "these are verified real" must be visible.
        print("  ⚠️ SYMBOL KEYS CREATED (--new-symbols): %d — %s" % (len(created_syms), ", ".join(sorted(created_syms))))
    for s in floored:
        print(f"      {s}")
    if no_tape:
        print("  ⚠️ no tape in the bin, qe+45d unfloored: %d — %s" % (len(no_tape), no_tape[:8]))
    if seamed:
        print("  floor SKIPPED on declared tape seams (--seam-syms): %d" % len(seamed))
        for s in seamed:
            print(f"      {s}")
    if a.repair_ann:
        print("  ann REPAIRS (written before the floor existed): %d" % len(repaired))
        for s in repaired:
            print(f"      {s}")
        if out_of_scope:
            print("  ⚠️ FOUND BUT NOT REPAIRED (out of --repair-syms), reported per §58d: %d" % len(out_of_scope))
            for s in out_of_scope:
                print(f"      {s}")
    for s in skipped[:30]:
        print(f"  skip: {s}")
    if len(skipped) > 30:
        print("  ... %d more skips" % (len(skipped) - 30))

    if a.apply and (filled or repaired):
        tmp = FUND + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(work, fh, separators=(",", ":"))
        os.replace(tmp, FUND)
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(journal)
        with open(LEDGER, "w", encoding="utf-8") as fh:
            json.dump(led, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print("journalled %d cells -> %s" % (len(journal), os.path.basename(LEDGER)))
    elif not a.apply:
        print("DRY RUN -- nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

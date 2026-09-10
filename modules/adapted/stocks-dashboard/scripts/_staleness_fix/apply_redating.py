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


#!/usr/bin/env python3
"""Apply the staleness campaign's fetched real dates to the fundamentals ann-date cells
(DATA_RUNBOOK §102/§103, PLAN_QUANTMAC_FIXES.md P2). Same dry-run-by-default convention as
scripts/gate_1530.py, which this deliberately mirrors — including running each matched cell
through the SAME 15:30 IST rule before writing, so the nightly gate finds nothing left to do.

For each cell in target_list.json with a match in fetch_results.json:
  1. Parse the real NEWS_DT -> a raw YYYYMMDD date + time-of-day.
  2. If broadcast time > 15:30 IST: bump to the next trading day (scripts/gate_calendar.json
     tdays) — same rule, same source of truth as gate_1530.py. Otherwise use the raw date.
  3. Skip (no-op) if the result equals what's already stored.
  4. Record direction (earlier/later) and day-delta vs the qe+45d placeholder being replaced —
     the campaign found this error runs BOTH ways (DATA_RUNBOOK §102, finding 3 note), so both
     get corrected the same way: write the truth.

Never invents a date: a cell with no fetch match is left untouched, exactly as stored.

Writes BOTH docs/sf_fundamentals.json and scripts/fundamentals.json (gate_1530.py precedent —
CI commits only the former; a local apply keeps the mirror in step) — dry run by default.
Also updates scripts/agg_pat_cell_fills.json entries whose ann_written equals the value being
replaced (2,046 of them per the plan's B4.1 measurement), so a future --repair-ann run doesn't
stamp the placeholder back (the retraction-needs-every-ledger class).

Usage:  python3 apply_redating.py              # dry run -> redate_ledger.json (audit, no writes)
        python3 apply_redating.py --apply      # also rewrite both fundamentals files + the ledger
"""
import bisect
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import classify_row, is_year_ago_comparative  # THE shared rules (PLAN F1)

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
DOCS = os.path.join(SCRIPTS, "..", "docs")
CUTOFF_MIN = 15 * 60 + 30  # 15:30 IST, same constant as gate_1530.py


def load(p):
    return json.load(open(p))


def news_min(ts):
    """Minutes-after-midnight from a BSE NEWS_DT like '2020-10-30T17:08:23.81'."""
    try:
        t = ts.split("T")[1]
        h, m = int(t[0:2]), int(t[3:5])
        return h * 60 + m
    except Exception:
        return None


def news_date(ts):
    try:
        return int(ts.split("T")[0].replace("-", ""))
    except Exception:
        return None


def month_idx(d):
    return (d // 10000) * 12 + (d // 100) % 100


def days_between(a, b):
    """Rough calendar-day delta between two YYYYMMDD ints, exact via datetime."""
    da = datetime.date(a // 10000, (a // 100) % 100, a % 100)
    db = datetime.date(b // 10000, (b // 100) % 100, b % 100)
    return (db - da).days


# A real filing can never predate its own quarter-end. The UPPER bound is subtler than v1's flat
# 120 days (PLAN_QUANTMAC_FIXES.md §G, which overturned §F2's proposed flat 400):
#
#  * What the cap was really catching is the YEAR-AGO COMPARATIVE — proven live on CESC, whose
#    four 2003 quarters each matched a 2004 filing ~394 days late because the headline reads
#    "…for the quarter ended June 30, 2004 as compared to …quarter ended June 30, 2003". That is
#    now caught precisely by classify.is_year_ago_comparative() using the row's OTHER dates, so a
#    blunt lag cap no longer has to stand in for it.
#  * But genuine LATE filings exist and a flat 120 discards them — proven live on BHARATRAS
#    qe 2016-09-30, broadcast 2017-03-10 (lag 161d), a single-date real disclosure.
#
# So: [0, 200] normally; beyond that only when the row mentions NOTHING but this quarter (there was
# no other date to confuse it with). lag < 0 refused always — a filing cannot predate its quarter.
QE_LAG_MIN_DAYS = 0
QE_LAG_MAX_DAYS = 200
QE_LAG_ABSOLUTE_MAX = 400


def build_decisions(target_list, fetch_results, tdays):
    """-> list of decision dicts, one per matched cell that resolves to a real date."""
    decisions = []
    reasons = {
        "matched": 0,
        "no_match": 0,
        "unparseable_news_dt": 0,
        "no_next_td": 0,
        "noop": 0,
        "rejected_implausible_lag": 0,
        "refused_intimation": 0,
        "refused_year_ago_comparative": 0,
        "written_from_secondary": 0,
    }

    def next_td(d):
        i = bisect.bisect_right(tdays, d)
        return tdays[i] if i < len(tdays) else None

    for sym, rows in target_list.items():
        entry = fetch_results.get(sym)
        if not entry:
            reasons["no_match"] += len(rows)
            continue
        matches = entry.get("matches", {})
        for qe, basis, old_ann in rows:
            key = f"{qe}|{basis}"
            m = matches.get(key)
            if not m:
                reasons["no_match"] += 1
                continue
            # v3 stores [news_dt, newssub, cls, dates_in_row]; v2 stored just [news_dt, newssub].
            news_dt, newssub = m[0], m[1]
            cls = m[2] if len(m) > 2 else classify_row(newssub or "")
            row_dates_ = set(m[3]) if len(m) > 3 else set()

            # ── HARD REFUSAL 1: a board-meeting notice PRECEDES the results it announces, so
            # writing one manufactures look-ahead — the exact defect quantmac caught (PAGEIND
            # would have been stamped ~3 weeks early). Keep the safe qe+45d placeholder instead.
            if cls == "intimation":
                reasons["refused_intimation"] += 1
                continue

            # ── HARD REFUSAL 2: this quarter is only a YEAR-AGO COMPARISON inside a row whose
            # real subject is a later quarter (CESC 2003 → a 2004 filing, ~394d off).
            if row_dates_ and is_year_ago_comparative(qe, row_dates_):
                reasons["refused_year_ago_comparative"] += 1
                continue

            raw_date = news_date(news_dt)
            mins = news_min(news_dt)
            if raw_date is None:
                reasons["unparseable_news_dt"] += 1
                continue
            lag = days_between(qe, raw_date)
            if lag < QE_LAG_MIN_DAYS:
                reasons["rejected_implausible_lag"] += 1
                continue
            if lag > QE_LAG_MAX_DAYS:
                # Past 200d, accept only a row that mentions this quarter and nothing else —
                # there was no other date it could have been confused with (BHARATRAS class).
                if not (row_dates_ == {qe} and lag <= QE_LAG_ABSOLUTE_MAX):
                    reasons["rejected_implausible_lag"] += 1
                    continue
            # NB a 'secondary' (Reg-47 newspaper re-publication, measured 472/501 LATER than the
            # filing) is still a better bound than a formulaic qe+45d, so it is written — tagged,
            # and only ever because nothing of class 'result' dated this quarter. Counted from the
            # final decision list, not here, so no-ops below don't inflate it.
            if mins is not None and mins > CUTOFF_MIN:
                new_ann = next_td(raw_date)
                gated = True
                if new_ann is None:
                    reasons["no_next_td"] += 1
                    continue
            else:
                new_ann = raw_date
                gated = False
            if new_ann == old_ann:
                reasons["noop"] += 1
                continue
            reasons["matched"] += 1
            delta_days = days_between(old_ann, new_ann)
            decisions.append(
                {
                    "sym": sym,
                    "qe": qe,
                    "basis": basis,
                    "old_ann": old_ann,
                    "new_ann": new_ann,
                    "direction": "later" if delta_days > 0 else "earlier",
                    "delta_days": abs(delta_days),
                    "gated_1530": gated,
                    "news_dt": news_dt,
                    "newssub": newssub,
                    "cls": cls,
                }
            )
    return decisions, reasons


def main():
    apply = "--apply" in sys.argv
    target_list = load(os.path.join(HERE, "target_list.json"))
    fetch_results = load(os.path.join(HERE, "fetch_results.json"))
    tdays = load(os.path.join(SCRIPTS, "gate_calendar.json"))["tdays"]

    decisions, reasons = build_decisions(target_list, fetch_results, tdays)

    print("=== decision summary ===")
    for k, v in reasons.items():
        print(f"  {k:22s} {v}")
    print(f"  cells to re-date       {len(decisions)}")
    by_dir = {"earlier": 0, "later": 0}
    for d in decisions:
        by_dir[d["direction"]] += 1
    print(f"  direction split        earlier={by_dir['earlier']} later={by_dir['later']}")
    gated_n = sum(1 for d in decisions if d["gated_1530"])
    print(f"  15:30-gated on write   {gated_n}")
    sec_n = sum(1 for d in decisions if d.get("cls") == "secondary")
    print(f"  sourced from SECONDARY {sec_n}  (newspaper re-publication — a bound, not the filing)")
    big = sorted(
        (d for d in decisions if days_between(d["qe"], d["new_ann"]) > QE_LAG_MAX_DAYS),
        key=lambda d: -days_between(d["qe"], d["new_ann"]),
    )
    print(f"  accepted lag >{QE_LAG_MAX_DAYS}d      {len(big)}  (single-date rows only — eyeball these)")
    for d in big[:10]:
        print(
            f"      {d['sym']:12s} qe={d['qe']} lag={days_between(d['qe'], d['new_ann'])}d  {(d['newssub'] or '')[:70]}"
        )

    json.dump(decisions, open(os.path.join(HERE, "redate_ledger.json"), "w"), indent=1)
    print(f"\naudit ledger written -> redate_ledger.json ({len(decisions)} entries)")

    if not apply:
        print("\n(dry run — pass --apply to rewrite both fundamentals files + the agg ledger)")
        return

    by_sym_qe = {}
    for d in decisions:
        by_sym_qe.setdefault((d["sym"], d["qe"]), {})[d["basis"]] = d["new_ann"]

    for path in (os.path.join(DOCS, "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json")):
        fund = load(path)
        cnt = 0
        for sym, rows in fund.items():
            for r in rows:
                qe = r[0]
                bmap = by_sym_qe.get((sym, qe))
                if not bmap:
                    continue
                if "std" in bmap and len(r) > 2 and r[2] is not None:
                    r[2] = bmap["std"]
                    cnt += 1
                if "con" in bmap and len(r) > 4 and r[4] is not None:
                    r[4] = bmap["con"]
                    cnt += 1
        json.dump(fund, open(path, "w"), separators=(",", ":"))
        print(f"applied {cnt} cell writes -> {os.path.relpath(path, SCRIPTS)}")

    agg_path = os.path.join(SCRIPTS, "agg_pat_cell_fills.json")
    agg = load(agg_path)
    agg_updated = 0
    for d in decisions:
        lkey = f"{d['sym']}|{d['qe']}"
        if lkey in agg and agg[lkey].get("ann_written") == d["old_ann"]:
            agg[lkey]["ann_written"] = d["new_ann"]
            agg[lkey]["ann_basis"] = (
                f"bse-broadcast {d['news_dt']} [{d.get('cls', 'result')}] "
                f"(staleness campaign 2026-08-20 v3, was CONVENTION quarter-end+45d)"
            )
            agg_updated += 1
    if agg_updated:
        json.dump(agg, open(agg_path, "w"), indent=1)
    print(f"synced {agg_updated} entries in agg_pat_cell_fills.json (of {len(decisions)} decisions)")
    print("DONE.")


if __name__ == "__main__":
    main()

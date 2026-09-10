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
"""FILL-2020: bulk no-sub consolidated-PAT derivation (con = std, SEBI LODR Reg-33 identity).

Scope: the pre-FY2020 consolidated-PAT hole. Quarterly consolidated results only became
compulsory in India from FY2020, so ~3.1k con cells before Apr-2019 were never filed. For a
company with NO consolidatable subsidiary, consolidated == standalone by identity, and that is
already how this dataset stores such companies (see apply_nosub_constd{,2}.py).

THE PROOF RULE (campaign FILL2020_CAMPAIGN.md Phase 2 / runbook §6-A). A cell is filled only if
ALL hold:
  1. std PAT exists for that cell (there is something to copy) and con is currently None.
  2. The company's con series OPENS with an unbroken run of >= MIN_IDENT identity quarters.
     The run must START the series: evidence has to sit adjacent to the gap, not anywhere in
     history. BAJAJELEC is why -- its very first stored con quarter (Jun-2019) already diverges
     17.40 vs 14.43, so it plainly had subsidiaries during its 2015-19 gap, yet it owns 6
     identity quarters years later and a naive ">=6 anywhere" test would have fabricated 17 cells.
     One coincidental match is likewise not proof -- IOB has exactly 1 identity quarter against
     17 divergent and is a real consolidator.
  3. The gap quarter is STRICTLY EARLIER than the company's first divergent quarter. Once a
     subsidiary appears it does not un-appear, so identity is only defensible before that date.
     (Companies that never diverge have no such bound.)
  4. Not on the EXCLUDE list below.

DIVERGENCE IS MATERIAL, NOT EXACT. A paisa-level delta is a rounding artifact, not a subsidiary:
MOIL prints con 113.45 against std 113.44 in Jun-2018 (immaterial) and 139.63 against 135.09 in
Mar-2019 (real). Exact-equality would have mis-dated MOIL's first divergence by three quarters.
Threshold: max(ABS_TOL, REL_TOL * |std|).

Everything failing the rule is left NULL and reported -- a never-filed quarter is done when it is
documented, not when it is fabricated.

EXCLUDE: KTKBANK and SOUTHBANK are held null by explicit user decision (2026-08-06) -- a bank's
consolidated can differ for reasons a plain identity papers over. They would otherwise pass rule 2
only marginally (6 and 5 identity quarters).

Fill-only: never overwrites a non-null con. Writes docs/sf_fundamentals.json +
scripts/fundamentals.json, journals every cell to scripts/nosub_pat_fills.json (tracked).

Run:  python -X utf8 scripts/fill2020_tools/derive_nosub_pat_bulk.py [--apply]
      (default is a DRY RUN with a full report; --apply writes.)
"""
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(ROOT, "scripts", "fundamentals.json")
QR = os.path.join(ROOT, "docs", "quarterly_results.json")
LEDGER = os.path.join(ROOT, "scripts", "nosub_pat_fills.json")
IDX = os.path.join(ROOT, "scripts", "indices_history.json")
RENAME = os.path.join(ROOT, "scripts", "_rename_map.json")

MIN_IDENT = 6  # campaign Phase-2 standard: >=6 overlap quarters of evidence
EXCLUDE = {"KTKBANK", "SOUTHBANK"}  # explicit user call 2026-08-06: banks stay null
ABS_TOL = 0.05  # below this a con-vs-std delta is rounding, not a subsidiary
REL_TOL = 0.001  # ... or 0.1% of standalone, whichever is larger
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}
WINDOW_END = 20260331  # Jun-2026 is still filing; leave it to the cron


def quarters(first=20150331, last=WINDOW_END):
    out = []
    for y in range(first // 10000, last // 10000 + 1):
        for m in (3, 6, 9, 12):
            qe = y * 10000 + m * 100 + LAST_DAY[m]
            if first <= qe <= last:
                out.append(qe)
    return out


def main():
    apply_it = "--apply" in sys.argv
    fund = json.load(open(DOCS))
    rename = json.load(open(RENAME))
    snaps = sorted(json.load(open(IDX))["Nifty 500"], key=lambda s: s["effectiveDate"])
    try:
        fin = {s: (m.get("f") == 1) for s, m in json.load(open(QR))["co"].items()}
    except Exception:
        fin = {}

    def resolve(sym):
        cur, seen = sym, set()
        while cur not in fund:
            if cur in seen or cur not in rename:
                return None
            seen.add(cur)
            cur = rename[cur]
        return cur

    def members_at(qe):
        ds = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
        best = None
        for s in snaps:
            if s["effectiveDate"] <= ds:
                best = s
            else:
                break
        return [x for x in best["symbols"] if not x.upper().startswith("DUMMY")]

    # ---- per-company identity profile from its OWN stored history
    def diverges(std, con):
        return abs(con - std) > max(ABS_TOL, REL_TOL * abs(std))

    prof = {}
    for sym, rows in fund.items():
        both = sorted([(r[0], r[1], r[3]) for r in rows if len(r) > 3 and r[1] is not None and r[3] is not None])
        div = [q for q, s, c in both if diverges(s, c)]
        first_div = min(div) if div else None
        # LEADING identity run: quarters from the start of the con series up to the first
        # material divergence. Evidence must open the series, not appear anywhere in it.
        lead = len([q for q, s, c in both if first_div is None or q < first_div])
        prof[sym] = {"n_ident": len(both) - len(div), "lead_ident": lead, "first_div": first_div}

    # ---- collect candidate gap cells across point-in-time membership
    targets = collections.defaultdict(list)
    reasons = collections.Counter()
    for qe in quarters():
        for msym in members_at(qe):
            sym = resolve(msym)
            if not sym:
                continue
            row = {r[0]: r for r in fund[sym]}.get(qe)
            if not row or len(row) < 2 or row[1] is None:
                continue  # nothing to copy from
            if len(row) > 3 and row[3] is not None:
                continue  # already filled
            if sym in EXCLUDE:
                reasons["excluded-by-user (bank)"] += 1
                continue
            p = prof.get(sym, {"lead_ident": 0, "first_div": None})
            if p["lead_ident"] < MIN_IDENT:
                reasons["identity-unproven (<%d leading quarters)" % MIN_IDENT] += 1
                continue
            if p["first_div"] is not None and qe >= p["first_div"]:
                reasons["at-or-after first divergence"] += 1
                continue
            targets[sym].append(qe)

    n_cells = sum(len(v) for v in targets.values())
    n_fin = sum(len(v) for s, v in targets.items() if fin.get(s))
    print("ELIGIBLE: %d cells across %d companies (%d cells are financials)" % (n_cells, len(targets), n_fin))
    print("rule: >=%d LEADING identity quarters AND gap strictly before first divergence\n" % MIN_IDENT)
    print("skipped:")
    for r, n in reasons.most_common():
        print("   %-42s %6d cells" % (r, n))
    top = sorted(((len(v), s) for s, v in targets.items()), reverse=True)[:15]
    print("\nlargest contributors:")
    for n, s in top:
        p = prof[s]
        print(
            "   %-13s %3d cells   lead_ident=%-3d first_div=%s%s"
            % (s, n, p["lead_ident"], p["first_div"], "  [FIN]" if fin.get(s) else "")
        )

    if not apply_it:
        print("\nDRY RUN -- nothing written. Re-run with --apply to write.")
        return

    journal = {}
    for path in (DOCS, MIRROR):
        d = json.load(open(path))
        filled = 0
        for sym, qes in targets.items():
            byqe = {r[0]: r for r in d.get(sym, [])}
            for qe in qes:
                r = byqe.get(qe)
                if not r:
                    continue
                while len(r) < 5:
                    r.append(None)
                if r[1] is None or r[3] is not None:
                    continue  # fill-only, re-checked per file
                r[3] = r[1]
                if r[4] is None:
                    r[4] = r[2]
                filled += 1
                if path == DOCS:
                    journal["%s|%d" % (sym, qe)] = {
                        "con": r[3],
                        "ann": r[4],
                        "src": "no-sub-identity-bulk",
                        "basis": "con=std",
                        "evidence": "%d leading identity qtrs; first divergence %s"
                        % (prof[sym]["lead_ident"], prof[sym]["first_div"]),
                        "applied": "2026-08-06 FILL-2020 pre-FY2020 con-PAT derivation",
                    }
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("wrote %-34s %d cells" % (os.path.basename(path), filled))

    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    led.update(journal)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("journalled %d cells -> %s" % (len(journal), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()

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
"""GATE H — correct a stored pre-2015 npStd cell the site's own FY identity indicts.

A CORRECTION IS NOT A FILL. A fill writes into a hole and its worst case is a wrong new number; a
correction destroys a value some earlier campaign put there on its own evidence, and its worst case
is replacing a right number with a wrong one — the §71h class, where a blanket resync overwrote
3IINFOLTD's correct owners figure with a total. So gate H is strictly tighter than gate E.

Input: scripts/_era_suspect_cells.json (agg_era_adjudicate.py — the site's own four quarters close
to the paisa against its own annual, and swapping our value in breaks the identity).

  H1  the VERDICT must be credible: the company's annual must be independent of its quarters
      (≥1 FY where they differ — the GLAXO trap, where MC's 0.46 for Mar-2011 propagated into its
      own annual and made the identity "close" perfectly), and the company must need ≤2 excusals.
      139 of the 175 suspects fail this and are NOT corrected: GLAXO wants 10 over 91 quarters and
      STERLINBIO 15 over 42, and GLAXO is a company where MC — not us — is demonstrably wrong.
  H2  THE NEIGHBOURHOOD MUST BE CLEAN. The site must reproduce our stored values at ±1 and ±2
      quarters with no disagreement. If it differs at a neighbour too, this is a VINTAGE
      difference across a stretch, not one defective cell of ours, and nothing here can tell which
      vintage is right. Removes MRPL (differs at Jun-08 845.40/869.80 and Sep-08 24.92/62.40),
      WOCKPHARMA, EICHERMOT, HMT.
  H3  the identity break must be MATERIAL: |our-FY-sum − annual| > max(1.0 cr, 2% of the annual).
  H4  the disputed difference must be material: > max(0.05 cr, 1% of our value).
  H5  ⚠️ TOLERANCE FLOORS MUST NOT BE MOST OF THE SIGNAL. The FY identity carries a 0.5 cr absolute
      floor, which is larger than MELSTAR's entire quarterly PAT (±0.2 cr) — on such a company the
      identity discriminates nothing. Require |annual| ≥ 10× that floor. (Memory:
      feedback-verify-before-claiming-a-fix — bound tests halve accuracy on small numbers.)
  H6  no other ledger may assert the value being replaced (checked: pre2015_attempted_* are ATTEMPT
      logs and assert nothing; mc_fyident_fills is revenue).

Guards: every cell's current value must equal the recorded `was` or the run aborts; blast-radius
diff; idempotent; journalled to scripts/era_pat_corrections.json with the full neighbourhood, both
FY sums and the annual, registered in verify_fills_live.py LEDGERS.

  python3 -X utf8 scripts/agg_tools/correct_era_suspects.py                 # dry-run
  python3 -X utf8 scripts/agg_tools/correct_era_suspects.py --apply
"""
import argparse
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import agg_era_gate as EG  # noqa: E402
import agg_gate as G  # noqa: E402
import mc_era as E  # noqa: E402

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SUSPECTS = os.path.join(SCRIPTS, "_era_suspect_cells.json")
LEDGER = os.path.join(SCRIPTS, "era_pat_corrections.json")
TOL = 0.011
MIN_ANNUAL = 10 * EG.FY_TOL_ABS  # H5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--stamp", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args()

    susp = json.load(open(SUSPECTS))["cells"]
    idc = json.load(open(E._ISIN_CACHE))
    orig = json.load(open(FUND))
    work = copy.deepcopy(orig)

    plan, refused, journal = [], [], {}
    for r in susp:
        s, q, ours_v, site_v = r["sym"], r["qe"], r["ours"], r["site"]
        tag = "%s|%d" % (s, q)
        if r.get("excusal_for_symbol") != "ALLOWED":  # H1
            refused.append((tag, "H1 verdict not credible: " + r.get("excusal_for_symbol", "?")[:60]))
            continue
        if abs(r["site_annual"]) < MIN_ANNUAL:  # H5
            refused.append((tag, "H5 annual {:.2f} is inside the identity's own floor".format(r["site_annual"])))
            continue
        if abs(r["sum_with_our_value"] - r["site_annual"]) <= max(1.0, abs(r["site_annual"]) * 0.02):
            refused.append((tag, "H3 identity break is not material"))  # H3
            continue
        if abs(site_v - ours_v) <= max(0.05, abs(ours_v) * 0.01):  # H4
            refused.append((tag, "H4 difference is not material"))
            continue
        ser, _ = E.quarters(idc[s], False)
        stored = G.ours_series(s, "patS")
        bad_nb = []
        for k in (-2, -1, 1, 2):  # H2
            x = EG.qde(EG.qord(q) + k)
            mine, theirs = stored.get(x), (ser.get(x) or {}).get("pat_total")
            if mine is not None and theirs is not None and G._agree(mine, theirs) == "no":
                bad_nb.append({"qe": x, "ours": mine, "site": theirs})
        if bad_nb:
            refused.append((tag, "H2 site also differs at %s -- vintage, not a defect" % [b["qe"] for b in bad_nb]))
            continue

        row = next((x for x in work.get(s, []) if x[0] == q), None)
        if row is None or row[1] is None or abs(row[1] - ours_v) > TOL:
            refused.append((tag, f"guard: live value {row[1] if row else None} != recorded was {ours_v}"))
            continue
        plan.append((s, q, ours_v, site_v))
        row[1] = site_v
        journal[tag] = {
            "std": site_v,
            "was": ours_v,
            "src": "moneycontrol quarterly_results_responsive (runbook §90)",
            "row_label": r.get("site_row"),
            "gate": "H — the site's own four quarters of FY%d close at %s against its own annual "
            "%s; with our value the same sum is %s. Neighbourhood ±2 reproduced exactly."
            % (r["fy_end"] // 10000, r["site_sum4Q"], r["site_annual"], r["sum_with_our_value"]),
            "fy_end": r["fy_end"],
            "fy_end_month_src": r.get("fy_end_month_src"),
            "annual_independent": True,
            "neighbourhood": {
                str(EG.qde(EG.qord(q) + k)): [
                    stored.get(EG.qde(EG.qord(q) + k)),
                    (ser.get(EG.qde(EG.qord(q) + k)) or {}).get("pat_total"),
                ]
                for k in (-2, -1, 0, 1, 2)
            },
            "caveat": (
                "ONE VENDOR. Moneycontrol/Trendlyne/Tickertape are one upstream feed "
                "(§81c), so this is not a second independent reader — it is the site's own "
                "annual row arbitrating its own quarterly row. A filing read outranks it."
            ),
            "applied": f"{a.stamp} era std-PAT correction pass",
        }

    diffs = []
    intended = {(s, q) for s, q, _, _ in plan}
    for s in set(list(orig) + list(work)):
        o = {x[0]: x for x in orig.get(s, [])}
        w = {x[0]: x for x in work.get(s, [])}
        for q in set(list(o) + list(w)):
            if o.get(q) != w.get(q) and (s, q) not in intended:
                diffs.append(f"{s} {q}: {o.get(q)} -> {w.get(q)}")
    if diffs:
        print("ABORT -- %d unintended changes: %s" % (len(diffs), diffs[:5]))
        return 2

    print("CORRECTIONS THAT PASS GATE H: %d of %d suspects\n" % (len(plan), len(susp)))
    for s, q, was, now in plan:
        print("   %-11s %s  %-10s -> %-10s" % (s, q, was, now))
    byreason = {}
    for _, why in refused:
        byreason[why.split(" ")[0]] = byreason.get(why.split(" ")[0], 0) + 1
    print("\nrefused %d: %s" % (len(refused), byreason))
    for t, w in refused[:8]:
        print("   %-20s %s" % (t, w))

    if a.apply and plan:
        tmp = FUND + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(work, fh, separators=(",", ":"))
        os.replace(tmp, FUND)
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(journal)
        with open(LEDGER, "w", encoding="utf-8") as fh:
            json.dump(led, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print("\nwrote %d corrections + journal -> %s" % (len(plan), os.path.basename(LEDGER)))
    elif not a.apply:
        print("\nDRY RUN -- nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

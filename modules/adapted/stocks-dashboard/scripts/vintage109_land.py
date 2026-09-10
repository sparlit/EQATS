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
"""Land the §109e by-product adjudication into the reviewed heal ledgers (append-only, deduped).

fund_cell_fix.json  <- npStd / npCon corrections
revop_cell_fix.json <- rev/op slots healed with the same row, plus the §70 PAT MIRROR for every
                       fund heal (the mirror only ever follows a fund_cell_fix entry).

Refuses to overwrite an existing entry with a different `fixed` — two adjudications disagreeing is
a human's call, never a silent overwrite.

RUN: python3 scripts/vintage109_land.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FOUND = "vintage109 by-product campaign 2026-08-25 (NSE as-filed + BSE detres + MC deep feed)"
REVOP_SLOT = {"rev_std": 0, "rev_con": 1, "op_std": 2, "op_con": 3, "pat_std": 4, "pat_con": 5}


def near(a, b, ab=0.35, rl=0.005):
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def why_fund(r, tgt):
    ev = r["evidence"]
    if r["verdict"] == "HEAL-PAIR":
        w = (
            "Runbook §109e by-product. NSE's archive holds only one filing of this quarter and it "
            "was filed {} days after quarter end ({}) — a re-filing, so it cannot state what was "
            "originally filed; it reads {}. BSE's detailed-results JSON (as-filed by construction, "
            "§42) reads {} and Moneycontrol's deep quarterly feed reads {} — two independent "
            "readers agreeing against the stored {}.".format(
                r["gap_qe_to_nsefiled"], r["nse_filed"], round(r["nse_pat"], 2), r["detres_pat"], _mc(r), r["stored"]
            )
        )
    else:
        w = (
            "Runbook §109e by-product: the stored value matched no vintage NSE holds. NSE's "
            "as-filed page for this quarter ({} basis, filed {} = qe+{}d, seq {}) reads {} cr "
            "against the stored {}.".format(
                r["nse_basis"],
                r["nse_filed"],
                r["gap_qe_to_nsefiled"],
                r["nse_seq"],
                round(r["nse_pat"], 4),
                r["stored"],
            )
        )
        if "DETRES" in ev:
            w += " BSE detres (as-filed by construction, §42) independently reads {}.".format(r["detres_pat"])
        if "MC" in ev:
            w += (
                f" Moneycontrol's deep quarterly feed reads {_mc(r)}; MC serves the restated vintage "
                "42% of the time (measured on the 257 §109 heals), so its agreement with the "
                "as-filed page means either MC is on that vintage or the restatement did not "
                "move the number — the as-filed value is confirmed either way."
            )
    if r["basis"] == "con":
        w += (
            " Consolidated: the target is the page's owners' bottom line and MC's owners figure "
            "reproduces it, which is what makes the page's line trustworthy here — the archive's "
            "consolidated bottom line is not reliably the owners' figure (BAJAJHLDNG Mar-2016)."
        )
    w += " No available reader reproduces the stored value."
    return w


def _mc(r):
    m = r.get("mc") or {}
    return m.get("pat_own") if (r["basis"] == "con" and m.get("pat_own") is not None) else m.get("pat_total")


def merge(path, new, label, apply):
    d = json.load(open(path, encoding="utf-8"))
    have = {(f["sym"], str(f["qe"]), f["basis"]): f for f in d["fixes"]}
    added = dup = conflict = 0
    for f in new:
        k = (f["sym"], str(f["qe"]), f["basis"])
        old = have.get(k)
        if old is not None:
            if abs(float(old["fixed"]) - float(f["fixed"])) > 0.011:
                conflict += 1
                print(
                    "  CONFLICT {} {} {}: ledger {} vs this campaign {} — NOT overwritten".format(
                        k[0], k[1], k[2], old["fixed"], f["fixed"]
                    )
                )
            else:
                dup += 1
            continue
        d["fixes"].append({kk: vv for kk, vv in f.items() if not kk.startswith("_")})
        have[k] = f
        added += 1
    print(
        "  [%s] add %d | already present %d | CONFLICT %d | ledger now %d"
        % (label, added, dup, conflict, len(d["fixes"]))
    )
    if apply and added:
        json.dump(d, open(path, "w"), indent=1, ensure_ascii=False)
        print(f"  wrote {os.path.basename(path)}")
    return added, conflict


def main():
    apply = "--apply" in sys.argv
    # --from FILE : land a PREVIOUSLY BUILT proposal set instead of rebuilding it. Needed after a
    # rebase: rebuilding reads the store, and once the heals are applied the store no longer shows
    # the defect, so a rebuild would silently produce an empty set. The entries carry their own
    # `was`, and the appliers are guarded on it, so a cell another session has since moved is
    # reported and skipped rather than forced. memory: feedback-minified-json-never-merge
    if "--from" in sys.argv:
        src = json.load(open(sys.argv[sys.argv.index("--from") + 1], encoding="utf-8"))
        print("landing a pre-built set: %d fund cells, %d revop slots" % (len(src["proposals"]), len(src["revop"])))
        a1, c1 = merge(os.path.join(HERE, "fund_cell_fix.json"), src["proposals"], "fund_cell_fix", apply)
        a2, c2 = merge(os.path.join(HERE, "revop_cell_fix.json"), src["revop"], "revop_cell_fix", apply)
        if not apply:
            print("\n(dry run — pass --apply to write the ledgers)")
        return
    a = json.load(open(os.path.join(HERE, "_vintage109_adjud.json")))["cells"]
    ro = json.load(open(os.path.join(HERE, "_vintage109_revop.json")))["revop"]
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    heals = [r for r in a.values() if r["verdict"] in ("HEAL", "HEAL-PAIR")]

    fund_props, revop_props = [], []
    for r in sorted(heals, key=lambda x: (x["sym"], x["qe"], x["basis"])):
        tgt = r["pair_target"] if r["verdict"] == "HEAL-PAIR" else round(r["nse_pat"], 2)
        fund_props.append(
            {
                "sym": r["sym"],
                "qe": str(r["qe"]),
                "basis": r["basis"],
                "was": r["stored"],
                "fixed": tgt,
                "why": why_fund(r, tgt),
                "found": FOUND,
            }
        )
        # §70 PAT mirror in sf_revop — only ever moved together with the fund heal
        name = "pat_{}".format(r["basis"])
        s = REVOP_SLOT[name]
        row = (revop.get(r["sym"]) or {}).get(str(r["qe"])) or []
        if len(row) > s and row[s] is not None and near(row[s], r["stored"]):
            revop_props.append(
                {
                    "sym": r["sym"],
                    "qe": str(r["qe"]),
                    "basis": name,
                    "was": row[s],
                    "fixed": tgt,
                    "why": "sf_revop §70 PAT mirror, synced to the fund_cell_fix heal "
                    "of the same cell. " + why_fund(r, tgt),
                    "found": FOUND,
                }
            )
    for p in ro:
        e = p["_ev"]
        line = "revenue from operations" if p["_field"] == "rev" else "operating profit"
        revop_props.append(
            {
                "sym": p["sym"],
                "qe": p["qe"],
                "basis": p["basis"],
                "was": p["was"],
                "fixed": p["fixed"],
                "why": (
                    "Runbook §109e by-product, ROW heal beside the PAT correction of the same cell "
                    "(feedback-heal-the-row-not-the-cell). NSE's as-filed page (seq {}, filed {} = "
                    "qe+{}d) prints {} {} cr against the stored {}; corroborated by {}.".format(
                        e["nse_seq"],
                        e["nse_filed"],
                        e["gap_qe_to_nsefiled"],
                        line,
                        p["fixed"],
                        p["was"],
                        " and ".join(
                            ("BSE detres {}".format(e["detres"]))
                            if x == "DETRES"
                            else ("Moneycontrol {}".format(e["mc"]))
                            for x in e["evidence"]
                        ),
                    )
                ),
                "found": FOUND,
            }
        )

    # the §108 cell the NSE PAT-row reader defect had hidden
    extra = json.load(open(os.path.join(HERE, "_vintage109_proposals.json")))
    note = (
        "vintage109 re-read of the §108 sweep 2026-08-25: the NSE reader had taken a blank "
        "minority-interest row as PAT=0, which hid this cell's restatement"
    )
    for src, dst in ((extra["proposals"], fund_props), (extra["revop"], revop_props)):
        for p in src:
            p = dict(p)
            p["found"] = note
            dst.append(p)

    print("PROPOSALS: %d fund cells, %d revop slots" % (len(fund_props), len(revop_props)))
    from collections import Counter

    print("  fund basis: {}".format(dict(Counter(p["basis"] for p in fund_props))))
    print("  revop basis: {}".format(dict(Counter(p["basis"] for p in revop_props))))
    json.dump(
        {"_doc": "§109e by-product heals", "proposals": fund_props, "revop": revop_props},
        open(os.path.join(HERE, "_vintage109_heals.json"), "w"),
        indent=1,
    )
    _a1, _c1 = merge(os.path.join(HERE, "fund_cell_fix.json"), fund_props, "fund_cell_fix", apply)
    _a2, _c2 = merge(os.path.join(HERE, "revop_cell_fix.json"), revop_props, "revop_cell_fix", apply)
    if not apply:
        print("\n(dry run — pass --apply to write the ledgers)")


if __name__ == "__main__":
    main()

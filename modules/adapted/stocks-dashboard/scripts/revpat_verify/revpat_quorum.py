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
"""RULE 6b, encoded. Cross-site quorum for rev/PAT, using ONLY P2-accepted mappings.

The user's standing mandate, verbatim intent: "check from many sites and it should match, only then
take it." Operationally:
  * a value is CONTRADICTED only when >=2 INDEPENDENT sites agree with each other and disagree with us
  * sites disagreeing among themselves => value NOT taken (SITES_DISAGREE), never a majority vote
  * a site our data was ever sourced from does not count toward quorum (provenance echo)
  * a mapping P2 REFUSED casts no vote at all -- notably Screener/Groww consolidated PAT, which
    publish TOTAL profit against our OWNERS-attributable series (P2 findings 1)

Nothing here decides a defect. A CONTRADICTED cell is a candidate that must then be arbitrated
against the filing itself (P5 ladder / runbook 57). The SBIN case in P2 is why: 10 of 10 quarters
disagreed with a site and the filing confirmed US.

  python3 -X utf8 revpat_quorum.py --out quorum.json
"""
import argparse
import collections
import glob
import json
import os

TREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root of THIS checkout
BASE = ""  # set by --base: the directory holding p2/*_map.json and <site>/<site>_pilot.jsonl
ABS_FLOOR, REL_BAND = 0.5, 0.005  # frozen in P2: max(Rs 0.5cr, 0.5%)


def agree(a, b):
    return abs(a - b) <= max(ABS_FLOOR, abs(b) * REL_BAND)


def load_ours():
    revop = json.load(open(os.path.join(TREE, "docs/sf_revop.json"), encoding="utf-8"))
    fund = json.load(open(os.path.join(TREE, "docs/sf_fundamentals.json"), encoding="utf-8"))
    ours, isfin = collections.defaultdict(dict), set()
    for s, d in revop.items():
        for k, row in d.items():
            ours[s][int(k)] = {"revS": row[0], "revC": row[1]}
            if row[6] == 1:
                isfin.add(s)
    for s, rows in fund.items():
        for r in rows:
            if isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int):
                ours[s].setdefault(r[0], {}).update({"patS": r[1], "patC": r[3]})
    return ours, isfin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="quorum.json")
    ap.add_argument("--suffix", default="pilot", help="which extraction set to read: <site>/<site>_<suffix>.jsonl")
    ap.add_argument("--base", required=True, help="dir holding p2/<site>_map.json and <site>/<site>_pilot.jsonl")
    a = ap.parse_args()
    global BASE
    BASE = a.base

    ours, isfin = load_ours()

    # ---- load the P2 cards; a mapping absent from a card is a REFUSAL and casts no vote ----
    cards = {}
    for p in glob.glob(os.path.join(BASE, "p2", "*_map.json")):
        c = json.load(open(p, encoding="utf-8"))
        cards[c["site"]] = c
    print("mapping cards: {}".format(", ".join(sorted(cards))))

    # (site, basis, class) -> {our_field: [(label, mult), ...]}
    accept = collections.defaultdict(lambda: collections.defaultdict(list))
    for site, c in cards.items():
        for seg, entries in c["map"].items():
            basis, cls = seg.split("|")
            for label, e in entries.items():
                accept[(site, basis, cls)][e["field"]].append((label, e["mult"]))

    # ---- gather site observations -------------------------------------------
    votes = collections.defaultdict(dict)  # (sym, qe, field) -> site -> value
    for site in cards:
        path = os.path.join(BASE, site, f"{site}_{a.suffix}.jsonl")
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            sym, basis = e["sym"].upper(), e.get("basis")
            q = int(str(e["qe"]).replace("-", ""))
            cls = "fin" if sym in isfin else "nonfin"
            for field, labels in accept[(site, basis, cls)].items():
                for label, mult in labels:
                    v = e["rows"].get(label)
                    if v is None:
                        continue
                    votes[(sym, q, field)][site] = float(v) * mult
                    break

    # ---- derive patE: BACKTEST-EFFECTIVE PAT --------------------------------
    # backtest-engine.js profitAt(): tries = basis==='std' ? [[1,2]] : [[3,4],[1,2]].
    # On the default consolidated basis the engine consumes patC where it exists and falls back to
    # patS per quarter -- so patE is the number strategy picks actually eat, and a defect invisible
    # in either pure basis can still flip a factor at the fallback boundary. We resolve the same
    # rule on OUR side and on each site's side, then adjudicate it as its own field.
    eff = {}
    for (sym, q, field), sv in list(votes.items()):
        if field not in ("patS", "patC"):
            continue
        mine = (ours.get(sym, {}) or {}).get(q, {})
        use = "patC" if mine.get("patC") is not None else "patS"
        if field != use:
            continue
        eff.setdefault((sym, q), {}).update(sv)
    for (sym, q), sv in eff.items():
        mine = (ours.get(sym, {}) or {}).get(q)
        if not mine:  # a site quarter we do not hold -- nothing to adjudicate
            continue
        votes[(sym, q, "patE")] = sv
        mine["patE"] = mine.get("patC") if mine.get("patC") is not None else mine.get("patS")

    # ---- adjudicate ---------------------------------------------------------
    out, tally = [], collections.Counter()
    for (sym, q, field), sv in sorted(votes.items()):
        mine = (ours.get(sym, {}) or {}).get(q, {}).get(field)
        if mine is None:
            tally["WE_HOLD_NOTHING"] += 1
            continue
        with_us = [s for s, v in sv.items() if agree(v, mine)]
        against = {s: v for s, v in sv.items() if not agree(v, mine)}
        # do the dissenters agree with EACH OTHER? that is what makes a contradiction
        blocs = []
        for s, v in against.items():
            for b in blocs:
                if agree(v, b["v"]):
                    b["sites"].append(s)
                    break
            else:
                blocs.append({"v": v, "sites": [s]})
        big = max((b for b in blocs), key=lambda b: len(b["sites"]), default=None)

        if len(with_us) >= 2:
            st = "CONFIRMED"
        elif len(with_us) == 1 and not against:
            st = "SINGLE_SITE_OK"
        elif big and len(big["sites"]) >= 2 and not with_us:
            st = "CONTRADICTED"
        elif (against and with_us) or len(blocs) > 1:
            st = "SITES_DISAGREE"
        else:
            st = "SINGLE_SITE_DISSENT"
        tally[st] += 1
        out.append(
            {
                "sym": sym,
                "qe": q,
                "field": field,
                "ours": mine,
                "sites": {s: round(v, 2) for s, v in sv.items()},
                "agree_with_us": with_us,
                "status": st,
            }
        )

    print("\nrule-6b quorum over %d (symbol, quarter, field) cells:" % len(out))
    for k in (
        "CONFIRMED",
        "SINGLE_SITE_OK",
        "SINGLE_SITE_DISSENT",
        "SITES_DISAGREE",
        "CONTRADICTED",
        "WE_HOLD_NOTHING",
    ):
        if tally[k]:
            print("  %-20s %5d" % (k, tally[k]))

    byf = collections.defaultdict(collections.Counter)
    for r in out:
        byf[r["field"]][r["status"]] += 1
    print("\nby field:")
    for f in ("revS", "revC", "patS", "patC", "patE"):
        if f in byf:
            t = byf[f]
            n = sum(t.values())
            print(
                "  %-5s n=%-4d CONFIRMED %-4d (%.1f%%)  1site %-4d  disagree %-3d  CONTRADICTED %d"
                % (
                    f,
                    n,
                    t["CONFIRMED"],
                    100.0 * t["CONFIRMED"] / n,
                    t["SINGLE_SITE_OK"],
                    t["SITES_DISAGREE"],
                    t["CONTRADICTED"],
                )
            )

    bad = [r for r in out if r["status"] in ("CONTRADICTED", "SITES_DISAGREE", "SINGLE_SITE_DISSENT")]
    if bad:
        print("\ncells needing arbitration at the filing (%d):" % len(bad))
        for r in sorted(bad, key=lambda r: -abs(max(r["sites"].values()) - r["ours"]))[:20]:
            print(
                "  %-11s %d %-5s ours=%-11s sites=%s  [%s]"
                % (r["sym"], r["qe"], r["field"], r["ours"], r["sites"], r["status"])
            )

    json.dump(
        {
            "_meta": {
                "rule": "6b: filing AND >=2 independent sites; sites disagreeing => not taken",
                "tolerance": "max(Rs0.5cr, 0.5%)",
                "tally": dict(tally),
                "note": "CONTRADICTED is a CANDIDATE, not a defect -- arbitrate at the filing",
            },
            "cells": out,
        },
        open(a.out, "w", encoding="utf-8"),
        indent=1,
    )
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()

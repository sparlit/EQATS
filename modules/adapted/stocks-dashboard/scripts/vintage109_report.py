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
"""§108 sweep — merge every route, classify, and PROPOSE the row heals.

Reads (all resumable, all optional — a missing one is REPORTED, never assumed empty):
    _vintage108_scan.json      BSE detres, as-filed by construction (§42), standalone only
    _vintage109_nse_fixed.json       NSE dual-vintage test, STANDALONE   — per-vintage pat/op/rev
    _vintage109_nse_con_fixed.json   NSE dual-vintage test, CONSOLIDATED — the basis detres cannot serve
    _vintage108_prov.json      provenance: which NSE page each 2026-07-27 fill actually read
    _vintage108_anchor_refusals.json   the refusals already on disk (§108 signature 1)

THE HEAL GATE. A slot is proposed only when the stored value is measurably a LATER vintage AND at
least one independent line of evidence says so:

  PROV    our own provenance record names the later-vintage page as the source of the fill, and
          the stored value is that page's value. This is a proof of the READ, not an inference
          from two numbers agreeing — the strongest evidence available, and the only one that
          reaches the consolidated basis.
  DETRES  BSE's detailed-results JSON, an independent as-filed reader, agrees with NSE's
          earliest-filed vintage (standalone only).

Value-match alone is never enough: two vintages of a steady filer differ by less than the noise
between feeds, and a coincidence is not a finding.

OUT: _vintage109_proposals.json  (fund_cell_fix + revop_cell_fix entries, NOT applied)
RUN: python3 scripts/vintage108_report.py
"""
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ABS_TOL, REL_TOL = 2.0, 0.03  # detres-vs-NSE agreement, the §42 cell tolerance
NEAR_ABS, NEAR_REL = 0.35, 0.005  # "the store IS this vintage"
POWERS = (0.001, 0.01, 0.1, 10.0, 100.0, 1000.0)
FUND_SLOT = {"std": 1, "con": 3}
REVOP_SLOT = {"rev_std": 0, "rev_con": 1, "op_std": 2, "op_con": 3, "pat_std": 4, "pat_con": 5}
REVOP_BASIS = {"rev_std": "std", "rev_con": "con"}  # the ledger calls revenue plain std/con


def load(name, default=None):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        print(f"  (ledger {name} ABSENT — its route contributes nothing to this run)")
        return {} if default is None else default
    return json.load(open(p, encoding="utf-8"))


def agree(a, b):
    return a is not None and b is not None and abs(a - b) <= max(ABS_TOL, abs(b) * REL_TOL)


def near(a, b):
    return a is not None and b is not None and abs(a - b) <= max(NEAR_ABS, abs(b) * NEAR_REL)


def days(a, b):
    import datetime

    try:
        return (
            datetime.date(b // 10000, (b // 100) % 100, b % 100) - datetime.date(a // 10000, (a // 100) % 100, a % 100)
        ).days
    except Exception:
        return None


def main():
    scan = load("_vintage108_scan.json").get("cells", {})
    nse = {"std": load("_vintage109_nse_fixed.json"), "con": load("_vintage109_nse_con_fixed.json")}
    prov = load("_vintage108_prov.json")
    ref = load("_vintage108_anchor_refusals.json").get("refusals", {})
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    vrf = load("vision_rev_fills.json")
    raw = load("_vintage108_raw.json")
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf-8"))

    done = {k: v for k, v in scan.items() if v.get("state") == "done"}
    print("=" * 78)
    print("PASS 1  BSE detres — %d cells fetched" % len(done))
    print(
        "  "
        + ", ".join(
            "%s=%d" % (k, n)
            for k, n in Counter(v.get("verdict", "?").split("=")[0] for v in done.values()).most_common()
        )
    )
    for b in ("std", "con"):
        print("PASS 2b NSE dual-vintage %s — %d cells" % (b, len(nse[b])))
        for k, n in Counter(v.get("verdict") for v in nse[b].values()).most_common():
            print("    %-30s %d" % (k, n))
    print("PASS 0  provenance — %d fill rows checked" % len(prov))
    for k, n in Counter(v.get("verdict") for v in prov.values()).most_common():
        print("    %-30s %d" % (k, n))

    # provenance index: (sym, qe, basis) -> the seq the 2026-07-27 pass actually read
    read_seq = {}
    for k, v in prov.items():
        if v.get("verdict") == "src-is-later-vintage":
            read_seq[(v["sym"], v["qe"], v["basis"])] = v["src_seq"]

    fund_props, revop_props, queues, byproduct = [], [], defaultdict(list), defaultdict(list)
    for basis in ("std", "con"):
        for key, v in sorted(nse[basis].items()):
            sym, qe = v["sym"], v["qe"]
            vints = [
                x for x in v.get("vintages", []) if x.get("pat") is not None and x.get("cumulative") != "Cumulative"
            ]
            if len(vints) < 2:
                if v.get("verdict") in ("single-vintage-mismatch", "stored-in-neither"):
                    byproduct[_subclass(v, scan.get(key, {}), fund, basis)].append(key + "|" + basis)
                continue
            asf = vints[0]
            seq = read_seq.get((sym, qe, basis))
            rest = next((x for x in vints[1:] if str(x.get("seq")) == str(seq)), None) if seq else None
            frow = next((r for r in fund.get(sym, []) if r[0] == qe), None)
            rrow = (revop.get(sym) or {}).get(str(qe)) or []
            ann = frow[2 if basis == "std" else 4] if frow and len(frow) > 4 else None

            # PAT — authority is sf_fundamentals; sf_revop slot 4/5 is the §70 mirror.
            cur = frow[FUND_SLOT[basis]] if frow and len(frow) > FUND_SLOT[basis] else None
            det = scan.get(key, {}).get("detres") if basis == "std" else None
            pat_rest = rest or next((x for x in vints[1:] if near(cur, x["pat"])), None)
            # A READER THAT CONTRADICTS VETOES THE HEAL. "At least one line of evidence" is not
            # enough on its own: a PROV-only cell whose detres reading disagrees with NSE's
            # as-filed page would be healed TOWARDS a value an independent reader rejects. Caught
            # by the post-heal invariant (agreement with detres rose 55%->97.5%, and the 4 cells
            # left disagreeing were all this hole — FSL Sep-2015 would have been divided by ten).
            contradicted = basis == "std" and det is not None and not agree(det, asf["pat"])
            ev = []
            if not contradicted:
                if rest is not None and near(cur, rest.get("pat")):
                    ev.append("PROV")
                if basis == "std" and det is not None and agree(det, asf["pat"]):
                    ev.append("DETRES")
            if cur is not None and pat_rest and not near(cur, asf["pat"]) and near(cur, pat_rest["pat"]):
                gap = days(ann, pat_rest.get("filed")) if ann else None
                if contradicted:
                    queues[f"pat-{basis}-detres-contradicts-nse-as-filed"].append(key)
                elif not ev:
                    queues[f"pat-{basis}-no-independent-evidence"].append(key)
                elif not isinstance(gap, int) or gap <= 180:
                    queues[f"pat-{basis}-restatement-gap-too-small"].append(key)
                else:
                    fund_props.append(
                        _entry(sym, qe, basis, cur, asf["pat"], asf, pat_rest, ann, gap, ev, det, "Net Profit")
                    )
            elif cur is not None and not near(cur, asf["pat"]):
                queues[f"pat-{basis}-store-matches-no-vintage"].append(key)

            # OP and REVENUE — the same read filled them, and sf_revop holds both.
            for field, lname in (("op", "operating profit"), ("rev", "revenue from operations")):
                bname = f"{field}_{basis}"
                slot = REVOP_SLOT[bname]
                if len(rrow) <= slot or rrow[slot] is None:
                    continue
                a = asf.get(field)
                if a is None:
                    queues[f"{bname}-as-filed-line-unreadable"].append(key)
                    continue
                # CLEAN FIRST. When the slot already holds the earliest vintage there is nothing
                # to look for — asking "which later vintage is this?" of a correct cell and then
                # queueing the failure to answer turned ~450 healthy slots into a fake backlog.
                if near(rrow[slot], a):
                    continue
                cand = (
                    rest
                    if (rest or {}).get(field) is not None
                    else next((x for x in vints[1:] if near(rrow[slot], x.get(field))), None)
                )
                cand_v = (cand or {}).get(field)
                # The Ind-AS "New" archive layout prints NO "profit from operations before other
                # income" subtotal at all — that line does not exist under Ind-AS — so `op` is
                # unreadable on the RESTATED page for ~350 vintage rows. But when provenance names
                # that page as the source, vision_rev_fills recorded the very value it read, and
                # that value IS the restated one. Use the record instead of re-deriving a subtotal
                # the document never printed.
                if cand_v is None and rest is not None:
                    logged = ((vrf.get("%s|%d" % (sym, qe)) or {}).get(basis) or {}).get(field)
                    if logged is not None and near(rrow[slot], logged):
                        cand, cand_v = rest, logged
                if cand is None or cand_v is None:
                    queues[f"{bname}-restated-line-unreadable"].append(key)
                    continue
                if not near(rrow[slot], cand_v) or near(rrow[slot], a):
                    continue  # this slot is not on the later vintage
                if abs(a - cand_v) <= 0.005:
                    continue  # the vintages agree; nothing to heal
                dv = None
                if basis == "std":
                    fdet = raw.get(key, {})
                    if field == "rev":
                        dv, _ = _fnum(
                            fdet,
                            "Net Sales/Revenue From Operations",
                            "Total Income From Operations",
                            "Net Sales",
                            "Interest Earned",
                        )
                    else:
                        dv, _ = _fnum(
                            fdet,
                            "Profit from Operations before Other Income, Interest and Exceptional Items",
                            "Operating Profit before Provisions and Contingencies",
                        )
                    dv = None if dv is None else dv / 10.0
                if dv is not None and not agree(dv, a):
                    queues[f"{bname}-detres-contradicts-nse-as-filed"].append(key)
                    continue
                ev2 = list(ev) if rest is cand else [e for e in ev if e != "PROV"]
                if dv is not None and "DETRES" not in ev2:
                    ev2.append("DETRES")
                if "PROV" not in ev2 and "DETRES" not in ev2:
                    queues[f"{bname}-no-independent-evidence"].append(key)
                    continue
                gap = days(ann, cand.get("filed")) if ann else None
                if not isinstance(gap, int) or gap <= 180:
                    queues[f"{bname}-restatement-gap-too-small"].append(key)
                    continue
                revop_props.append(
                    _entry(
                        sym,
                        qe,
                        REVOP_BASIS.get(bname, bname),
                        rrow[slot],
                        a,
                        asf,
                        dict(cand, **{field: cand_v}),
                        ann,
                        gap,
                        ev2,
                        None,
                        lname,
                        field,
                    )
                )

            # the PAT mirror in sf_revop must move with the fund heal, never on its own
            mslot = REVOP_SLOT[f"pat_{basis}"]
            if (
                any(p["sym"] == sym and p["qe"] == "%d" % qe and p["basis"] == basis for p in fund_props)
                and len(rrow) > mslot
                and rrow[mslot] is not None
                and near(rrow[mslot], cur)
            ):
                revop_props.append(
                    _entry(
                        sym,
                        qe,
                        f"pat_{basis}",
                        rrow[mslot],
                        asf["pat"],
                        asf,
                        pat_rest,
                        ann,
                        days(ann, pat_rest.get("filed")),
                        ev,
                        det,
                        "Net Profit (sf_revop §70 mirror)",
                    )
                )

    print("\nHEAL PROPOSALS")
    print(
        "  fund_cell_fix  : %d cells over %d symbols  (%s)"
        % (
            len(fund_props),
            len({p["sym"] for p in fund_props}),
            ", ".join("%s=%d" % (b, sum(1 for p in fund_props if p["basis"] == b)) for b in ("std", "con")),
        )
    )
    for b, n in Counter(p["basis"] for p in revop_props).most_common():
        print("  revop_cell_fix %-8s: %d" % (b, n))
    print("  evidence: {}".format(dict(Counter("+".join(p["_ev"]["evidence"]) for p in fund_props))))
    print("\nQUEUES (not proposed — each says why):")
    for q, ks in sorted(queues.items(), key=lambda x: -len(x[1])):
        print("  %-44s %d" % (q, len(ks)))
    print("\nBY-PRODUCT — store matches no vintage NSE holds (NOT auto-healed):")
    for t, ks in sorted(byproduct.items(), key=lambda x: -len(x[1])):
        print("  %-44s %d" % (t, len(ks)))

    ref_syms = {k.split("|")[0] for k in ref}
    prop_syms = {p["sym"] for p in fund_props}
    print(
        "\nAnchor refusals already on disk (§108 signature 1): %d cells / %d symbols; "
        "%d of those symbols are proposed here" % (len(ref), len(ref_syms), len(ref_syms & prop_syms))
    )

    json.dump(
        {
            "_doc": "vintage108 heal proposals — reviewed before they reach the ledgers",
            "proposals": fund_props,
            "revop": revop_props,
            "queues": dict(queues),
            "byproduct": dict(byproduct),
        },
        open(os.path.join(HERE, "_vintage109_proposals.json"), "w"),
        indent=1,
    )
    print("\nwrote _vintage109_proposals.json")


def _entry(sym, qe, basis, was, fixed, asf, rest, ann, gap, ev, det, lname, field="pat"):
    why = (
        "Runbook §108 restated-comparative vintage. NSE's results archive holds two filings of "
        "this quarter: the ORIGINAL, filed {} ({}, seq {}), {} {} cr, and a RESTATEMENT filed "
        "{} ({}, seq {}), {} {} cr — the stored value. Our ann date for the cell is {}, {} days "
        "BEFORE that restatement was filed, so the stored figure was not public on the date the "
        "cell claims.".format(
            asf.get("filed"),
            asf.get("indAs"),
            asf.get("seq"),
            lname,
            asf.get(field),
            rest.get("filed"),
            rest.get("indAs"),
            rest.get("seq"),
            lname,
            rest.get(field),
            ann,
            gap,
        )
    )
    if "PROV" in ev:
        why += (
            " PROVENANCE: vision_rev_fills records this cell as read from "
            "financial_res_..._{}.html — the restatement page itself.".format(rest.get("seq"))
        )
    if "DETRES" in ev and det is not None:
        why += f" BSE detres (as-filed by construction, §42) independently reads {det} cr."
    return {
        "sym": sym,
        "qe": "%d" % qe,
        "basis": basis,
        "was": was,
        "fixed": round(fixed, 2),
        "why": why,
        "found": "vintage108 sweep 2026-08-24 (NSE dual-vintage + provenance + detres)",
        "_ev": {
            "evidence": ev,
            "as_filed": asf.get(field),
            "restated": rest.get(field),
            "as_filed_seq": asf.get("seq"),
            "restated_seq": rest.get("seq"),
            "detres": det,
            "stored_ann": ann,
            "gap_days": gap,
        },
    }


def _fnum(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v), n
            except ValueError:
                pass
    return None, None


def _subclass(v, sc, fund, basis):
    """Name the class of a store that matches no vintage NSE holds.

    ⚠️ THE CROSS-BASIS TEST MUST LOOK AT THE *OTHER* BASIS. An earlier cut compared the stored
    value against `row[3]` (npCon) whichever basis it was adjudicating — so every CON cell was
    compared with itself, always "equal", and 310 consolidated cells were labelled "the std slot
    holds the CON value". A tautology dressed as a finding. The cross-basis twin of `std` is
    `con` and vice versa.
    """
    asf = v.get("as_filed")
    if not asf:
        return "no-readable-vintage"
    sym, qe = v["sym"], v["qe"]
    row = next((r for r in fund.get(sym, []) if r[0] == qe), None)
    other_slot = 3 if basis == "std" else 1
    other = row[other_slot] if row and len(row) > other_slot else None
    ratio = v["stored"] / asf if asf else 0
    if any(abs(ratio - p) <= 0.02 * p for p in POWERS):
        return "scale-step (§74)"
    if other is not None and abs(other - v["stored"]) <= 0.011:
        return "std slot holds the CON value (§59)" if basis == "std" else "con slot is a STD copy (con-copy class)"
    # detres is STANDALONE-ONLY (§42). The scan ledger is keyed SYM|QE with no basis in the key,
    # so reading it for a `con` cell compares BSE's standalone figure with NSE's consolidated one —
    # of course they differ, and 108 consolidated cells were filed under "the two readers disagree"
    # on that alone. The same cross-basis slip as the twin test above.
    det = sc.get("detres") if basis == "std" else None
    if det is not None and not agree(det, asf):
        return "the two readers disagree with each other — adjudicate"
    if basis == "con":
        return "con: NSE as-filed vs the store (no detres for this basis)"
    return (
        "two as-filed readers vs the store"
        if det is not None
        else "std: NSE as-filed vs the store (detres not yet read)"
    )


if __name__ == "__main__":
    main()

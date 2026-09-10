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
"""§109e BY-PRODUCTS — cells whose store matches NO vintage NSE holds.

These are not the §108 vintage class: the stored value is not the restatement either, it is simply
not any figure the company filed for that quarter. The sweep found them on the way past and did not
heal them, because they need their own second reader per basis.

THE GATE, identical in spirit to §109d — evidence AND no available reader may contradict:
    std  second reader = BSE detres (as-filed by construction, §42)
    con  second reader = Moneycontrol, guarded against the §85 std-fallback
        (vintage108_mc_con.py; detres serves standalone only and must never be asked about con —
         the scan ledger is keyed SYM|QE with no basis in the key, and reading it for a con cell
         compares BSE's standalone number with NSE's consolidated one)
A cell is proposed only when the second reader AGREES with NSE's earliest-filed page and DISAGREES
with the store. When it backs the STORE instead, the NSE page is the suspect one and the cell is
queued, not healed — that case is real: measured on the first 12 consolidated cells, 3 of them.

CROSS-BASIS TAG: where the stored value equals the OTHER basis's stored value to the paisa, the
entry is labelled (std slot holding the CON figure, §59; or a con slot that is a STD copy). The
heal is the same — write the basis's own as-filed figure — but the label matters for the runbook.

OUT: scripts/_vintage108_bp_proposals.json
RUN: python3 scripts/vintage108_byproduct.py
"""
import datetime
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ABS_TOL, REL_TOL = 2.0, 0.03
NEAR_ABS, NEAR_REL = 0.35, 0.005
POWERS = (0.001, 0.01, 0.1, 10.0, 100.0, 1000.0)
# A results filing lands within roughly a quarter of the period end. A page filed much later than
# that, when it is the ONLY one NSE holds, is the year-later restatement with the original simply
# missing from the archive — healing to it would write a restated figure onto an as-filed ann date,
# which is the very defect §108 exists to remove. Measured here: 19 consolidated candidates rested
# on a lone page filed 200-449 days after quarter end (DRREDDY Sep-2015: 449).
# detres is exempt: it is AS-FILED BY CONSTRUCTION (§42), so when it corroborates the value, the
# page's own filing date does not matter.
MAX_FILING_LAG_DAYS = 120


def filing_lag(qe, filed):
    try:
        a = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
        b = datetime.date(filed // 10000, (filed // 100) % 100, filed % 100)
        return (b - a).days
    except Exception:
        return None


FUND_SLOT = {"std": 1, "con": 3}
REVOP_SLOT = {"rev_std": 0, "rev_con": 1, "op_std": 2, "op_con": 3, "pat_std": 4, "pat_con": 5}
REVOP_BASIS = {"rev_std": "std", "rev_con": "con"}


def load(name, default=None):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        print(f"  (ledger {name} ABSENT)")
        return {} if default is None else default
    return json.load(open(p, encoding="utf-8"))


def agree(a, b):
    return a is not None and b is not None and abs(a - b) <= max(ABS_TOL, abs(b) * REL_TOL)


def near(a, b):
    return a is not None and b is not None and abs(a - b) <= max(NEAR_ABS, abs(b) * NEAR_REL)


def fnum(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def main():
    nse = {"std": load("_vintage108_nse.json"), "con": load("_vintage108_nse_con.json")}
    scan = load("_vintage108_scan.json").get("cells", {})
    raw = load("_vintage108_raw.json")
    mccon = load("_vintage108_mccon.json")
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf-8"))

    fund_props, revop_props, queues = [], [], defaultdict(list)
    seen = Counter()
    for basis in ("std", "con"):
        for key, v in sorted(nse[basis].items()):
            if v.get("verdict") not in ("single-vintage-mismatch", "stored-in-neither"):
                continue
            sym, qe = v["sym"], v["qe"]
            vints = [
                x for x in v.get("vintages", []) if x.get("pat") is not None and x.get("cumulative") != "Cumulative"
            ]
            if not vints:
                queues["no-readable-vintage"].append(key + "|" + basis)
                continue
            asf = vints[0]
            frow = next((r for r in fund.get(sym, []) if r[0] == qe), None)
            slot = FUND_SLOT[basis]
            cur = frow[slot] if frow and len(frow) > slot else None
            if cur is None:
                queues["cell-empty-now"].append(key + "|" + basis)
                continue
            if near(cur, asf["pat"]):
                seen["already-as-filed"] += 1
                continue

            if basis == "std":
                second, sname = scan.get(key, {}).get("detres"), "BSE detres"
                if second is None:
                    queues["std-no-detres-reading"].append(key + "|" + basis)
                    continue
            else:
                m = mccon.get(key) or {}
                if m.get("verdict") == "mc-con-is-std-fallback":
                    queues["con-mc-is-std-fallback (§85)"].append(key + "|" + basis)
                    continue
                if m.get("verdict") in ("no-mc-quarter", "no-mc-id") or m.get("mc_con") is None:
                    queues["con-no-second-reader"].append(key + "|" + basis)
                    continue
                second, sname = m["mc_con"], "Moneycontrol consolidated (§85-guarded)"

            if agree(second, cur) and not agree(second, asf["pat"]):
                queues["second-reader-BACKS-THE-STORE — NSE page suspect"].append(key + "|" + basis)
                continue
            if not agree(second, asf["pat"]):
                queues["second-reader-agrees-with-neither"].append(key + "|" + basis)
                continue
            if agree(second, cur):
                queues["second-reader-cannot-separate"].append(key + "|" + basis)
                continue
            if basis != "std":  # std's second reader IS detres, as-filed
                lag = filing_lag(qe, asf.get("filed"))
                if lag is None or lag > MAX_FILING_LAG_DAYS:
                    queues["target-page-filed-%dd+-after-qe — may BE the restatement" % MAX_FILING_LAG_DAYS].append(
                        f"{key}|{basis} (lag {lag})"
                    )
                    continue

            # label, for the runbook — the ACTION is the same either way
            other = frow[3 if basis == "std" else 1] if frow and len(frow) > 3 else None
            ratio = cur / asf["pat"] if asf["pat"] else 0
            if any(abs(ratio - p) <= 0.02 * p for p in POWERS):
                cls = "scale-step (§74)"
            elif other is not None and abs(other - cur) <= 0.011:
                cls = "the std slot held the CON figure (§59)" if basis == "std" else "the con slot was a STD copy"
            else:
                cls = "the store matched no filed figure"
            seen[cls] += 1

            why = (
                "Runbook §109e by-product: the stored value matches NO vintage NSE holds for "
                "this quarter. NSE's earliest-filed page ({}, {}, seq {}) reads Net Profit {} cr; "
                "{} independently reads {} cr; the store held {}. Class: {}.".format(
                    asf.get("filed"), asf.get("indAs"), asf.get("seq"), asf["pat"], sname, round(second, 2), cur, cls
                )
            )
            fund_props.append(
                {
                    "sym": sym,
                    "qe": "%d" % qe,
                    "basis": basis,
                    "was": cur,
                    "fixed": round(asf["pat"], 2),
                    "why": why,
                    "found": "vintage108 by-product sweep 2026-08-24",
                    "_cls": cls,
                }
            )

            # the sf_revop PAT mirror moves with it, and rev/op when detres can vouch for them
            rrow = (revop.get(sym) or {}).get(str(qe)) or []
            ms = REVOP_SLOT[f"pat_{basis}"]
            if len(rrow) > ms and rrow[ms] is not None and near(rrow[ms], cur):
                revop_props.append(
                    {
                        "sym": sym,
                        "qe": "%d" % qe,
                        "basis": f"pat_{basis}",
                        "was": rrow[ms],
                        "fixed": round(asf["pat"], 2),
                        "why": why + " (sf_revop §70 PAT mirror, synced to the fund heal)",
                        "found": "vintage108 by-product sweep 2026-08-24",
                    }
                )
            if basis != "std":
                continue
            f = raw.get(key, {})
            for field, bname, lname, dnames in (
                (
                    "rev",
                    "rev_std",
                    "revenue from operations",
                    (
                        "Net Sales/Revenue From Operations",
                        "Total Income From Operations",
                        "Net Sales",
                        "Interest Earned",
                    ),
                ),
                (
                    "op",
                    "op_std",
                    "operating profit",
                    (
                        "Profit from Operations before Other Income, Interest and Exceptional Items",
                        "Operating Profit before Provisions and Contingencies",
                    ),
                ),
            ):
                s2 = REVOP_SLOT[bname]
                a = asf.get(field)
                if len(rrow) <= s2 or rrow[s2] is None or a is None:
                    continue
                if near(rrow[s2], a):
                    continue
                dv = fnum(f, *dnames)
                dv = None if dv is None else dv / 10.0
                if dv is None or not agree(dv, a) or agree(dv, rrow[s2]):
                    queues[f"{bname}-no-usable-second-reader"].append(key)
                    continue
                revop_props.append(
                    {
                        "sym": sym,
                        "qe": "%d" % qe,
                        "basis": REVOP_BASIS.get(bname, bname),
                        "was": rrow[s2],
                        "fixed": round(a, 2),
                        "why": (
                            "Runbook §109e by-product: NSE's earliest-filed page (seq {}) reads {} "
                            "{} cr and BSE detres independently reads {:.2f} cr; the store held {}.".format(
                                asf.get("seq"), lname, a, dv, rrow[s2]
                            )
                        ),
                        "found": "vintage108 by-product sweep 2026-08-24",
                    }
                )

    print("BY-PRODUCT PROPOSALS")
    print(
        "  fund_cell_fix : %d cells over %d symbols (%s)"
        % (
            len(fund_props),
            len({p["sym"] for p in fund_props}),
            ", ".join("%s=%d" % (b, sum(1 for p in fund_props if p["basis"] == b)) for b in ("std", "con")),
        )
    )
    for b, n in Counter(p["basis"] for p in revop_props).most_common():
        print("  revop_cell_fix %-8s: %d" % (b, n))
    print("  classes: {}".format(dict(Counter(p["_cls"] for p in fund_props))))
    print("  (already as-filed, nothing to do: %d)" % seen["already-as-filed"])
    print("\nQUEUES:")
    for q, ks in sorted(queues.items(), key=lambda x: -len(x[1])):
        print("  %-52s %d" % (q, len(ks)))
    json.dump(
        {
            "_doc": "runbook §109e by-product proposals — gate: NSE earliest-filed page + a "
            "per-basis second reader agreeing with it and disagreeing with the store",
            "proposals": [{k: v for k, v in p.items() if k != "_cls"} for p in fund_props],
            "revop": revop_props,
            "queues": dict(queues),
        },
        open(os.path.join(HERE, "_vintage108_bp_proposals.json"), "w"),
        indent=1,
    )
    print("\nwrote _vintage108_bp_proposals.json")


if __name__ == "__main__":
    main()

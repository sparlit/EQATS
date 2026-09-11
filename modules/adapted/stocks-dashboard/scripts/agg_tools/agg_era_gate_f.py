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
"""GATE F-SOLO -- the pre-2015 gate for symbols where we store NOTHING to anchor against.

WHY GATE E CANNOT DECIDE THESE. agg_era_gate's E1 proves identity by having the site reproduce
>=8 of OUR stored quarters. That is the right test wherever we hold values -- and it is structurally
impossible where we hold none. Measured on the pre-2009 patStd residue 2026-08-26: 75 open cells on
13 symbols have a Moneycontrol PAT at the target quarter while our own series for that key is empty
or near-empty (SB&TINTL 0 stored / MC 78 periods from 1998-06; SQRDSFWARE 0/…; WELLWININD 0/…).
GATE E reports NOT-FOUND, which reads like "the site does not have it" when the site plainly does.

PRE2015_CAMPAIGN.md's LANDING RULES already name the gate for this case, and explicitly allow it
single-source:

    GATE F -- FY quarter-sum identity: the 4 same-source quarters sum to the same-source AUDITED
    annual -> land all four.

What that rule does NOT cover on its own is IDENTITY: "which company is this?" E1 answered that
with our own numbers; with no numbers to answer it, this module answers it with an ISIN.

  F0  IDENTITY BY ISIN, not by name and not by ticker. MC's autosuggest row for the symbol carries
      an ISIN; ours comes from bse_master.scrip_id == our symbol (mc_era.isin_for). They must be
      EQUAL. A recycled or coincidentally-equal ticker fails here -- which is the §89 DVL/DTIL trap
      and memory feedback-scrip-id-ticker-coincidence. No ISIN on our side => REFUSED, never
      "probably the same company".
  F1  THE FY IDENTITY at the TARGET FY only: site's own 4 quarters == site's own annual within
      max(0.5cr, 0.4%) -- agg_era_gate's own FY tolerance, and its fy_end_month_near, so an
      off-cycle filer is framed correctly rather than silently NO-TESTed.
  F2  ANNUAL INDEPENDENCE (runbook §90d). "The four quarters sum to the annual" proves nothing if
      the site COMPUTED that annual by summing them. GLAXO 2011 is the documented case: MC prints
      0.46 between quarters of 115.70 and 147.54 and its annual closes PERFECTLY on the corrupt
      number. So the company must have >=1 FY anywhere in its own MC history where the annual
      DIFFERS from its four quarters. 122 of 466 companies failed this test in §90d.
  F3  CONTIGUITY: the target and both immediate neighbour periods exist in the site's table.
  F4  a printed 0 is the not-reported sentinel, never a value (agg_gate gate B).

⚠️ WHAT THIS GATE CANNOT DO, stated because the ledger must not overclaim: F0 proves the COMPANY,
F1/F2 prove the site's series is internally coherent at that FY. Neither proves the site's VINTAGE
matches the as-filed print, and there is no second reader here to check it against. That is strictly
weaker than GATE E (which adds our own series as a second voice) and strictly weaker than GATE X
(two publishers). It is used only where E and X are impossible, and every cell says so.

CALIBRATION. --calibrate runs the identical rule over cells we ALREADY store, as a hold-out, and
prints the mismatch rate. The identity leg (F0) cannot be calibrated that way -- a hold-out symbol
by definition has stored values -- so what is measured is the FY-identity rule, not the ISIN rule.
Run it before landing, and put its number in the ledger (apply_agg_pat_fills --calibration).

  python3 -X utf8 scripts/agg_tools/agg_era_gate_f.py --cells <cells.json> --out <props.json>
  python3 -X utf8 scripts/agg_tools/agg_era_gate_f.py --calibrate --sample 1200 --to 20081231
"""
import argparse
import collections
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import contextlib

import agg_era_gate as EG  # noqa: E402
import agg_gate as G  # noqa: E402
import mc_era as E  # noqa: E402

MAX_ANCHORS_FOR_SOLO = 8  # at or above this, GATE E can run and its verdict wins
_ALIAS = None


def rename_target(sym):
    """Our OWN rename authority: backtest-engine.js FUND_ALIAS + scripts/_rename_map.json."""
    global _ALIAS
    if _ALIAS is None:
        import re

        js = open(os.path.join(ROOT, "docs", "backtest-engine.js"), encoding="utf8").read()
        _ALIAS = json.loads(re.search(r"const FUND_ALIAS = (\{.*?\});", js, re.DOTALL).group(1))
        with contextlib.suppress(Exception):
            _ALIAS = dict(json.load(open(os.path.join(ROOT, "scripts", "_rename_map.json"))), **_ALIAS)
    return _ALIAS.get(sym)


def our_isin(sym):
    """-> (isin, note). mc_era.isin_for keys on bse_master.scrip_id == OUR SYMBOL, which for an era
    ticker is the §76 coincidence: measured cross-session 2026-08-26, only 5 of 36 unresolved era
    symbols appear as a BSE scrip_id at all, so the ISIN rung never fired for the other 31 and a
    rung that never fires looks exactly like a rung that fired and found nothing. Second key: the
    symbol OUR OWN rename authority maps this one to (BILT->BALLARPUR gives INE294A01037, L&T->LT
    gives INE018A01030 -- both then match Moneycontrol exactly). Still an ISIN test, never a name
    test; if neither key yields an ISIN the answer is None and the cell is REFUSED."""
    isin, note = E.isin_for(sym)
    if isin:
        return isin, f"our key {sym}: {note}"
    t = rename_target(sym)
    if t:
        isin, note = E.isin_for(t)
        if isin:
            return isin, f"our key {t} via OUR rename map {sym}->{t}: {note}"
    return None, "no ISIN under {}{}".format(sym, (f" or its rename target {t}") if t else "")


def annual_independent(q, ann, cand):
    """>=1 FY in the site's OWN history where its annual differs from its own four quarters."""
    seen = 0
    for fyend in sorted(ann):
        # An OFF-CYCLE annual key (MC prints e.g. 20051031 for a 7-month transition year) has no
        # quarter frame at all -- qord() cannot place it, and asking site_fy about it raises.
        # Skip it rather than crash: it is not evidence either way about the annual's independence.
        if (fyend // 100) % 100 not in EG._LASTDAY:
            continue
        v, _d = EG.site_fy(q, ann, cand, fyend)
        if v == "RESTATED":
            seen += 1
    return seen > 0, seen


STRICT_NEIGHBOURS = False  # F1b -- see main()'s --strict-neighbours


def check_f(sym, qe, ident, q, ann, cand="pat_total", require_isin=True):
    """-> (value|None, report). Never writes."""
    rep = {"sym": sym, "qe": qe, "gate": "F-solo", "notes": []}
    if require_isin:
        ours, note = our_isin(sym)
        theirs = (ident or {}).get("isin")
        rep["isin_ours"], rep["isin_mc"], rep["isin_src"] = ours, theirs, note
        if not ours:
            rep["state"] = "REJECT-F0"
            rep["why"] = f"no ISIN on our side ({note[:60]}) -- identity unprovable without anchors"
            return None, rep
        if not theirs or ours.upper() != theirs.upper():
            rep["state"] = "REJECT-F0"
            rep["why"] = f"ISIN mismatch: ours={ours} mc={theirs}"
            return None, rep

    val = (q.get(qe) or {}).get(cand)
    if val is None:
        rep["state"] = "REJECT-F1"
        rep["why"] = "site has no value at %d" % qe
        return None, rep
    if val == 0:
        rep["state"] = "REJECT-F4"
        rep["why"] = "printed 0 = the not-reported sentinel"
        return None, rep

    prev_q, next_q = EG.qde(EG.qord(qe) - 1), EG.qde(EG.qord(qe) + 1)
    miss = [x for x in (prev_q, next_q) if (q.get(x) or {}).get(cand) is None]
    if miss:
        rep["state"] = "REJECT-F3"
        rep["why"] = f"neighbour period(s) {miss} absent from the site's table"
        return None, rep

    fem, femwhy = EG.fy_end_month_near(ann, qe)
    _, fyend = EG.fy_of(qe, fem)
    verdict, detail = EG.site_fy(q, ann, cand, fyend)
    rep["fy_end_month"], rep["fy_end_month_src"] = fem, femwhy
    rep["fy_target"] = dict(detail, verdict=verdict)
    if verdict != "OK":
        rep["state"] = "REJECT-F1"
        rep["why"] = f"target FY identity {verdict}: {detail}"
        return None, rep
    if STRICT_NEIGHBOURS:
        # F1b. GATE E2b was allowed to judge the TARGET FY alone because E1 carried the identity.
        # With no anchors there is no E1, so the §60d conservatism comes back: a restated
        # neighbour FY is the only remaining signal that the site's vintage moves near this cell.
        nb = {}
        for tag, off in (("prev", -4), ("next", 4)):
            nb[tag] = EG.site_fy(q, ann, cand, EG.qde(EG.qord(fyend) + off))
        rep["fy_neighbours"] = {t: dict(d2, verdict=v2) for t, (v2, d2) in nb.items()}
        bad = [t for t, (v2, _) in nb.items() if v2 == "RESTATED"]
        if bad:
            rep["state"] = "REJECT-F1b"
            rep["why"] = "neighbour FY restated on the site ({}) and nothing else proves identity".format(",".join(bad))
            return None, rep

    indep, nrest = annual_independent(q, ann, cand)
    rep["annual_independent"] = {"ok": indep, "fys_where_annual_differs": nrest, "fys_tested": len(ann)}
    if not indep:
        rep["state"] = "REJECT-F2"
        rep["why"] = (
            "the site's annual NEVER differs from its own four quarters in %d FYs -- it "
            "may be COMPUTED from them, so the identity proves nothing (§90d GLAXO)" % len(ann)
        )
        return None, rep

    rep["state"] = "FILLED-F"
    rep["row"] = q[qe].get(cand + "_label") or cand
    return val, rep


def _series(ident):
    q, qn = E.quarters(ident, False)
    ann, an = EG._era_annual(ident, False)
    return q, ann, qn, an


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells")
    ap.add_argument("--out")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--sample", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--to", type=int, default=20081231)
    ap.add_argument("--reach")
    ap.add_argument(
        "--strict-neighbours",
        action="store_true",
        help="F1b: also require both neighbour FYs to close. Restores the §60d\n                         conservatism that GATE E2b was allowed to drop only because E1 carried\n                         the identity there.",
    )
    a = ap.parse_args()
    global STRICT_NEIGHBOURS
    if a.strict_neighbours:
        STRICT_NEIGHBOURS = True
    idc = json.load(open(E._ISIN_CACHE)) if os.path.exists(E._ISIN_CACHE) else {}
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))

    if a.calibrate:
        # hold-out: cells we already store, on companies MC resolves. F0 is skipped (a stored
        # symbol trivially has anchors); what is measured is F1+F2+F3+F4.
        reach = json.load(open(a.reach)) if a.reach else {}
        pop = []
        for sym, rec in (reach or {}).items():
            if not rec.get("resolved") or not idc.get(sym):
                continue
            for r in fund.get(sym, []):
                if r[0] <= a.to and r[1] is not None:
                    pop.append((sym, r[0]))
        random.Random(a.seed).shuffle(pop)
        pop = pop[: a.sample]
        print(
            "hold-out: %d stored cells (<= %d) on %d companies -- F0 NOT measured here\n"
            % (len(pop), a.to, len({s for s, _ in pop}))
        )
        cache, filled, match, misses = {}, 0, 0, []
        t0 = time.time()
        for sym, qe in pop:
            if sym not in cache:
                cache[sym] = _series(idc[sym])
            q, ann, _, _ = cache[sym]
            if not q or not ann:
                continue
            val, rep = check_f(sym, qe, idc[sym], q, ann, require_isin=False)
            if val is None:
                continue
            filled += 1
            ours = fund[sym]
            stored = next((r[1] for r in ours if r[0] == qe), None)
            if G._agree(stored, val) != "no":
                match += 1
            else:
                misses.append({"sym": sym, "qe": qe, "ours": stored, "gate": val})
        print(
            "GATE F-solo (F1+F2+F3+F4) fills %d/%d (%.1f%%)  reproduces ours %d  MISMATCH %d (%.2f%%)  [%.0fs]"
            % (
                filled,
                len(pop),
                100.0 * filled / max(1, len(pop)),
                match,
                filled - match,
                100.0 * (filled - match) / max(1, filled),
                time.time() - t0,
            )
        )
        for m in misses[:25]:
            print("   MISS %-12s %d ours=%s gate=%s" % (m["sym"], m["qe"], m["ours"], m["gate"]))
        if a.out:
            json.dump(
                {
                    "population": len(pop),
                    "would_fill": filled,
                    "mismatch": filled - match,
                    "mismatch_rate": round(100.0 * (filled - match) / max(1, filled), 2),
                    "misses": misses,
                },
                open(a.out, "w"),
                indent=1,
                sort_keys=True,
            )
        return 0

    cells = [tuple(c) for c in json.load(open(a.cells))]
    by = collections.defaultdict(list)
    for sym, qe, _field in cells:
        by[sym].append(int(qe))
    props, reports = {}, {}
    for sym in sorted(by):
        ident = idc.get(sym)
        if not ident:
            for qe in by[sym]:
                reports["%s|%d|patS" % (sym, qe)] = {"state": "UNRESOLVED"}
            continue
        ours = G.ours_series(sym, "patS")
        q, ann, qn, an = _series(ident)
        anchors = [
            x
            for x in q
            if x in ours and q[x].get("pat_total") is not None and G._agree(ours[x], q[x]["pat_total"]) != "no"
        ]
        if len(anchors) >= MAX_ANCHORS_FOR_SOLO:
            for qe in by[sym]:
                reports["%s|%d|patS" % (sym, qe)] = {
                    "state": "OUT-OF-SCOPE",
                    "why": "%d anchors -- GATE E can run here and wins" % len(anchors),
                }
            continue
        for qe in by[sym]:
            key = "%s|%d|patS" % (sym, qe)
            if not q or not ann:
                reports[key] = {"state": "NOT-FOUND", "site": qn, "annual": an}
                continue
            val, rep = check_f(sym, qe, ident, q, ann)
            rep["anchors_available"] = len(anchors)
            rep["site_note"], rep["annual_note"] = qn, an
            reports[key] = rep
            if val is not None:
                props[key] = {
                    "value": val,
                    "state": "FILLED-F",
                    "chosen": {
                        "site": "mc",
                        "cand": "pat_total",
                        "row": rep["row"],
                        "anchors": len(anchors),
                        "worst_anchor": 0.0,
                        "precision": "site-exact",
                        "nearest_anchor_q": None,
                    },
                    "corroborated_by": [],
                    "resolved_via": "isin-equality (F0)",
                    "fy_check": {"target": rep["fy_target"]},
                    "our_fy_identity": {"verdict": "NO-TEST", "have": len(anchors)},
                    "sites": {"mc": qn},
                    "evidence": (
                        "GATE F-solo: our series holds %d usable anchors so E1 is "
                        "IMPOSSIBLE here. Identity by ISIN equality (%s == MC's %s, ours "
                        "from %s). The site's OWN four quarters sum to its OWN annual at "
                        "the target FY %d (sum4Q %s vs annual %s, diff %s), its annual is "
                        "INDEPENDENT of its quarters (differs in %d of %d FYs, so it is "
                        "not a computed total), the target and both neighbour periods "
                        "exist, and the print is not the 0 sentinel. ⚠️ No second reader "
                        "and no vintage check -- weaker than GATE E and GATE X, used only "
                        "where both are impossible."
                        % (
                            len(anchors),
                            rep.get("isin_ours"),
                            rep.get("isin_mc"),
                            (rep.get("isin_src") or "")[:40],
                            rep["fy_target"]["fy_end"],
                            rep["fy_target"].get("sum4Q"),
                            rep["fy_target"].get("annual"),
                            rep["fy_target"].get("diff"),
                            rep["annual_independent"]["fys_where_annual_differs"],
                            rep["annual_independent"]["fys_tested"],
                        )
                    ),
                }
    json.dump(
        {"generated": time.strftime("%Y-%m-%d %H:%M IST"), "gate": "F-solo", "proposals": props, "reports": reports},
        open(a.out, "w"),
        indent=1,
        sort_keys=True,
    )
    by_state = collections.Counter(r.get("state", "?") for r in reports.values())
    print("%d of %d cells passed GATE F-solo -> %s" % (len(props), len(cells), a.out))
    for k, v in by_state.most_common():
        print("   %-18s %d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())

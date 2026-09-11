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
"""GATE E -- the pre-2015 gate, for targets that sit OUTSIDE our own series entirely.

WHY agg_gate.py cannot decide these. Its gate A wants >=2 reproduced anchors within +-6 quarters of
the target, because in the 2019-2026 window a distant match says nothing about a restated vintage
near the cell. In the 2002-2014 era the anchors are not merely distant, they are on the WRONG SIDE:
our stored series usually BEGINS after the gap ends. KSB, measured 2026-08-12: Moneycontrol's
standalone table reproduces **74 of our stored quarters** with one disagreement (Dec-2018, ours
2.53 against 25.30 -- a 10x, i.e. our own scale-step defect class), and every one of those anchors
is 2008 or later while the 21 open cells are 2005-2007. Gate A reports "0 anchors inside +-6q" and
refuses. The company identity and the basis are proven beyond doubt; what is unproven is the
VINTAGE at the target. So gate E keeps the identity requirement, drops the locality requirement it
cannot satisfy, and replaces it with a test that reaches the target directly:

  E1  IDENTITY, globally.  >= MIN_ANCHORS reproduced across the whole overlap, disagreements
      <= MAX_BAD cells AND <= MAX_BAD_RATE, and NONE within +-6 quarters of the target. (A distant
      disagreement is usually OUR defective cell -- runbook §81e measured that on 45 of 97 refusals
      -- so it is recorded as a suspect, not used as a veto.)
  E2  SITE-INTERNAL FY IDENTITY at the target and BOTH neighbouring FYs (§60d: reject the years
      adjacent to a restated one). The site's own four quarters must sum to the site's own annual.
      It needs nothing from us, which is exactly why it works where we hold nothing.
      ⚠️ THE FY-END MONTH IS READ LOCALLY. agg_fy_check.fy_end_month takes the most common month
      across the WHOLE annual table; KSB filed to March until 2001 and to December from 2002
      (measured: annual keys 19900331..20010331 then 20021231..20251231), so the global answer is
      wrong for one era or the other, and a wrong FY frame makes the identity a silent NO-TEST.
      Here the month comes from the annual keys nearest the target.
  E3  CONTIGUITY. The target and both immediate neighbours must exist in the site's own table, so
      the value is part of a run rather than an isolated period. Off-frame period ends (MPHASIS
      filed Jan/Apr/Jul/Oct in this era) never match our quarter and are counted, not ignored.
  E4  B / C / D from agg_gate, unchanged: a printed 0 is the not-reported sentinel; a value equal
      to our stored OTHER basis is the copied-con fingerprint; the row label must be the one that
      reproduces our stored values, never assumed.
  E5  PRECISION measured from the anchors (site-exact vs rounded), and the NEAREST-ANCHOR DISTANCE
      recorded in provenance -- these cells are further from evidence than a §81 fill and the
      ledger must say so.

Cells that DO have local anchors are not this module's business -- agg_gate handles them and its
verdict wins. Nothing here writes.

  python3 -X utf8 scripts/agg_tools/agg_era_gate.py --cells /tmp/open_cells_0214.json \
          --out /tmp/era_props.json [--syms KSB,MTNL]
"""
import argparse
import collections
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import agg_gate as G  # noqa: E402
import agg_sources as A  # noqa: E402
import mc_era as E  # noqa: E402

MIN_ANCHORS = 8  # E1: the identity claim, made globally rather than locally
# ★ CALIBRATED BY HOLD-OUT (era_calibrate.py, 1,200 cells / 386 companies, 2026-08-12), not chosen.
# The first cut was MAX_BAD=2 / 3%, which refused 949 cells on 210 companies agreeing with us
# 92-97% of the time (KTKBANK 83 anchors / 3 disagreements, BASF 82/4, UNITECH 80/4) -- and the
# disagreements sat 12-17 years from the target. Dropping each held cell in turn and asking what
# the gate would have written:
#     maxbad=2  rate=3%    fills 380/1200   mismatch 1.32%
#     maxbad=4  rate=6%    fills 502/1200   mismatch 1.39%
#     maxbad=10 rate=15%   fills 600/1200   mismatch 1.17%
# +58% reach at a FLAT error rate, because the protection was never coming from the global cap --
# it comes from "no disagreement within +-6q of the target" and from the FY identity. Same
# conclusion runbook §81e reached when agg_gate's GUARD_Q was 12, and 15% is agg_gate's own
# GLOBAL_MAX_BAD. (2 of the 7 residual mismatches are cells the FY identity indicts as OURS --
# FACT 2008-03, FIRSTLEASE 2010-12 -- so the true gate error is below the measured bound.)
MAX_BAD = 10  # absolute number of disagreeing anchors tolerated ANYWHERE
MAX_BAD_RATE = 0.15
NEAR_BAD_Q = 6  # ... but none of them may sit this close to the target
FY_TOL_REL = 0.004
FY_TOL_ABS = 0.5
# E2b -- must the NEIGHBOUR FYs also close, or only the target's own FY?
# Default True = the original §60d conservatism (reject the years adjacent to a restated one).
# ★ CALIBRATED BY HOLD-OUT for the pre-2009 era (era_calibrate_e2.py, 2026-08-26) before any cell
# was written with it False -- see that script's header for the measured mismatch rates. The reason
# it needed measuring at all: on the 1,852-cell pre-2009 patStd residue this single clause is the
# largest addressable refusal (159 cells whose OWN target FY closes to the paisa while a neighbour
# FY does not), and a neighbour restatement is evidence about the NEIGHBOUR, not about the target.
NEIGHBOUR_FY_REQUIRED = True
# ★ WHICH ROW CARRIES THE VINTAGE TEST FOR AN op CELL (2026-09-05). E2 asks "is the site's quarterly
# row the same vintage as its annual?". Run on op_pre itself it refused 4,075 of 18,345 op cells --
# and on 3,119 of those the site's OWN PAT still closed to the paisa for the same FY(s). PAT is the
# line year-end reclassification cannot move; op is the line it moves first (other income vs other
# operating income, excise, expense regrouping in the audited annual). So with E2_VINTAGE_FOR_OP =
# "pat_total" the restatement test runs on PAT and the op identity is JOURNALLED, not enforced.
# Calibrated by hold-out (era_calibrate_op.py --e2-pat) before any cell was written with it: the
# numbers are in the runbook entry for this sweep. None = the original behaviour (op tests op).
E2_VINTAGE_FOR_OP = None
_LASTDAY = {3: 331, 6: 630, 9: 930, 12: 1231}
_STEP = [3, 6, 9, 12]


def qord(qe):
    return (qe // 10000) * 4 + _STEP.index((qe // 100) % 100)


def qde(o):
    return (o // 4) * 10000 + _LASTDAY[_STEP[o % 4]]


def fy_end_month_near(ann, qe, span=3):
    """FY-end month from the annual keys NEAREST the target -- see E2 in the docstring."""
    if not ann:
        return 3, "no annual table"
    y = qe // 10000
    near = [k for k in ann if abs(k // 10000 - y) <= span]
    pool = near or list(ann)
    c = collections.Counter((k // 100) % 100 for k in pool if (k // 100) % 100 in _LASTDAY)
    if not c:
        return 3, "no month in annual keys"
    m = c.most_common(1)[0][0]
    return m, (
        "from %d annual keys within +-%dy of %d" % (len(pool), span, y)
        if near
        else "no annual key near %d; whole-table fallback" % y
    )


def fy_of(qe, fem):
    o, i = qord(qe), _STEP.index(fem)
    end = o + ((i - o) % 4)
    return [qde(end - k) for k in (3, 2, 1, 0)], qde(end)


def _close(a, b):
    return abs(a - b) <= max(FY_TOL_ABS, abs(b) * FY_TOL_REL)


def site_fy(q, ann, cand, fyend):
    """('OK'|'RESTATED'|'NO-TEST', detail) for the FY ending at `fyend`."""
    qs = [qde(qord(fyend) - k) for k in (3, 2, 1, 0)]
    vals = [(q.get(x) or {}).get(cand) for x in qs]
    target = (ann.get(fyend) or {}).get(cand)
    if target is None or any(v is None for v in vals):
        return "NO-TEST", {"fy_end": fyend, "have": sum(v is not None for v in vals), "annual": target}
    s = round(sum(vals), 2)
    return (
        "OK" if _close(s, target) else "RESTATED",
        {"fy_end": fyend, "sum4Q": s, "annual": target, "diff": round(s - target, 2)},
    )


def check(sym, qe, field="patS", site="mc", ident=None, excused=None):
    """-> (value|None, report). Never writes.

    `excused` is a set of quarters whose disagreement has been ADJUDICATED as ours, by the FY
    quarter-sum identity in agg_era_adjudicate.py. They are dropped from the comparison entirely --
    not counted as agreement, not counted as disagreement -- so an excused cell can never inflate
    the anchor count. Passing None keeps the strict first-pass behaviour.
    """
    excused = excused or set()
    con = field.endswith("C")
    rep = {"sym": sym, "qe": qe, "field": field, "site": site, "gate": "E", "notes": []}
    if ident is not None:
        series, note = E.quarters(ident, con)
        rep["resolved_via"] = ident.get("via")
        rep["sc_id"] = ident.get("sc_id")
    else:
        series, note = A.read(site, sym, con)
        rep["resolved_via"] = "symbol"
    rep["site_note"] = note
    if not series:
        rep["state"] = "NOT-FOUND"
        return None, rep

    ours = G.ours_series(sym, field)
    other = G.ours_series(sym, G.OTHER[field])
    rep["our_series"] = {"n": len(ours), "first": min(ours, default=None), "last": max(ours, default=None)}

    for cand in G.FIELD_CANDS[field]:
        hits = [
            (q, ours[q], series[q][cand])
            for q in sorted(series)
            if q in ours and series[q].get(cand) is not None and q not in excused
        ]
        if not hits:
            continue
        bad = [h for h in hits if G._agree(h[1], h[2]) == "no"]
        good = [h for h in hits if h not in bad]
        r = {
            "cand": cand,
            "anchors": len(good),
            "bad": len(bad),
            "bad_cells": [{"qe": q, "ours": o, "site": s} for q, o, s in bad[:6]],
        }
        if len(good) < MIN_ANCHORS:
            rep.setdefault("rejected", []).append(
                "%s: GATE-E1 only %d anchors, need %d" % (cand, len(good), MIN_ANCHORS)
            )
            continue
        if len(bad) > MAX_BAD or (len(bad) / float(len(hits))) > MAX_BAD_RATE:
            rep.setdefault("rejected", []).append("%s: GATE-E1 %d/%d disagreements" % (cand, len(bad), len(hits)))
            continue
        nearbad = [q for q, _, _ in bad if abs(qord(q) - qord(qe)) <= NEAR_BAD_Q]
        if nearbad:
            rep.setdefault("rejected", []).append(
                "%s: GATE-E1 disagreement %s within %dq of the target" % (cand, nearbad, NEAR_BAD_Q)
            )
            continue

        val = (series.get(qe) or {}).get(cand)
        if val is None:
            rep.setdefault("rejected", []).append("%s: site has no value at %d" % (cand, qe))
            continue
        if val == 0:
            rep.setdefault("rejected", []).append(f"{cand}: GATE-B printed 0 = not-reported sentinel")
            continue
        ov = other.get(qe)
        if ov is not None and abs(ov - val) <= max(G.EXACT_ABS, abs(ov) * G.EXACT_REL):
            rep.setdefault("rejected", []).append(f"{cand}: GATE-C equals our stored {G.OTHER[field]} ({ov})")
            continue

        prev_q, next_q = qde(qord(qe) - 1), qde(qord(qe) + 1)
        miss = [x for x in (prev_q, next_q) if (series.get(x) or {}).get(cand) is None]
        if miss:
            rep.setdefault("rejected", []).append(
                f"{cand}: GATE-E3 neighbour period(s) {miss} absent from the site's table"
            )
            continue

        ann, _anote = A.read_annual(site, sym, con) if ident is None else (_era_annual(ident, con))
        fem, femwhy = fy_end_month_near(ann, qe)
        _, fyend = fy_of(qe, fem)
        a5 = {}
        vcand = cand
        if field in ("opS", "opC") and E2_VINTAGE_FOR_OP:
            vcand = E2_VINTAGE_FOR_OP
            r["op_fy_identity"] = {
                t: dict(zip(("verdict", "detail"), site_fy(series, ann, cand, qde(qord(fyend) + off)), strict=False))
                for t, off in (("target", 0), ("prev", -4), ("next", 4))
            }
        for tag, off in (("target", 0), ("prev", -4), ("next", 4)):
            a5[tag] = site_fy(series, ann, vcand, qde(qord(fyend) + off))
            # ★ A DERIVED subtotal has no printed row to be checked against in its own era (MC
            # prints none before 2008), so it is held to BOTH identities: the PAT vintage test
            # above AND its own quarter-sum closing on the derived annual. Either failing vetoes.
            if cand == "op_der" and vcand != cand:
                v2, d2 = site_fy(series, ann, cand, qde(qord(fyend) + off))
                if a5[tag][0] == "OK" and v2 != "OK":
                    a5[tag] = (v2, dict(d2, also=f"op_der identity {v2}"))
        restated = [t for t, (v, _) in a5.items() if v == "RESTATED"]
        if not NEIGHBOUR_FY_REQUIRED:  # E2b -- see the constant's note
            restated = [t for t in restated if t == "target"]
        notest = [t for t, (v, _) in a5.items() if v == "NO-TEST"]
        r.update(
            {
                "fy_end_month": fem,
                "fy_end_month_src": femwhy,
                "vintage_row": vcand,
                "A5": {t: {"verdict": v, **d} for t, (v, d) in a5.items()},
            }
        )
        if restated:
            rep.setdefault("rejected", []).append(
                "{}: GATE-E2 FY restated on the site ({})".format(cand, ",".join(restated))
            )
            rep["fy_detail"] = r["A5"]
            continue
        if a5["target"][0] == "NO-TEST":
            rep.setdefault("rejected", []).append(f"{cand}: GATE-E2 no FY identity available at the target ({notest})")
            rep["fy_detail"] = r["A5"]
            continue

        # our-FY identity, where we hold the siblings: enforced, same as agg_fy_check gate B
        sibs = [qde(qord(fyend) - k) for k in (3, 2, 1, 0)]
        mine = [(x, (val if x == qe else ours.get(x))) for x in sibs]
        annv = (ann.get(fyend) or {}).get(cand)
        if annv is not None and all(v is not None for _, v in mine):
            s = round(sum(v for _, v in mine), 2)
            r["our_fy_identity"] = {
                "sum4Q": s,
                "site_annual": annv,
                "diff": round(s - annv, 2),
                "verdict": "CONFIRMED" if _close(s, annv) else "MISMATCH",
            }
            if not _close(s, annv):
                rep.setdefault("rejected", []).append(f"{cand}: our-FY identity MISMATCH ({s} vs {annv})")
                continue
        else:
            r["our_fy_identity"] = {"verdict": "NO-TEST", "have": sum(1 for _, v in mine if v is not None)}

        worst = max(abs(o - s) for _, o, s in good)
        near = min(abs(qord(q) - qord(qe)) for q, _, _ in good)
        precision = "site-exact" if worst <= 0.01 else f"rounded({worst:.2f})"
        r.update(
            {
                "worst_anchor": round(worst, 4),
                "nearest_anchor_q": near,
                "precision": precision,
                "row": (series[qe].get(cand + "_label") or cand),
                "excused": sorted(excused) or None,
            }
        )
        rep["chosen"] = {
            "site": site,
            "cand": cand,
            "row": r["row"],
            "anchors": len(good),
            "worst_anchor": round(worst, 4),
            "precision": precision,
            "nearest_anchor_q": near,
        }
        rep["detail"] = r
        rep["state"] = "FILLED-EXACT" if precision == "site-exact" else "FILLED-ROUNDED"
        return val, rep

    rep["state"] = "NOT-FOUND" if "rejected" not in rep else "REJECT-GATE-E"
    return None, rep


def _era_annual(ident, con):
    """MC annual table for an already-resolved sc_id (mirror of mc_era.quarters)."""
    tf = "cons_yearly" if con else "yearly"
    url = (
        "https://appfeeds.moneycontrol.com/jsonapi/stocks/yearly_results_responsive"
        "?sc_id={}&type_format={}&start=0&limit=200".format(ident["sc_id"], tf)
    )
    txt = A._get("appfeeds.moneycontrol.com", url, A.MC_PACE, "mc", "y_{}_{}".format(ident["sc_id"], tf))
    out = {}
    if not txt:
        return out, "mc: no annual body"
    try:
        rows = (json.loads(txt) or {}).get("data") or []
    except ValueError:
        return out, "mc: unparseable annual"
    for r in rows if isinstance(rows, list) else []:
        qe = A.qe_from_label(r.get("yrc0"))
        if qe is None or qe in out:
            continue
        # mirror agg_sources.mc_annuals: the derived op must exist in the ANNUAL table too, or E2's
        # FY identity for an op cell is a silent NO-TEST on every ISIN-resolved symbol (2026-09-05)
        vals = A.mc_row_values(r)
        if vals:
            out[qe] = vals
    return out, "mc: %d FYs" % len(out)


def _evidence(rep):
    """The provenance sentence for a GATE-E pass, written HERE because the applier's default is wrong.

    apply_agg_pat_fills.py builds `evidence` only when a proposal does not carry its own, and its
    template opens with "gate A/A2 passed" -- a gate that never ran on these cells. Its own comment
    says the template "describes a gate A/A2 pass and nothing else", which is exactly the shape of a
    comment that documents a defect instead of fixing it (memory: feedback-config-that-never-took-
    effect), and every GATE-E cell already in scripts/agg_pat_cell_fills.json carries that wrong
    claim. Emitting the sentence here fixes it forward for every future era fill; entries written
    before 2026-08-26 stay mislabelled and are identified by the presence of `fy_check` (gate A/A2
    never produces one).
    """
    c, d = rep.get("chosen") or {}, rep.get("detail") or {}
    a5 = d.get("A5") or {}
    restated = [t for t in ("prev", "next") if (a5.get(t) or {}).get("verdict") == "RESTATED"]
    tgt = a5.get("target") or {}
    return (
        "GATE E%s (pre-2015, runbook §90): E1 identity -- that site's own %s series reproduces "
        "%d of our stored quarters, worst anchor error %s, %d disagreement(s) anywhere and NONE "
        "within ±%dq; nearest anchor %d quarter(s) from the target. E2 the site's OWN FY "
        "quarter-sum identity on its %s row closes at the target FY (%s vs annual %s). E3 target "
        "and both neighbour periods present. Precision %s.%s"
        % (
            "2b" if restated else "",
            c.get("cand"),
            d.get("anchors", 0),
            c.get("worst_anchor"),
            d.get("bad", 0),
            NEAR_BAD_Q,
            c.get("nearest_anchor_q", -1),
            d.get("vintage_row", c.get("cand")),
            tgt.get("sum4Q"),
            tgt.get("annual"),
            c.get("precision"),
            (
                " E2b: the {} FY is RESTATED on the site and did NOT veto -- a neighbour restatement is "
                "evidence about the NEIGHBOUR; hold-out calibrated on stored pre-2009 cells, and our "
                "store holds 0 rows before 2001, so a target before 2001 has no calibration base.".format(
                    "/".join(restated)
                )
            )
            if restated
            else "",
        )
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--reach", help="mc_era.py output, for ISIN-resolved sc_ids")
    ap.add_argument("--syms")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--e2b",
        action="store_true",
        help="E2 judges the TARGET FY only; a restated neighbour FY no longer vetoes. "
        "Calibrated by hold-out first (era_calibrate_e2.py) -- never flip it "
        "without re-running that on the era you are filling.",
    )
    # ★ EXCUSED ANCHORS (2026-09-05, op sweep). {SYM: [qe, ...]} of stored cells ADJUDICATED as not
    # holding this field's definition -- measured, per cell, against the site's own rows (the opS
    # slot of 2008-2016 holds the after-depreciation figure = MC's ebit_pre row, not op_pre). They
    # are dropped from the comparison entirely, never counted as agreement, and the list is
    # journalled in every proposal (`excused`). Without this, a symbol's 8 defective 2015-16 cells
    # read as 8 disagreements and E1's rate cap refuses a series whose identity is not in doubt.
    ap.add_argument("--excuse", help="json {SYM: [qe,...]} of adjudicated non-comparable cells")
    ap.add_argument(
        "--e2-pat",
        action="store_true",
        help="op cells: run E2's vintage test on the site's own PAT row and journal "
        "the op identity (see E2_VINTAGE_FOR_OP). Hold-out calibrated first.",
    )
    a = ap.parse_args()

    global NEIGHBOUR_FY_REQUIRED, E2_VINTAGE_FOR_OP
    if a.e2b:
        NEIGHBOUR_FY_REQUIRED = False
    if a.e2_pat:
        E2_VINTAGE_FOR_OP = "pat_total"
    cells = [tuple(c) for c in json.load(open(a.cells))]
    if a.syms:
        want = set(a.syms.split(","))
        cells = [c for c in cells if c[0] in want]
    reach = json.load(open(a.reach)) if a.reach else {}
    idcache = json.load(open(E._ISIN_CACHE)) if os.path.exists(E._ISIN_CACHE) else {}
    excuse = {k: set(v) for k, v in json.load(open(a.excuse)).items()} if a.excuse else {}

    props, reports = {}, {}
    t0 = time.time()
    for i, (sym, qe, field) in enumerate(sorted(cells)):
        ident = idcache.get(sym)
        if reach.get(sym) and not reach[sym].get("resolved"):
            reports["%s|%d|%s" % (sym, qe, field)] = {"state": "UNRESOLVED", "why": reach[sym].get("why")}
            continue
        val, rep = check(sym, int(qe), field, ident=ident, excused=excuse.get(sym))
        key = "%s|%d|%s" % (sym, qe, field)
        reports[key] = rep
        if val is not None:
            props[key] = {
                "value": val,
                "state": rep["state"],
                "chosen": rep["chosen"],
                "corroborated_by": [],
                "resolved_via": rep.get("resolved_via"),
                "fy_check": rep["detail"].get("A5"),
                "our_fy_identity": rep["detail"].get("our_fy_identity"),
                "op_fy_identity": rep["detail"].get("op_fy_identity"),
                "vintage_row": rep["detail"].get("vintage_row"),
                "excused": rep["detail"].get("excused"),
                "evidence": _evidence(rep),
                "sites": {"mc": rep.get("site_note")},
            }
        if (i + 1) % 100 == 0:
            print(
                "[%4d/%4d] %-11s %-8s %-16s (%.0fs)  filled=%d"
                % (i + 1, len(cells), sym, qe, rep.get("state", "?"), time.time() - t0, len(props))
            )
            sys.stdout.flush()
            json.dump({"proposals": props, "reports": reports}, open(a.out, "w"), indent=1, sort_keys=True)

    json.dump(
        {
            "generated": time.strftime("%Y-%m-%d %H:%M IST"),
            "gate": "E (pre-2015)",
            "proposals": props,
            "reports": reports,
        },
        open(a.out, "w"),
        indent=1,
        sort_keys=True,
    )
    by = collections.Counter(r.get("state", "?") for r in reports.values())
    print("\n%d of %d cells passed GATE E -> %s (%.0fs)" % (len(props), len(cells), a.out, time.time() - t0))
    for k, v in by.most_common():
        print("   %-22s %d" % (k, v))


if __name__ == "__main__":
    main()

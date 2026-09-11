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
"""GATE A5 -- the restated-year detector, and the confirmation on a DIFFERENT AXIS.

§62's closing rule: "a confirmation check that uses the same addressing scheme as the thing it is
confirming proves nothing. Confirm across a different axis." The quarterly gate (agg_gate.py)
compares the site's QUARTERLY series against ours. This module uses the site's ANNUAL table -- a
separate row of its own data -- two ways:

  A5  SITE-INTERNAL FY IDENTITY (mandatory, and it needs nothing from us).
      The site's own four quarters of a financial year must sum to the site's own annual figure for
      that year. When they do not, that year is RESTATED on the site while its quarterly row is
      as-reported -- exactly the §60d Gate A2 class -- and any cell taken out of it is a different
      vintage from its neighbours. Measured on this sweep:
          ICIL    FY2022  quarters 2,862.87 vs annual 2,842.02   (-20.85)
          PEL     FY2023  quarters 9,354.70 vs annual 8,934.30  (-420.40)  Piramal Pharma demerger
          WELCORP FY2022  quarters 5,915.04 vs annual 6,505.11  (+590.07)
      All three had passed the quarterly gate with 27-40 anchors and zero local disagreements. This
      check is the only thing that caught them.
      §60d also says reject the years ADJACENT to a restated one, so a failing FY vetoes its
      neighbours' cells too.

  B   OUR-QUARTERS IDENTITY (corroboration, not a veto).
      our three stored quarters + the proposed value vs the site's annual. A hit means the proposed
      number is the one that makes OUR OWN financial year add up. A miss can be filer-side (§45,
      memory: feedback-fy-identity-can-be-filer-side), so it is recorded, not enforced.

  python3 -X utf8 scripts/agg_tools/agg_fy_check.py --props P.json --out-props P.gated.json
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agg_gate as G  # noqa: E402
import agg_sources as A  # noqa: E402

TOL_REL = 0.004
TOL_ABS = 0.5
_ANN = {}


_LASTDAY = {3: 331, 6: 630, 9: 930, 12: 1231}
_STEP = [3, 6, 9, 12]


def fy_end_month(ann):
    """The company's financial-year end month, READ OFF the site's own annual table.

    Apr-Mar is the Indian norm, not a law: RAIN closes in December and KENNAMET in June (measured
    2026-08-11 from their annual keys). Assuming Mar would have built the wrong four quarters and
    turned every FY test for those companies into a silent NO-TEST -- which is how an untested cell
    gets reported as a checked one.
    """
    if not ann:
        return 3
    counts = {}
    for k in ann:
        m = (k // 100) % 100
        if m in _LASTDAY:
            counts[m] = counts.get(m, 0) + 1
    return max(counts, key=counts.get) if counts else 3


def qord(qe):
    return (qe // 10000) * 4 + _STEP.index((qe // 100) % 100)


def qde(o):
    return (o // 4) * 10000 + _LASTDAY[_STEP[o % 4]]


def fy_quarters(qe, fem=3):
    """The four quarter-ends of the financial year (ending in month `fem`) containing `qe`."""
    o, i = qord(qe), _STEP.index(fem)
    end = o + ((i - o) % 4)  # first ordinal >= o whose month is the FY end
    return [qde(end - k) for k in (3, 2, 1, 0)], qde(end)


def _close(a, b):
    return abs(a - b) <= max(TOL_ABS, abs(b) * TOL_REL)


def _series(site, sym, con):
    key = (site, sym, con)
    if key not in _ANN:
        _ANN[key] = (A.read(site, sym, con)[0], A.read_annual(site, sym, con)[0])
    return _ANN[key]


def site_fy_identity(site, sym, con, cand, fy, fem=3):
    """A5 for one FY. -> ('OK'|'RESTATED'|'NO-TEST', detail)."""
    q, ann = _series(site, sym, con)
    qs, _ = fy_quarters(fy, fem)
    vals = [(q.get(x) or {}).get(cand) for x in qs]
    target = (ann.get(fy) or {}).get(cand)
    if target is None or any(v is None for v in vals):
        return "NO-TEST", {"fy": fy, "have": sum(v is not None for v in vals), "annual": target}
    s = sum(vals)
    return (
        "OK" if _close(s, target) else "RESTATED",
        {"fy": fy, "site_sum4Q": round(s, 2), "site_annual": target, "diff": round(s - target, 2)},
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--props", required=True)
    ap.add_argument("--out-props")
    ap.add_argument("--out")
    a = ap.parse_args()
    d = json.load(open(a.props))
    props = d["proposals"]
    kept, res = {}, {}

    for key in sorted(props):
        sym, qe, field = key.split("|")
        qe = int(qe)
        p = props[key]
        site, cand = p["chosen"]["site"], p["chosen"]["cand"]
        con = field.endswith("C")
        fem = fy_end_month(_series(site, sym, con)[1])
        qs, fy = fy_quarters(qe, fem)

        a5 = {}
        for tag, f in (("target", fy), ("prev", fy - 10000), ("next", fy + 10000)):
            a5[tag] = site_fy_identity(site, sym, con, cand, f, fem)
        veto = [t for t, (v, _) in a5.items() if v == "RESTATED"]

        ours = G.ours_series(sym, field)
        have = {q: (p["value"] if q == qe else ours.get(q)) for q in qs}
        ann = _ANN[(site, sym, con)][1]
        target = (ann.get(fy) or {}).get(cand)
        if target is None or any(v is None for v in have.values()):
            b = {"verdict": "NO-TEST", "missing": [q for q, v in have.items() if v is None], "site_annual": target}
        else:
            s = sum(have.values())
            b = {
                "verdict": "CONFIRMED" if _close(s, target) else "MISMATCH",
                "sum4Q": round(s, 2),
                "site_annual": target,
                "diff": round(s - target, 2),
            }

        # Gate B is now ENFORCED, not merely recorded. Where we hold the other three quarters of
        # the FY, our own siblings plus the candidate must reproduce the site's annual. It is the
        # §62 different-axis confirmation and it costs nothing; a MISMATCH means the candidate does
        # not fit the financial year it claims to belong to.
        if b["verdict"] == "MISMATCH":
            veto = [*veto, "our-FY-identity"]
        rec = {
            "A5": {t: {"verdict": v, **det} for t, (v, det) in a5.items()},
            "our_fy_identity": b,
            "state": "VETO-RESTATED-FY({})".format(",".join(veto)) if veto else "PASS",
        }
        res[key] = rec
        if not veto:
            q2 = dict(p)
            q2["fy_check"] = rec
            kept[key] = q2
        print(
            "%-26s %-24s A5 target=%s prev=%s next=%s | ourFY=%s"
            % (key, rec["state"], a5["target"][0], a5["prev"][0], a5["next"][0], b["verdict"])
        )

    print("\nkept %d of %d" % (len(kept), len(props)))
    for k, r in sorted(res.items()):
        if r["state"] != "PASS":
            print("  VETO %-24s %s" % (k, r["A5"]))
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1, sort_keys=True)
    if a.out_props:
        d2 = dict(d)
        d2["proposals"] = kept
        d2["fy_checks"] = res
        json.dump(d2, open(a.out_props, "w"), indent=1, sort_keys=True)
        print(f"wrote {a.out_props}")


if __name__ == "__main__":
    main()

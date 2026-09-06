# -*- coding: utf-8 -*-
"""MONEYCONTROL AS A SECOND READER over every cell a campaign WROTE  (2026-08-11, FILL-2018).

§60f says a cell may not be called unfillable until a second independent reader has been tried. The
mirror of that rule is the one this tool implements: **a cell may not be called FILLED until a second
independent reader has been given the chance to contradict it.**

WHY IT EARNED ITS KEEP IMMEDIATELY. The §58 PDF sweep landed FINCABLES 2018-09 revC = 732.20.
Moneycontrol says 713.97. The document settles it (BSE ann 105e065f…, Finolex's Sep-2019 filing,
p8, `Rs. In crore`, column headed `30-Sep-18`):

    Revenue from Operations   715.76  807.74  713.97  1,523.50  1,505.15  3,077.79
    Total Income (I+II)       740.28  829.71  732.20  1,569.99  1,543.48  3,159.43

**732.20 is Total Income, not revenue from operations.** In the extracted text the figures for row I
arrive on a line of their own, *before* the label, while row III carries label and figures together —
so the label matched and the numbers came from the wrong row (§75b's `merge_wrapped` class). No
magnitude screen can see a 2.5% error; §54a's neighbour band is explicitly limited to orders of
magnitude. Only a second reader catches this.

THE ASYMMETRY THAT MAKES THIS SAFE TO ACT ON. §60c rejects a whole MC series for ONE disagreement,
so a rejected series normally tells you nothing. But WHICH cell it disagrees on is information the
gate throws away: when a series reproduces 28-32 of our stored quarters to the paisa and disagrees
on precisely the cell we wrote this session, the indictment is against US (§61a mode 6). A series
that reproduces almost nothing (BPCL 1/32, OIL 0/33 — different entity, basis or unit) indicts
nothing and is reported as such.

  python -X utf8 scripts/fill2020_tools/verify_vs_mc.py [--min-agree 10]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import mc_quarterly_fetch as M                                    # noqa: E402

REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
CODES = os.path.join(HERE, "_mc_codes.json")
OUT = os.path.join(HERE, "_verify_vs_mc_2018.json")
Q2018 = [20180331, 20180630, 20180930, 20181231]
TOL = 0.002


def campaign_cells():
    """Every 2018 cell this campaign wrote, with the route that wrote it."""
    out = {}
    for name, path in (
            ("§58 sweep", os.path.join(SCRIPTS, "_revgap_done.json")),
            ("screener annual (§60d)", os.path.join(SCRIPTS, "annual_derived_fills.json")),
            ("nse xbrl (§54a)", os.path.join(SCRIPTS, "nse_xbrl_rev_fills.json")),
            ("hand-read (§45)", os.path.join(SCRIPTS, "named_rev_cell_fills_2018.json"))):
        try:
            led = json.load(open(path))
        except Exception:
            continue
        for k, v in led.items():
            parts = k.split("|")
            sym, qe = parts[0], parts[1]
            if int(qe) not in Q2018:
                continue
            if name == "§58 sweep":
                for b in ("std", "con"):
                    if (v or {}).get(b, {}).get("rev") is not None:
                        out[(sym, int(qe), b)] = name
            else:
                b = "con" if (len(parts) > 2 and parts[2] in ("con", "revC")) else "std"
                out.setdefault((sym, int(qe), b), name)
    return out


def main():
    min_agree = int(sys.argv[sys.argv.index("--min-agree") + 1]) if "--min-agree" in sys.argv else 10
    revop = json.load(open(REVOP))
    codes = json.load(open(CODES)) if os.path.exists(CODES) else {}
    cells = campaign_cells()

    rows, agree, contradicted, weak, nocover = [], 0, [], [], 0
    for (sym, qe, basis), route in sorted(cells.items()):
        slot = 1 if basis == "con" else 0
        ours = ((revop.get(sym) or {}).get(str(qe)) or [None] * 9)[slot]
        code = codes.get(sym)
        if ours is None or not code:
            nocover += 1
            continue
        s = M.series(code, basis)
        got = s.get(qe)
        if got is None:
            nocover += 1
            continue
        # How much of OUR series does this MC series reproduce, EXCLUDING the cell under test?
        n_ok = n_bad = 0
        for q, r in (revop.get(sym) or {}).items():
            if int(q) == qe or len(r) <= slot or r[slot] is None:
                continue
            mv = s.get(int(q))
            if mv is None:
                continue
            if abs(mv - r[slot]) <= max(0.05, TOL * abs(r[slot])):
                n_ok += 1
            else:
                n_bad += 1
        d = abs(got - ours) / max(abs(ours), 1e-9)
        rec = {"ours": ours, "mc": got, "delta_pct": round(d * 100, 3), "route": route,
               "mc_reproduces": n_ok, "mc_disagrees_elsewhere": n_bad}
        if d <= TOL:
            agree += 1
            rec["verdict"] = "CONFIRMED by a second reader"
        elif n_ok >= min_agree and n_bad == 0:
            rec["verdict"] = ("★ CONTRADICTED — MC reproduces %d of our other quarters exactly and "
                              "disagrees only here; the indictment is against US (§61a mode 6)" % n_ok)
            contradicted.append((sym, qe, basis, rec))
        else:
            rec["verdict"] = ("MC differs but its series is not credible for this company "
                              "(%d reproduced / %d disagreements elsewhere) — no conclusion" % (n_ok, n_bad))
            weak.append((sym, qe, basis, rec))
        rows.append(("%s|%d|%s" % (sym, qe, basis), rec))

    json.dump(dict(rows), open(OUT, "w"), indent=1, sort_keys=True)
    print("campaign-written 2018 cells checked against Moneycontrol: %d" % len(rows))
    print("  CONFIRMED (agree within %.1f%%)          : %d" % (TOL * 100, agree))
    print("  ★ CONTRADICTED (credible series)        : %d" % len(contradicted))
    print("  differs, series not credible            : %d" % len(weak))
    print("  no MC coverage / no code                : %d\n" % nocover)
    for sym, qe, basis, r in contradicted:
        print("  ★ %-12s %d %s  ours %12.2f  mc %12.2f  (%.2f%%)  MC reproduces %d of ours"
              % (sym, qe, basis, r["ours"], r["mc"], r["delta_pct"], r["mc_reproduces"]))
    for sym, qe, basis, r in weak:
        print("    %-12s %d %s  ours %12.2f  mc %12.2f  (%.2f%%)  MC %d ok / %d bad — no conclusion"
              % (sym, qe, basis, r["ours"], r["mc"], r["delta_pct"],
                 r["mc_reproduces"], r["mc_disagrees_elsewhere"]))
    print("\nwrote %s" % os.path.basename(OUT))


if __name__ == "__main__":
    main()

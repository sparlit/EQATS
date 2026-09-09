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
"""Run the aggregator route + gate over a list of open cells and journal the verdicts.

Writes NOTHING into the datasets. Its output is a proposal ledger that apply_agg_fills.py can
apply in about a second -- the split exists because several sessions push these single-line JSONs
all day and the write step has to be short enough to win a rebase race (CLAUDE.md rule 4).

Every cell ends in one of the terminal states of runbook §61b, and the reason is recorded per site:

  FILLED-EXACT / FILLED-ROUNDED   gate passed; precision measured from the anchors
  REJECT-*                        a gate said no -- which one is in the record
  NOT-FOUND                       no site both HAS the quarter and reproduces our series;
                                  reported as not-found-via:<sites>, never as "unfillable" (§0)

It also collects SUSPECT cells: quarters where a gated-out site disagrees with what we store while
agreeing with everything around it -- runbook §61a mode 6, the indictment being against us. Those
are reported, never silently patched (§58d).

  python3 -X utf8 scripts/agg_tools/agg_sweep.py --cells /tmp/open_cells.json --out /tmp/agg.json
  python3 -X utf8 scripts/agg_tools/agg_sweep.py --syms WESTLIFE,GICRE --out /tmp/agg.json
"""
import argparse
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


def open_cells_from_coverage(path, lo, hi):
    d = json.load(open(path))
    out = []
    for r in d["rows"]:
        qe = r["qe"]
        if not (lo <= qe <= hi):
            continue
        for f in ("revS", "revC", "patS", "patC"):
            for s in r.get("who", {}).get(f, []):
                out.append([s, qe, f])
    return out


def suspects_for(sym, field, sites=("mc", "tl")):
    """Quarters where a site disagrees with our stored value -- mode 6 candidates."""
    ours = G.ours_series(sym, field)
    con = field.endswith("C")
    found = []
    for site in sites:
        try:
            series, _ = A.read(site, sym, con)
        except Exception:
            continue
        if not series:
            continue
        for cand in G.FIELD_CANDS[field]:
            hits = [(q, ours[q], series[q][cand]) for q in series if q in ours and series[q].get(cand) is not None]
            if len(hits) < 4:
                continue
            bad = [h for h in hits if G._agree(h[1], h[2]) == "no"]
            # only interesting when the REST of the series lines up -- otherwise it is an
            # entity/basis mismatch, not a bad cell of ours
            if bad and len(bad) <= 3 and len(hits) - len(bad) >= 6:
                for q, mine, theirs in bad:
                    found.append(
                        {
                            "sym": sym,
                            "qe": q,
                            "field": field,
                            "ours": mine,
                            "site": site,
                            "row": cand,
                            "site_val": theirs,
                            "series_agreement": "%d/%d" % (len(hits) - len(bad), len(hits)),
                        }
                    )
                break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells")
    ap.add_argument("--coverage")
    ap.add_argument("--syms")
    ap.add_argument("--sites", default="mc,tl,tt")
    ap.add_argument("--lo", type=int, default=20191231)
    ap.add_argument("--hi", type=int, default=20260331)
    ap.add_argument("--out", default=os.path.join(HERE, "_agg_proposals.json"))
    # suspects_for() used to read mc AND tl for every (sym, field) regardless of --sites, and the
    # Trendlyne read is paced at 10 s (robots.txt) -- so a 432-symbol MC-only sweep spent >1 h on a
    # site it was told not to use. Suspects now follow --sites; --no-suspects skips them outright.
    ap.add_argument("--no-suspects", action="store_true")
    a = ap.parse_args()

    if a.cells:
        cells = json.load(open(a.cells))
    elif a.coverage:
        cells = open_cells_from_coverage(a.coverage, a.lo, a.hi)
    else:
        msg = "need --cells or --coverage"
        raise SystemExit(msg)
    if a.syms:
        want = set(a.syms.split(","))
        cells = [c for c in cells if c[0] in want]
    sites = tuple(a.sites.split(","))

    props, reports, susp = {}, {}, []
    seen_series = set()
    t0 = time.time()
    for i, (sym, qe, field) in enumerate(sorted(cells)):
        key = "%s|%d|%s" % (sym, qe, field)
        val, rep = G.check(sym, int(qe), field, sites=sites)
        reports[key] = rep
        if val is not None:
            props[key] = {
                "value": val,
                "state": rep["state"],
                "chosen": rep["chosen"],
                "corroborated_by": rep["corroborated_by"],
                "sites": {s: v.get("note") for s, v in rep["sites"].items()},
            }
        if (sym, field) not in seen_series and not a.no_suspects:
            seen_series.add((sym, field))
            susp.extend(suspects_for(sym, field, sites=sites))
        print(
            "[%3d/%3d] %-11s %-8d %-4s %-24s %s"
            % (
                i + 1,
                len(cells),
                sym,
                qe,
                field,
                rep["state"],
                rep.get("chosen", {}).get("site", "")
                or "; ".join(v.get("verdict", v.get("note", ""))[:60] for v in rep["sites"].values())[:110],
            )
        )
        sys.stdout.flush()

    json.dump(
        {
            "generated": time.strftime("%Y-%m-%d %H:%M IST"),
            "sites": list(sites),
            "proposals": props,
            "reports": reports,
            "suspects": susp,
        },
        open(a.out, "w"),
        indent=1,
        sort_keys=True,
    )
    n_ok = len(props)
    print("\n%d/%d gated OK -> %s  (%.0fs)" % (n_ok, len(cells), a.out, time.time() - t0))
    by = {}
    for r in reports.values():
        by[r["state"]] = by.get(r["state"], 0) + 1
    for k in sorted(by):
        print("   %-26s %d" % (k, by[k]))
    if susp:
        print("   SUSPECT cells (ours vs a well-agreeing site): %d" % len(susp))


if __name__ == "__main__":
    main()

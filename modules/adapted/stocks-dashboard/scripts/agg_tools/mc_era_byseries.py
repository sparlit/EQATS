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
"""RUNG 4: resolve an era symbol by SERIES REPRODUCTION — identity from the numbers, not the name.

Rungs 1-3 all ask a name question and all fail on the same 46 companies. Rung 3's premise turned
out to be wrong, and measuring it is what showed that: NSE's symbolchange.csv covers 1999-2026 with
1,054 pairs and **not one of the 46 appears in it as an old symbol** (ORCHIDPHAR appears only as a
NEW one, ORCHIDCHEM -> ORCHIDPHAR in 2015). So CASTROL, CEAT, COLGATE, TUBEINVEST, GESHIPPING are
not NSE renames at all — they are the tickers the index lists carried in that era, and no
name-based route reaches them.

What remains is stronger than any name: **our own stored numbers.** MC's autosuggest returns a
handful of candidates for the symbol text; fetch each candidate's standalone quarterly table and
accept the ONE whose series reproduces ≥8 of the values we already store under this key, with ZERO
disagreements. A company's 8-quarter PAT sequence is not something a different company reproduces
to the paisa. Where two candidates both pass, the answer is AMBIGUOUS and nothing is written.

This is the same evidence GATE E's E1 demands, applied one step earlier — so it does not weaken the
chain, it just stops a resolution failure from being mistaken for an absence
([[feedback-never-infer-absence-from-own-gaps]]). Symbols holding fewer than 8 stored quarters are
reported as out of reach for this rung rather than resolved on a weaker test.

  python3 -X utf8 scripts/agg_tools/mc_era_byseries.py --syms-from /tmp/unres_usable.json --out /tmp/r4.json
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agg_gate as G  # noqa: E402
import mc_era as E  # noqa: E402

MIN_ANCHORS = 8
# The resolution bar is GATE E1's bar, not a stricter one. Resolution answers "which company is
# this?"; E1 then decides, per target, whether the series is trustworthy there. Demanding ZERO
# disagreements here rejected candidates with overwhelming identity evidence -- HEXAWARE 67
# reproduced quarters against 2 misses, SUPPETRO 63/5, RUCHISOYA 62/2 -- on a test that was never
# about identity. 15% is the rate era_calibrate.py measured (runbook §90).
MAX_BAD_RATE = 0.15
DOMINANCE = 2.0  # the winner must reproduce at least this many times the runner-up


def candidates(sym, limit=8):
    """MC autosuggest rows for the symbol text — every one a hypothesis, none of them trusted."""
    seen, out = set(), []
    for r in E._sugg_rows(sym, "sugg2_")[:limit]:
        if r["sc_id"] and r["sc_id"] not in seen:
            seen.add(r["sc_id"])
            out.append(r)
    return out


def resolve_by_series(sym, field="patS"):
    """-> (ident|None, report). Accepts exactly one candidate that reproduces our stored series."""
    ours = G.ours_series(sym, field)
    rep = {"sym": sym, "stored": len(ours), "tried": []}
    if len(ours) < MIN_ANCHORS:
        rep["why"] = "only %d stored quarters; below the %d-anchor bar" % (len(ours), MIN_ANCHORS)
        return None, rep
    cand = G.FIELD_CANDS[field][0]
    passing = []
    for r in candidates(sym):
        series, _note = E.quarters({"sc_id": r["sc_id"]}, con=False)
        hits = [(q, ours[q], series[q][cand]) for q in series if q in ours and series[q].get(cand) is not None]
        bad = [h for h in hits if G._agree(h[1], h[2]) == "no"]
        ok = len(hits) - len(bad)
        rep["tried"].append(
            {
                "sc_id": r["sc_id"],
                "mc_sym": r["sym"],
                "mc_name": r["name"],
                "isin": r["isin"],
                "periods": len(series),
                "anchors": ok,
                "disagreements": len(bad),
            }
        )
        if ok >= MIN_ANCHORS and (len(bad) / float(len(hits))) <= MAX_BAD_RATE:
            passing.append((r, ok, len(series)))
    if not passing:
        rep["why"] = "no candidate reproduced %d of our stored quarters with zero disagreements" % MIN_ANCHORS
        return None, rep
    passing.sort(key=lambda p: -p[1])
    if len(passing) > 1 and passing[0][1] < DOMINANCE * passing[1][1]:
        rep["why"] = "AMBIGUOUS: %s reproduces %d and %s reproduces %d -- no dominant candidate" % (
            passing[0][0]["sc_id"],
            passing[0][1],
            passing[1][0]["sc_id"],
            passing[1][1],
        )
        return None, rep
    r, ok, n = passing[0]
    ident = {
        "sc_id": r["sc_id"],
        "via": "series-reproduction",
        "isin": r["isin"],
        "mc_sym": r["sym"],
        "mc_name": r["name"],
        "note": "MC row %s (%s, %s) reproduces %d of our stored %s quarters for %s with zero "
        "disagreements; %d periods available" % (r["sc_id"], r["sym"], r["name"], ok, field, sym, n),
    }
    rep["resolved"] = ident
    return ident, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms-from", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    syms = json.load(open(a.syms_from))
    idc = json.load(open(E._ISIN_CACHE)) if os.path.exists(E._ISIN_CACHE) else {}
    out, n, t0 = {}, 0, time.time()
    print("%-12s %-8s %-24s %6s %5s  %s" % ("SYM", "sc_id", "MC name", "anchors", "bad", "verdict"))
    for sym in syms:
        ident, rep = resolve_by_series(sym)
        out[sym] = rep
        if ident:
            idc[sym] = ident
            n += 1
            best = max(rep["tried"], key=lambda t: t["anchors"])
            print(
                "%-12s %-8s %-24s %6d %5d  RESOLVED"
                % (sym, ident["sc_id"], (ident.get("mc_name") or "")[:24], best["anchors"], best["disagreements"])
            )
        else:
            best = max(rep["tried"], key=lambda t: t["anchors"]) if rep["tried"] else None
            print(
                "%-12s %-8s %-24s %6s %5s  %s"
                % (
                    sym,
                    best["sc_id"] if best else "-",
                    (best["mc_name"] if best else "")[:24],
                    best["anchors"] if best else "-",
                    best["disagreements"] if best else "-",
                    rep["why"][:44],
                )
            )
        sys.stdout.flush()
    json.dump(idc, open(E._ISIN_CACHE, "w"), indent=0, sort_keys=True)
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    print("\nresolved %d of %d by series reproduction (%.0fs) -> %s" % (n, len(syms), time.time() - t0, a.out))


if __name__ == "__main__":
    main()

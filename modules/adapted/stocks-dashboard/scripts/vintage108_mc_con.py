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
"""A SECOND READER FOR THE CONSOLIDATED BASIS — Moneycontrol, with the §85 fallback guard.

BSE's detailed-results JSON is STANDALONE-ONLY (§42), so every consolidated finding in this
campaign has exactly one reader: NSE's archive. One reader is a reading, not a fact (§58), and the
§109d rule — evidence AND no available reader may contradict — needs a second voice before a con
cell is healed. Moneycontrol's deep feed is that voice.

⚠️ THE §85 DEFECT MAKES MC'S CON TABLE UNUSABLE WITHOUT A GUARD: for companies with no
consolidated filing, MC's consolidated table silently FALLS BACK to the standalone numbers, and
every ratio/scale gate passes on it. So the con reading is only accepted when it DIFFERS from the
same feed's standalone reading for the same quarter. Where they are identical the cell is reported
`mc-con-is-std-fallback` — an absence of evidence, never evidence of agreement.

VERDICTS per cell:
  ⚠️ THE READING IS OWNERS-BASIS. NSE's consolidated page bottom line is NOT the owners figure
  (§111d), so a con target is trusted only when an OWNERS reader reproduces it.
  mc-backs-nse-as-filed   the owners reader agrees with NSE's earliest vintage, not the store
  mc-backs-store          MC agrees with the STORE -> do NOT heal; NSE's page needs re-reading
  mc-backs-neither        three readings, three answers -> adjudicate by hand
  mc-con-is-std-fallback / no-mc-id / no-mc-quarter   the route is absent, which is not a verdict

OUT: scripts/_vintage108_mccon.json
RUN: python3 scripts/vintage108_mc_con.py [--limit N] [--only SYM,SYM]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import contextlib

import agg_sources  # noqa: E402

NSE_CON = os.path.join(HERE, "_vintage108_nse_con.json")
OWNERS_XBRL = {}
with contextlib.suppress(Exception):
    OWNERS_XBRL = json.load(open(os.path.join(HERE, "_reattr_owners.json"), encoding="utf-8"))
PROPS = os.path.join(HERE, "_vintage108_proposals.json")
OUT = os.path.join(HERE, "_vintage108_mccon.json")
ABS_TOL, REL_TOL = 2.0, 0.03


def agree(a, b):
    return a is not None and b is not None and abs(a - b) <= max(ABS_TOL, abs(b) * REL_TOL)


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None

    nse = json.load(open(NSE_CON, encoding="utf-8"))
    bp = json.load(open(PROPS, encoding="utf-8"))["byproduct"]
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    for k in [k for k, v in out.items() if v.get("verdict", "").startswith("transport")]:
        del out[k]

    targets = []
    for cls, items in bp.items():
        for x in items:
            sym, qe, basis = x.split("|")
            if basis != "con" or (only and sym not in only):
                continue
            k = f"{sym}|{qe}"
            if k not in out and k in nse:
                targets.append((sym, int(qe), k, cls))
    targets = targets[:limit]
    print("consolidated cells needing a second reader: %d" % len(targets))

    cache, n = {}, 0
    for sym, qe, k, cls in targets:
        if sym not in cache:
            try:
                con, cnote = agg_sources.mc_quarters(sym, True)
            except Exception as ex:
                con, cnote = {}, f"exception {type(ex).__name__}"
            try:
                std, snote = agg_sources.mc_quarters(sym, False)
            except Exception:
                std, snote = {}, "exception"
            cache[sym] = (con, std, cnote, snote)
        con, std, cnote, snote = cache[sym]
        v = nse[k]
        rec = {
            "sym": sym,
            "qe": qe,
            "class": cls,
            "stored": v["stored"],
            "nse_as_filed": v.get("as_filed"),
            "mc_note": cnote,
        }
        # ★ OWNERS, NOT TOTAL. Our con PAT slot holds OWNERS-ATTRIBUTABLE profit (§profit-basis).
        # This read `pat_total` and so compared a TOTAL-basis reader against the NSE archive page's
        # bottom line — which is also not the owners figure (§111d) — two total-basis voices
        # agreeing, and 85 cells written onto the wrong basis before an owners reader caught it
        # (BHARTIARTL Mar-2017: store 373.40 = owners, the heal wrote 219.80 = total).
        # The DEFINITIONAL reader wins where it reaches: _reattr_owners.json is built from the
        # filings' XBRL ProfitOrLossAttributableToOwnersOfParent. MC's `pat_own` is the fallback.
        # `pat_total` survives only as the §85 std-fallback probe, which is a same-basis test.
        mc = OWNERS_XBRL.get("%s|%d" % (sym, qe))
        mc_src = "XBRL owners"
        if mc is None:
            mc = (con.get(qe) or {}).get("pat_own")
            mc_src = "MC pat_own"
        mcs = (std.get(qe) or {}).get("pat_total")
        mc_tot = (con.get(qe) or {}).get("pat_total")
        rec["mc_con"], rec["mc_std"] = mc, mcs
        rec["owners_src"], rec["mc_con_total"] = (mc_src if mc is not None else None), mc_tot
        if mc is None:
            rec["verdict"] = "no-mc-quarter" if con else "no-mc-id"
        elif mc_src == "MC pat_own" and mcs is not None and mc_tot is not None and abs(mc_tot - mcs) < 0.011:
            rec["verdict"] = "mc-con-is-std-fallback"  # §85 — absence, not agreement
        else:
            a, st = v.get("as_filed"), v["stored"]
            if agree(mc, a) and not agree(mc, st):
                rec["verdict"] = "mc-backs-nse-as-filed"
            elif agree(mc, st) and not agree(mc, a):
                rec["verdict"] = "mc-backs-store"
            elif agree(mc, a) and agree(mc, st):
                rec["verdict"] = "mc-cannot-separate"
            else:
                rec["verdict"] = "mc-backs-neither"
        out[k] = rec
        n += 1
        if n % 25 == 0:
            json.dump(out, open(OUT, "w"), indent=1)
            print("  .. %d/%d" % (n, len(targets)))
    json.dump(out, open(OUT, "w"), indent=1)
    from collections import Counter

    print("done: %d cells" % n)
    for kk, c in Counter(x.get("verdict") for x in out.values()).most_common():
        print("   %-26s %d" % (kk, c))


if __name__ == "__main__":
    main()

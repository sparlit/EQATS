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
"""RETROSPECTIVE screen for Moneycontrol's CONSOLIDATED FALLBACK, over cells already WRITTEN.

THE DEFECT (found by the 2019 session, 2026-08-11). Moneycontrol serves a `cons_quarterly` table for
a company even in quarters where NO consolidated result was filed, and in those quarters the row
carries the STANDALONE figure. Writing it manufactures a consolidated number that is really the
standalone one — the §67 con-copy class, arriving through an aggregator instead of through our own
earlier passes.

WHY THE SERIES GATE CANNOT SEE IT. The §60c gate proves MC's consolidated series IS this company's
consolidated series, by reproducing our stored con values elsewhere — and it does, correctly, often
on 26-32 quarters. The fallback is PER QUARTER inside a series that is otherwise right. Every other
guard passes too: the anchor, the magnitude band, the cross-basis gate.

WHY 2018 IS THE WORST CASE. Consolidated quarterlies became compulsory only from FY2020 (§51a), so
pre-2020 is exactly where companies filed standalone-only — exactly where MC has nothing real to
serve and falls back. This campaign's 725 con cells sit entirely in that window.

THE DISCRIMINATOR (no fetch; uses only our own store):

    written con is BYTE-EQUAL to our stored std for the SAME quarter
      AND the company's own history shows con != std in ANY other quarter
        -> HOLD. It consolidates differently, so an identical figure here is the source repeating
           standalone.
    written con is byte-equal, and the company NEVER shows con != std anywhere
        -> KEEP. Genuine no-consolidation-difference (the MOIL / CHENNPETRO / SCI shape).

★ THE STRONGER TEST, and the one to prefer when the source can be re-read (2019 session, 2026-08-11):
compare the SOURCE's consolidated row against the SOURCE'S OWN standalone row, SAME QUARTER, SAME
LABEL, judging each FIELD on its own row.
    differs   -> a genuine consolidated table FOR THAT FIELD. Writable.
    identical -> UNRESOLVED. Not writable and NOT proven a fallback — a company whose subsidiaries
                 are equity-accounted files consolidated revenue EQUAL to standalone while its
                 profit differs (the MOIL/CHENNPETRO shape), and that is indistinguishable from a
                 copy at the aggregator. Settle it from the FILING, not the aggregator.
⚠️ Neither a differing PAT nor the presence of a "Net P/L After M.I & Associates" row proves a
genuine table: GAYAPROJ 2019-03 and PIIND 2019-03 are PROVEN fallbacks and show both.

⚠ THIS IS STRICTER THAN `screen_crossbasis_2018.py`, WHICH THIS CAMPAIGN ALREADY RAN. That screen
cleared a cell when its con==std neighbours outnumbered the differing ones, and reasoned about
regime changes for the mixed cases. Under the rule above, ANY differing quarter is disqualifying —
so cells this campaign cleared as "company convention" on a mixed history must be re-adjudicated.

  python -X utf8 scripts/fill2020_tools/mc_con_fallback_retro_2018.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
TARGETS = os.path.join(HERE, "_rev2018_targets.json")
MC_LEDGER = os.path.join(SCRIPTS, "mc_quarterly_fills.json")
OUT = os.path.join(HERE, "_mc_fallback_retro_2018.json")
# DOCUMENT-PROVEN EXEMPTIONS. A cell leaves this screen ONLY on primary evidence that the company's
# consolidated revenue really does equal its standalone in the target era — never on a plausibility
# argument, and never because the differences happen to fall after the target (that test is CIRCULAR
# here: our pre-2019 consolidated coverage is exactly what this campaign is filling, so there can be
# no differing quarters before a 2018 target by construction).
EXEMPT = {
    "FINCABLES|20180930": "BSE ann 105e065f… (Finolex Sep-2019 filing): the STANDALONE statement on "
    "p3 and the CONSOLIDATED statement on p8 print the IDENTICAL revenue row "
    "715.76 / 807.74 / 713.97 / 1,523.50 / 1,505.15 / 3,077.79, differing only "
    "in Other Income (std total income 772.39 vs con 740.28). Two separate "
    "statements in one filing, so con revenue == std revenue is proven, not "
    "inferred.",
}
# ★ A FALLBACK IS A BYTE COPY — TEST FOR EXACT EQUALITY, NOT A BAND.
# This was 0.001 (0.1% RELATIVE), which on a 3,000-crore value is 3 crore of slack. It admitted 7 of
# the 28 cells this screen retracted on 2026-08-11 as "equal to our standalone" when they were 0.03
# to 0.69 apart — SHREECEM 3,070.15 vs 3,069.91, COCHINSHIP 717.11 vs 716.42, SJVN 484.46 vs 484.49.
# A source repeating the standalone row repeats it EXACTLY; a difference of any size is evidence of a
# real consolidated table. All 6 testable ones were restored (§85a).
EQ_ABS = 0.005  # "byte-equal to our standalone"
DIFF_REL = 0.01  # "this company consolidates differently"


def main():
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP))
    targets = json.load(open(TARGETS))
    mc = json.load(open(MC_LEDGER))

    hold, keep, notflag = [], [], 0
    for sym, v in sorted(targets.items()):
        rows = revop.get(sym) or {}
        # the company's OWN history: does it ever consolidate differently?
        diff_qs = []
        for q, r in rows.items():
            if len(r) > 1 and r[0] not in (None, 0) and r[1] is not None:
                if abs(r[1] - r[0]) > DIFF_REL * abs(r[0]):
                    diff_qs.append(q)
        for qe in v.get("revC", []):
            r = rows.get(str(qe))
            if not r or len(r) < 2 or r[1] is None or r[0] in (None, 0):
                continue
            written_by_mc = ("%s|%d|con" % (sym, qe)) in mc
            if abs(r[1] - r[0]) > EQ_ABS:
                notflag += 1
                continue  # con != std here: not the fallback shape
            rec = {
                "con": r[1],
                "std": r[0],
                "by_moneycontrol": written_by_mc,
                "company_quarters_where_con_differs": len(diff_qs),
                "examples": sorted(diff_qs)[:4],
            }
            if k_exempt := EXEMPT.get("%s|%d" % (sym, qe)):
                rec["verdict"] = "KEEP — document-proven: " + k_exempt
                keep.append(("%s|%d" % (sym, qe), rec))
                continue
            if diff_qs:
                rec["verdict"] = (
                    "HOLD — this company consolidates differently in %d of its own "
                    "quarters, so a figure identical to standalone here is the "
                    "aggregator repeating the standalone row" % len(diff_qs)
                )
                hold.append(("%s|%d" % (sym, qe), rec))
            else:
                rec["verdict"] = (
                    "KEEP — this company NEVER shows con != std anywhere in its stored "
                    "history, so con == std is its real convention"
                )
                keep.append(("%s|%d" % (sym, qe), rec))

    print("2018 con cells written and currently equal to our stored standalone:")
    print("  HOLD (company consolidates differently elsewhere): %d" % len(hold))
    print("  KEEP (no consolidation difference anywhere)       : %d" % len(keep))
    print("  con != std, not the fallback shape                : %d\n" % notflag)
    for k, r in hold:
        print(
            "  HOLD %-22s con %12.2f == std   differs in %2d other quarters %s  [mc=%s]"
            % (k, r["con"], r["company_quarters_where_con_differs"], r["examples"][:2], r["by_moneycontrol"])
        )
    for k, r in keep:
        print("  keep %-22s con %12.2f == std   (never differs)  [mc=%s]" % (k, r["con"], r["by_moneycontrol"]))
    json.dump({"hold": dict(hold), "keep": dict(keep)}, open(OUT, "w"), indent=1, sort_keys=True)

    if not apply_it:
        print("\nDRY RUN — nothing retracted.")
        return
    for path in (REVOP, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for k, _r in hold:
            sym, qe = k.split("|")
            row = (d.get(sym) or {}).get(qe)
            if row and len(row) > 1 and row[1] is not None:
                row[1] = None  # retract: a hole beats a manufactured figure
                d[sym][qe] = row
                n += 1
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("retracted %d cells from %s" % (n, os.path.basename(path)))
    led = json.load(open(MC_LEDGER))
    for k, r in hold:
        key = f"{k}|con"
        if key in led:
            led[key]["held"] = r["verdict"]
    json.dump(led, open(MC_LEDGER, "w"), indent=1, sort_keys=True)
    print("annotated the moneycontrol ledger with `held` (nothing deleted)")


if __name__ == "__main__":
    main()

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
"""Detect (and optionally repair) backfilled cells that went missing from the SERVED payloads.

WHY THIS EXISTS. On 2026-08-06 a backfill pushed 193 consolidated-revenue cells; ten minutes later
a CI refresh restored its own pre-run snapshot over docs/sf_revop.json and silently reverted every
one of them. The values were never lost -- scripts/revop_fundamentals.json (the ledger) still held
them, because CI does not commit the scripts/ mirrors -- but the site served nulls, and the push
had been reported as successful because it WAS verified against origin at push time.

Two defences came out of that. The cause is fixed in scripts/ci_preserve_merge.py (CI now does a
three-way merge instead of a blind copy). This is the detector: it re-checks, against whatever the
payloads currently say, that every cell any fill ledger claims is still there. Run it after a push
and again once a refresh cycle has passed -- "verified at push time" is NOT verified (CLAUDE.md
rule 5, runbook §41).

Compares each ledger's claimed cells against docs/sf_revop.json and docs/sf_fundamentals.json:
  MISSING  = ledger has a value, the served payload has None      -> a clobber; --repair restores it
  DRIFT    = both present but different                           -> reported, NEVER auto-changed,
             because a later correction legitimately supersedes a backfill and only a human can say

Run:  python3 scripts/verify_fills_live.py [--repair] [--quiet]
Exit code 1 when anything is MISSING (so CI or a wrapper can fail loudly), else 0.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")

# ledger -> (payload, value-key in the ledger entry, slot/field)
#   revop slots: 0 revS, 1 revC   |   fundamentals row idx: 1 stdPAT, 3 conPAT
LEDGERS = [
    ("nosub_rev_pre2020_fills.json", "revop", "revC", 1),
    ("con_rev_nse_reads.json", "revop", "revC", 1),
    ("std_rev_detres_fills.json", "revop", "revS", 0),
    ("std_rev_nse_reads.json", "revop", "revS", 0),
    ("nosub_rev_fills.json", "revop", "revC", 1),
    ("nosub_pat_fills.json", "fund", "con", 3),
    ("std_pat_detres_fills.json", "fund", "std", 1),
    ("con_pat_nse_reads.json", "fund", "con", 3),
    ("con_pat_fy_derived.json", "fund", "con", 3),
    # sf_revop patS is a MIRROR of npStd (§70); this ledger holds every mirror value fixed or
    # confirmed by the 2026-08-10 std-PAT adjudication (46 cells), so a rebuild that re-lands a
    # poisoned XBRL parse (wrong-year OneD, H1-as-quarter, double-indexed Mar-2019 files) trips here.
    ("stdpat_mirror_heals.json", "revop", "patS", 4),
    # hand-read named cells (§57/§58): keyed SYM|QE with the whole anchor chain journalled beside
    # the value. A file is listed once per slot it can carry.
    ("named_rev_cell_fills.json", "revop", "revS", 0),
    # revC on this file was UNGUARDED until 2026-08-10 — 15 hand-read consolidated-revenue cells
    # (AIIL/BALKRISIND/CGPOWER/CYIENT/INDUSINDBK×4/KNRCON/MCX×2/NMDC/SWANCORP/TIMKEN/WAAREEENER)
    # sat in the ledger with nothing re-checking them after a refresh. All 15 verified present at
    # registration time.
    ("named_rev_cell_fills.json", "revop", "revC", 1),
    ("named_rev_cell_fills_2019.json", "revop", "revC", 1),
    ("named_rev_cell_fills_2019.json", "revop", "revS", 0),
    # hand-read PAT cells that no quarter-keyed index serves (§57/§58), keyed SYM|QE with the whole
    # anchor chain beside the value — the PAT counterpart of named_rev_cell_fills.json. HALDER's
    # Jun/Sep-2025 rows are the first entries: the scrip is BSE-first and BOTH NSE endpoints skip
    # those quarters, so nothing but this ledger would notice them going missing again.
    ("named_pat_cell_fills.json", "fund", "std", 1),
    ("named_pat_cell_fills.json", "fund", "con", 3),
    # aggregator route (runbook §81): Moneycontrol / Trendlyne quarterly-results feeds. Every cell
    # is gated on that site's own series reproducing >=2 of our stored quarters with zero local
    # disagreements, AND on the site's own four quarters summing to its own annual for the target
    # FY and both neighbours. Registered at creation time so this ledger never joins the class that
    # sat unguarded for weeks (see the named_rev_cell_fills revC note above).
    ("agg_cell_fills.json", "revop", "revS", 0),
    ("agg_cell_fills.json", "revop", "revC", 1),
    # ★ op / ebit on the SAME ledger were UNREGISTERED until 2026-09-05: the 2026-08-12 op/ebit
    # sweep (commit 6b7c1a302) journalled opS/opC/ebitS/ebitC cells here and nothing re-checked
    # them after a refresh — the exact "std"-only class described under agg_pat_cell_fills below.
    # Checked-count delta at registration: measured and recorded in the commit that added these.
    ("agg_cell_fills.json", "revop", "opS", 2),
    ("agg_cell_fills.json", "revop", "opC", 3),
    ("agg_cell_fills.json", "revop", "ebitS", 7),
    ("agg_cell_fills.json", "revop", "ebitC", 8),
    # EBIT-IN-OP-SLOT corrections (runbook §129g, apply_op_slot_heal.py, user decision 2026-09-05):
    # ebitS = the after-dep value moved out of the op slot; opS = gated or derived op. Entries whose op
    # could not be re-derived carry `opS_refused` + `held`, so the old value RESURRECTING in slot 2 is
    # the failure (a fill-only replay of the original OCR/detres reads would do exactly that).
    ("op_slot_corrections.json", "revop", "ebitS", 7),
    ("op_slot_corrections.json", "revop", "opS", 2),
    # the ABSENCE half lives in its own file: `held` is read per ENTRY across every key registered for a
    # ledger, so a record asserting ebitS present AND opS_refused absent flagged its own ebit as
    # RESURRECTED (166 false alarms on the first local run, 2026-09-05)
    ("op_slot_refused.json", "revop", "opS_refused", 2),
    # PRE-2015 standalone PAT from the same route (2026-08-12). Separate ledger because it writes a
    # different file (docs/sf_fundamentals.json slot 1) through its own applier, and because these
    # cells are the oldest in the dataset — the era CI never rebuilds, so a clobber here would be
    # silent for years. Registered at creation time.
    ("agg_pat_cell_fills.json", "fund", "std", 1),
    # ★ AND THE con KEY. UNREGISTERED until 2026-08-13, and the ledger was NOT new: it already held
    # 278 patC entries (ACC and ADANIENT 2009 among them) that nothing had ever re-checked. The
    # entry loop skips any record whose registered key is absent (`key not in v: continue`), so a
    # "std"-only registration reports a serene MISSING 0 for a ledger full of consolidated cells —
    # a guard that checks nothing looks exactly like a guard that found nothing.
    # ★ THE ASSERTION IS THE CHECKED COUNT, MEASURED BOTH WAYS, not the absence of complaints:
    #   without this line  10,485 ledgered cells checked
    #   with it            10,767   (+282 = 278 pre-existing patC + the 4 con cells written today)
    # (memory: feedback-ledger-guard-count-must-move.)
    ("agg_pat_cell_fills.json", "fund", "con", 3),
    # CORRECTIONS, not fills (§90g): a stored pre-2015 npStd the site's own FY identity indicted
    # and gate H replaced. A clobber here does not lose a backfill, it silently RESTORES a value
    # the identity refuted — the pat_defects class. Registered at creation time.
    ("era_pat_corrections.json", "fund", "std", 1),
    # rev-parity 2026-09-05: standalone REVENUE read off the WAYBACK-archived NSE results.jsp page (the same
    # as-filed document that produced the std-PAT cell), direct quarter or cumulative-differenced, both
    # anchored on the page's own Net Profit == stored npStd to the paisa. Registered at creation.
    ("wayback_nse/wb_rev_fills.json", "revop", "revS", 0),
    # rev-parity 2026-09-05: the BSE sibling -- Wayback capture of bseindia.com/qresann/result.asp, PAT anchored,
    # revenue line chosen by reproduction against the symbol's own held quarters (bse_rev.py). Registered at creation.
    ("wayback_nse/bse_rev_fills.json", "revop", "revS", 0),
]
# BASIS-IN-KEY ledgers: "SYM|QE|basis", not "SYM|QE" — the flat loop above would rsplit the BASIS
# off as the quarter and check nothing. These were UNGUARDED until 2026-08-10: nse_xbrl_rev_fills
# alone holds 154 cells that nothing re-checked after a refresh. Entries carrying "held" are
# candidates the reader REFUSED to write (§58d), so they assert nothing and are skipped.
BASIS_KEYED = [
    ("nse_xbrl_rev_fills.json", "revop", "rev"),
    ("deoverlay_rev_fills2019.json", "revop", "rev"),
    # §55 insurer consolidated revenue read out of the filing PDF. UNGUARDED until 2026-08-11 —
    # 52 cells (HDFCLIFE/ICICIPRULI/NIACL/GICRE) sat in this ledger with nothing re-checking them
    # after a refresh, the same gap the named_rev_cell_fills revC note above describes.
    ("insurer_con_rev_fills.json", "revop", "rev"),
    # Moneycontrol quarterly (runbook §81). The 2018 campaign's single biggest route — 184 cells,
    # each gated on MC's own series reproducing >=3 of our stored quarters on the SAME basis with
    # ZERO disagreements. Registered at creation time rather than after the fact.
    ("mc_quarterly_fills.json", "revop", "rev"),
    # screener FY-annual derivations (§60d). UNGUARDED until 2026-08-11 despite holding 213 cells
    # across three campaigns — the same gap the named_rev_cell_fills revC note above describes.
    ("annual_derived_fills.json", "revop", "revC"),
    # hand-read 2018 cells (§45/§57/§58): HINDALCO's two, one of them a RETRACTION of a value this
    # campaign itself wrote off a digit-fused text layer (§83), so a clobber here would restore a
    # number a filing has already refuted.
    ("named_rev_cell_fills_2018.json", "revop", "revC"),
    # ★ THE MONEYCONTROL WHOLE-HISTORY LEDGERS (§85), 2,598 revenue + 1,832 PAT entries, and they
    # were UNREGISTERED until 2026-08-11 — the single largest unguarded block this detector has had.
    # The 2018 session found them the hard way: it retracted two fallback cells, and they came back
    # live because these ledgers claimed the same cells with held=False. Registered at both ends now
    # (the value must persist AND a held cell must stay absent — see the resurrection check below).
    ("mc_history_fills.json", "revop", "rev"),
    ("mc_pat_fills.json", "fund", "pat", {"std": 1, "con": 3}),
    # §86 FY-identity route — cells our ANCHOR gate could never reach (<6 stored quarters on the
    # basis), gated instead on Moneycontrol's own quarters summing to its own annual. Registered at
    # creation this time rather than discovered unguarded weeks later, which is the whole lesson of
    # the mc_history/mc_pat gap above.
    ("mc_fyident_fills.json", "revop", "rev"),
    # ★ conpat_filing_fills.json — the 2026-08-16 "lastmile-classC" route: consolidated PAT read
    # straight out of the filing (per-basis NSE XBRL, or the results-data row where no XBRL was
    # filed) for quarters mc_pat_fills had HELD. It shipped UNREGISTERED in f24388563/6ae9d2a81,
    # which is the exact gap the mc_history/mc_pat note above was written about: these six cells
    # are the ones that settle a contradiction between two other ledgers, so a clobber here would
    # re-open it silently. Two registrations because the ledger carries both fields under different
    # key shapes — the PAT entries are "SYM|QE|con" with value key "con", and the one revenue entry
    # is "SYM|QE|con_rev" with value key "rev_con". Each registration skips the other's entries
    # (the loop `continue`s when the registered value-key is absent or the basis token is unmapped),
    # so neither silently checks nothing.
    ("conpat_filing_fills.json", "fund", "con", {"con": 3}),
    ("conpat_filing_fills.json", "revop", "rev_con", {"con_rev": 1}),
    # ★ con_nofile_retractions.json (2026-08-18) — con cells for quarters with NO consolidated
    # filing at all. EVERY entry carries `held`, so all four registrations feed the resurrection
    # check below and nothing here asserts presence. This is the ledger's whole point: the cells
    # differ from their standalone twin, so purge_copied_con.py's equality test can never re-null
    # them, and the writer that produced them is still active (HUHTAMAKI's 20241231 duplicate
    # landed two weeks after the other 21). Four registrations because sf_revop carries four con
    # fields in different slots and BASIS_SLOT maps only the revenue pair; each one skips the
    # other three fields' entries, so none of them silently checks nothing.
    ("con_nofile_retractions.json", "revop", "was", {"revC": 1}),
    ("con_nofile_retractions.json", "revop", "was", {"opC": 3}),
    ("con_nofile_retractions.json", "revop", "was", {"patC": 5}),
    ("con_nofile_retractions.json", "revop", "was", {"ebitC": 8}),
]
# "revS"/"revC" are accepted as basis tokens alongside "std"/"con": several ledgers key their third
# part by FIELD rather than by BASIS, and the loop below silently `continue`s on any token it cannot
# map — so annual_derived_fills.json (213 cells) and named_rev_cell_fills_2018.json would have LOOKED
# registered while checking nothing at all. A monitor that silently monitors nothing is worse than
# no monitor, because it reports "MISSING 0".
BASIS_SLOT = {"std": 0, "con": 1, "revS": 0, "revC": 1}
# NESTED ledgers: {SYM: {QE: {...}}} rather than the flat "SYM|QE" shape above. The defect ledgers
# carry CORRECTIONS (a value we proved wrong and replaced), so a clobber there does not merely lose
# a backfill -- it silently restores a number a filing already refuted. The basis is read per entry
# where the ledger records one. `root` (when set) names the top-level key holding the SYM map:
# con_nofile_identity_fills.json (the FILL-2020 identity-fill journal, con = std where NSE's filing
# index proves no consolidated result exists) wraps its SYM map in campaign metadata under "fills".
# Only its revC maps into this detector's scope -- opC/ebitC have no slot in the checked payloads.
#   (file, payload, value-key, default slot, basis-key, {basis: slot}, root)
NESTED = [
    ("pat_defects.json", "fund", "correct_pat", 1, None, None, None),
    ("pat_defects.json", "fund", "correct_pat_con", 3, None, None, None),
    ("rev_defects.json", "revop", "correct_rev", 0, "basis", {"std": 0, "con": 1}, None),
    ("con_nofile_identity_fills.json", "revop", "revC", 1, None, None, "fills"),
]
TOL = 0.011


def main():
    repair = "--repair" in sys.argv
    quiet = "--quiet" in sys.argv
    revop = json.load(open(REVOP))
    fund = json.load(open(FUND))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    missing, drift, checked = [], [], 0
    odd_keys = []  # ledger keys that are not quarters (e.g. _RETRACTED_*, _note)
    # ★ RESURRECTED: a cell some reader REFUSED to write is live again with exactly the refused
    # value. This class was invisible to every detector until 2026-08-11, and it is the mirror image
    # of MISSING: MISSING asks "is the value we asserted still there?", and a held cell asserts the
    # opposite — that the value must NOT be there. A fill-only applier is enough to resurrect one,
    # because fill-only only promises never to overwrite; it promises nothing about a slot that a
    # retraction deliberately emptied. Measured the day it was added: the 2018 session retracted
    # SHREECEM 2018-06 and SYNGENE 2018-03 as Moneycontrol consolidated-fallback, both came back
    # from sibling ledgers, and this detector reported MISSING 0 throughout.
    resurrected = []
    # ★ REVERTED: a value-correction ledger says a cell was moved `was` -> `fixed`, and the payload
    # holds `was` again — EXACTLY the value the correction replaced. That is not DRIFT: drift means
    # somebody adjudicated a THIRD number and a human must choose; reverted means the heal was
    # simply undone, by a rebuild that derives the cell and wins the three-way merge (§109j). The
    # two need different names because they need different responses — one is auto-repairable from
    # the ledger, the other must never be auto-anything. They were indistinguishable until
    # 2026-08-25: every §109j revert was landing in the DRIFT bucket, where "superseded/corrected"
    # reads like somebody's decision rather than a clobber.
    reverted = []

    def live_value(payload, sym, qe, slot):
        row = (revop.get(sym) or {}).get(str(qe)) if payload == "revop" else (fmap.get(sym) or {}).get(int(qe))
        return row[slot] if row and len(row) > slot else None

    for entry in BASIS_KEYED:
        name, payload, key = entry[0], entry[1], entry[2]
        slotmap = entry[3] if len(entry) > 3 else BASIS_SLOT
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            continue
        try:
            led = json.load(open(p))
        except Exception:
            continue
        for k, v in led.items():
            parts = k.split("|")
            if len(parts) != 3 or not isinstance(v, dict):
                continue
            if v.get("skip") or v.get(key) is None:
                continue
            sym, qe, basis = parts
            slot = slotmap.get(basis)
            if slot is None:
                continue
            want = v[key]
            cur = live_value(payload, sym, qe, slot)
            if v.get("held"):
                # the ledger's claim here is ABSENCE, so a match is the failure
                checked += 1
                if cur is not None and abs(cur - want) <= TOL:
                    resurrected.append((name, sym, qe, basis, want, str(v["held"])[:70]))
                continue
            checked += 1
            if cur is None:
                missing.append((name, sym, qe, want, payload, slot))
            elif abs(cur - want) > TOL:
                drift.append((name, sym, qe, want, cur))

    for name, payload, key, slot in LEDGERS:
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            continue
        try:
            led = json.load(open(p))
        except Exception:
            continue
        for k, v in led.items():
            if not isinstance(v, dict) or v.get("skip") or key not in v or v[key] is None:
                continue
            if "|" not in k:
                continue
            sym, qe = k.rsplit("|", 1)
            want = v[key]
            checked += 1
            if payload == "revop":
                row = (revop.get(sym) or {}).get(qe)
                cur = row[slot] if row and len(row) > slot else None
            else:
                row = (fmap.get(sym) or {}).get(int(qe))
                cur = row[slot] if row and len(row) > slot else None
            if v.get("held"):  # asserts ABSENCE — see the note above
                if cur is not None and abs(cur - want) <= TOL:
                    resurrected.append((name, sym, qe, "-", want, str(v["held"])[:70]))
                continue
            if cur is None:
                missing.append((name, sym, qe, want, payload, slot))
            elif abs(cur - want) > TOL:
                drift.append((name, sym, qe, want, cur))

    # ---- the REVIEWED CELL-FIX ledgers ------------------------------------------------
    # fund_cell_fix / revop_cell_fix are shaped {"fixes":[{sym,qe,basis,was,fixed}]}, not the flat
    # SYM|QE dict every other ledger uses, so they sat OUTSIDE this detector entirely: 2,101
    # adjudicated cells with nothing re-checking them after a refresh (§74's durability rule — a
    # heal CI cannot see gets clobbered silently). Registered 2026-08-25 (runbook §111g).
    # DRIFT here is informative, not fatal, and that is deliberate: it is how a cross-campaign
    # disagreement becomes visible instead of silent (§111i — 8 con cells whose ledger value three
    # independent readers contradict). Note this step runs BEFORE §109j's post-merge re-apply, so a
    # ledger value that the owners pass reverted mid-run shows here and is restored afterwards.
    for name, payload, slots in (
        ("fund_cell_fix.json", "fund", {"std": 1, "con": 3}),
        (
            "revop_cell_fix.json",
            "revop",
            {"std": 0, "con": 1, "op_std": 2, "op_con": 3, "pat_std": 4, "pat_con": 5, "ebit_std": 7, "ebit_con": 8},
        ),
    ):
        p3 = os.path.join(HERE, name)
        if not os.path.exists(p3):
            continue
        try:
            fixes = json.load(open(p3)).get("fixes") or []
        except Exception:
            continue
        for f in fixes:
            slot = slots.get(f.get("basis"))
            sym, qe, want = f.get("sym"), str(f.get("qe")), f.get("fixed")
            if slot is None or sym is None or qe is None:
                continue
            row = (revop.get(sym) or {}).get(qe) if payload == "revop" else (fmap.get(sym) or {}).get(int(qe))
            cur = row[slot] if row and len(row) > slot else None
            if want is None:  # a null `fixed` is a RETRACTION: asserts absence
                if cur is not None:
                    resurrected.append((name, sym, qe, f.get("basis"), cur, "ledger retracts this cell"))
                continue
            checked += 1
            if cur is None:
                missing.append((name, sym, qe, want, payload, slot))
            elif abs(cur - want) > TOL:
                prev = f.get("was")
                if prev is not None and abs(cur - prev) <= TOL:
                    reverted.append((name, sym, qe, f.get("basis"), prev, want, payload, slot))
                else:
                    drift.append((name, sym, qe, want, cur))

    for name, payload, key, dslot, bkey, bmap, root in NESTED:
        p2 = os.path.join(HERE, name)
        if not os.path.exists(p2):
            continue
        try:
            led = json.load(open(p2))
        except Exception:
            continue
        if root is not None:
            led = led.get(root)
            if not isinstance(led, dict):
                continue
        for sym, qd in led.items():
            if not isinstance(qd, dict):
                continue
            for qe, v in qd.items():
                if not isinstance(v, dict) or v.get("skip"):
                    continue
                # ⚠️ A LEDGER KEY IS NOT ALWAYS A QUARTER. These defect ledgers use a
                # `_RETRACTED_<QE>` key rename to withdraw an entry while keeping its audit trail
                # (and `_note` for prose), so `int(qe)` below is not safe on every key. Unguarded it
                # raised ValueError and CRASHED this whole step — which is BLOCKING, so it stopped the
                # entire fundamentals payload from publishing (2026-08-18: b395fa35 added 24 such keys
                # to pat_defects + 4 to rev_defects, and the first one alphabetically, ASTRAZEN
                # _RETRACTED_20200630, killed the run). Skipping is also the right SEMANTICS: a
                # retracted entry asserts nothing. Counted and reported rather than silently dropped,
                # so a genuinely malformed key still shows up instead of hiding here.
                if not (isinstance(qe, str) and qe.isdigit()):
                    odd_keys.append(f"{name} {sym}/{qe}")
                    continue
                want = v.get(key)
                if want is None:  # a deliberate null verdict is not a claim
                    continue
                slot = dslot
                if bkey and bmap:
                    slot = bmap.get(str(v.get(bkey, "")).lower(), dslot)
                checked += 1
                if payload == "revop":
                    row = (revop.get(sym) or {}).get(str(qe))
                    cur = row[slot] if row and len(row) > slot else None
                else:
                    row = (fmap.get(sym) or {}).get(int(qe))
                    cur = row[slot] if row and len(row) > slot else None
                if cur is None:
                    missing.append((name, sym, str(qe), want, payload, slot))
                elif abs(cur - want) > TOL:
                    drift.append((name, sym, str(qe), want, cur))

    if not quiet:
        print("checked %d ledgered cells against the served payloads" % checked)
        print("  MISSING     (clobbered):            %d" % len(missing))
        print("  DRIFT       (superseded/corrected): %d" % len(drift))
        print("  REVERTED    (a correction was undone — the payload holds the ledger's `was`): %d" % len(reverted))
        print("  RESURRECTED (a refused value is live again): %d" % len(resurrected))
        if odd_keys:
            print("  skipped %d non-quarter ledger key(s) — retracted/annotation entries, not claims:" % len(odd_keys))
            for k in odd_keys[:8]:
                print(f"     skip    {k}")
        for m in missing[:15]:
            print("     MISSING %-30s %-12s %s  ledger=%s" % (m[0], m[1], m[2], m[3]))
        for d in drift[:10]:
            print("     DRIFT   %-30s %-12s %s  ledger=%s live=%s" % d)
        for r in reverted[:15]:
            print(
                "     REVERTED %-26s %-12s %s %-8s live=%s (the pre-heal value) ledger=%s"
                % (r[0], r[1], r[2], r[3] or "-", r[4], r[5])
            )
        if reverted:
            print(
                "     ^ these are repairable from the ledger: --repair-reverted, or wait for the"
                " post-merge re-apply that refresh-fundamentals now runs (runbook 109j)."
            )
        for r in resurrected[:15]:
            print(
                "     RESURRECTED %-26s %-12s %s %-4s value=%s\n                 held because: %s"
                % (r[0], r[1], r[2], r[3], r[4], r[5])
            )

    if missing and repair:
        for name, sym, qe, want, payload, slot in missing:
            if payload == "revop":
                row = (revop.get(sym) or {}).get(qe)
                if not row:
                    continue
                while len(row) <= slot:
                    row.append(None)
                row[slot] = want
                revop[sym][qe] = row
            else:
                row = (fmap.get(sym) or {}).get(int(qe))
                if not row:
                    continue
                while len(row) <= slot:
                    row.append(None)
                row[slot] = want
        json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
        json.dump(fund, open(FUND, "w"), separators=(",", ":"))
        print("repaired %d cells into the served payloads (commit + push them, then re-run to confirm)" % len(missing))

    # Reverted cells ARE safely repairable — unlike DRIFT, the ledger's own `was` proves nobody
    # adjudicated a different number, they were simply overwritten with the value the correction
    # replaced. Still its own flag rather than part of --repair: --repair fills EMPTY slots, this
    # overwrites a populated one, and those deserve separate consent.
    if reverted and "--repair-reverted" in sys.argv:
        for name, sym, qe, basis, prev, want, payload, slot in reverted:
            row = (revop.get(sym) or {}).get(str(qe)) if payload == "revop" else (fmap.get(sym) or {}).get(int(qe))
            if row and len(row) > slot and row[slot] is not None and abs(row[slot] - prev) <= TOL:
                row[slot] = want
        json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
        json.dump(fund, open(FUND, "w"), separators=(",", ":"))
        print("restored %d reverted cells from the ledgers (commit + push, then re-run)" % len(reverted))

    # Emptying a slot is destructive and a held flag can itself be wrong (measured: of the three
    # holds another session added on 2026-08-11, SHREECEM 2018-06 was refuted by Moneycontrol's own
    # consolidated row differing from its own standalone row). So this never runs as a side effect
    # of --repair; it needs its own flag, and the operator is expected to have read the held reason.
    if resurrected and "--repair-held" in sys.argv:
        for name, sym, qe, basis, want, _why in resurrected:
            for payload, slot in (("revop", BASIS_SLOT.get(basis)), ("fund", {"std": 1, "con": 3}.get(basis))):
                if slot is None:
                    continue
                row = (revop.get(sym) or {}).get(str(qe)) if payload == "revop" else (fmap.get(sym) or {}).get(int(qe))
                if row and len(row) > slot and row[slot] is not None and abs(row[slot] - want) <= TOL:
                    row[slot] = None
        json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
        json.dump(fund, open(FUND, "w"), separators=(",", ":"))
        print("re-retracted %d resurrected cells (commit + push, then re-run)" % len(resurrected))

    # ★ HTML-ESCAPED PHANTOM SYMBOL KEYS (2026-08-26, runbook §114). Called from here rather than
    # added as a new workflow step: this is already THE blocking gate over these two payloads, so the
    # guard inherits its CI wiring for free. A phantom key (`M&M` -> `M&AMP;M`) is a duplicate row
    # every coverage scan reads as already-filled, and it was rendering in docs/discovery.json.
    phantom_ok = True
    try:
        sys.path.insert(0, HERE)
        import phantom_key_guard

        phantom_ok, lines = phantom_key_guard.check()
        if not phantom_ok or not quiet:
            for _l in lines:
                print(_l)
    except Exception as e:  # never let the guard wedge the detector it rides on
        print(f"  (phantom-key guard errored: {type(e).__name__}: {e} — run scripts/phantom_key_guard.py by hand)")

    sys.exit(1 if (missing or resurrected or not phantom_ok) else 0)


if __name__ == "__main__":
    main()

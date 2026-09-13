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
"""HTML-ESCAPED PHANTOM SYMBOLS — recover the data we already own but never serve  (2026-08-11)

FOUND WHILE FIXING SOMETHING ELSE. The Moneycontrol resolver was writing off every symbol containing
an ampersand, and sizing that turned up 13 symbols in our own store that no exchange ever listed:

    M&AMP;M   M&AMP;MFIN   J&AMP;KBANK   IL&AMP;FSENGG   S&AMP;SPOWER   SURANAT&AMP;P
    GET&AMP;D   GVT&AMP;D   GMRP&AMP;UI   ARE&AMP;M   COX&AMP;KINGS   IL&AMP;FSTRANS   L&AMP;TFH

An `&` was HTML-escaped to `&amp;` somewhere in ingestion and then upper-cased with the ticker, so
`M&M` became `M&AMP;M` and got its own key. They are invisible to the site — absent from
quarterly_results.json and from the search index — yet they hold 271 revop quarters and 74
fundamentals rows between them. Data we already have, that nothing reads.

★ THE PHANTOM IS PROVED TO BE THE SAME COMPANY BY ITS OWN OVERLAP, not by the name resembling one.
Every slot of the revop row is compared, [revS, revC, opS, opC, patS, patC, fin, ebitS, ebitC], plus
both PAT slots of sf_fundamentals. Measured across all 13 phantoms: 798 overlapping values agree with
the clean symbol, 62 disagree, and 766 sit where the clean symbol's slot is EMPTY.

Per-phantom gate before any of its unique values are trusted — the same shape as every other route
here, because "the name looks right" is exactly the reasoning that produces a wrong-company merge:
    >= 3 agreeing overlaps  AND  disagreement rate < 15%
Measured verdicts, and note the gate costs us the two RICHEST phantoms rather than the poorest, which
is the point of having it:
    REFUSED  S&AMP;SPOWER   49 agree / 11 disagree (18.3%)  — 230 values left where they are
    REFUSED  IL&AMP;FSENGG  44 agree /  8 disagree (15.4%)  — 210 values left where they are
    REFUSED  COX&AMP;KINGS  13 agree /  7 disagree (35.0%)  —  57 values left where they are
    MERGED   the other ten, J&AMP;KBANK cleanest at 135 agree / 0 disagree
Result: 269 values merged, 497 refused.

★★ THE TARGET FOLLOWS A RENAME. GET&D and L&TFH have no revop rows of their own at all — they were
renamed to GVT&D and LTF. Unescaping alone would write into a dead key, so the target is
_rename_map.json's successor when one exists.

FILL-ONLY, ALWAYS. A disagreement is never resolved by overwriting: the 5 known ones (COX&KINGS
2019-06 430.16 vs 438.89, GET&D 2018-03 813.93 vs 760.11, M&M 2024-06 and 2024-09 consolidated) are
left exactly as they are and recorded. The phantom keys themselves are NOT deleted — that is a
separate decision with its own blast radius, and this script only moves values that no consumer can
currently see into keys they can.

Run: python -X utf8 scripts/fill2020_tools/merge_escaped_phantom_symbols.py [--apply]
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
RENAMES = os.path.join(SCRIPTS, "_rename_map.json")
FILLS = os.path.join(SCRIPTS, "phantom_symbol_merge.json")
RETRACT = os.path.join(SCRIPTS, "phantom_symbol_retract.json")
IDPROOF = os.path.join(SCRIPTS, "phantom_identity_proof.json")
BSE_SCRIPS = os.path.join(SCRIPTS, "bse_scrips.json")

MIN_AGREE = 3
MAX_DIS_RATE = 0.15
# ★★★ SLOT 6 (`fin`) IS A DERIVED FLAG, NOT A MEASUREMENT — IT MUST NOT VOTE (2026-08-26, §115).
# build_revop sets it per FILING from the filename and which tags appear
# (`fname.startswith("BANKING")`, `"InterestEarned" in xml`, ...), so two filings for the same
# company-quarter legitimately disagree on it. Scoring it asks "do these two readings agree on the
# numbers?" and answers with a boolean nobody reported. It cost the richest phantom its merge:
# S&AMP;SPOWER scored 56/12 = 17.6% REFUSED, and ALL TWELVE disagreements were this flag — every
# actual value slot agreed 44/0. Identity is not in doubt there either; its filing carries
# `S&S POWER SWITCHGEARS LIMITED`, ISIN INE902B01017, ScripCode 517273, our exact code for S&SPOWER.
# Excluding it does NOT rescue COX&AMP;KINGS (25.0%, genuine revS/opS disagreements) and flips no
# passing phantom to refused — measured for all 13 before the change was kept.
# It stays un-propagatable as well (the `pv == 0` skip below); this only stops it VOTING.
SCORELESS_REVOP_SLOTS = {6}
PAT_SLOT = {1: "std", 3: "con"}


def close(a, b):
    return abs(a - b) <= max(0.05, 0.002 * max(abs(a), abs(b)))


def identity_proven():
    """{phantom: proof} for phantoms whose OWN FILING names the target company, RE-VERIFIED here.

    ★★★ A DIRECT IDENTITY PROOF OUTRANKS THE STATISTICAL PROXY (2026-08-26, runbook §115).
    The overlap gate below exists to answer ONE question — "is this phantom the same company?" — and
    it answers it by proxy because the direct answer was not available. It now is: build_revop parses
    the symbol out of the company's own XBRL, and those same files carry `<ScripCode>`. Where that
    code equals OUR stored BSE code for the target, identity is settled by primary evidence and the
    proxy has nothing left to add. That is the house rule everywhere else, not a new one — §76 says
    gate a symbol->BSE-scrip mapping on the ISIN/scrip, never on the ticker looking right.

    WHY IT MATTERED: S&AMP;SPOWER scored 16.7% REFUSED and every disagreement behind that number was
    a fundamentals con-PAT cell — a different quantity in a different store, already journalled as a
    known two-reader dispute. Its revop values agreed 40/0. Refusing on that would have stranded 190
    values: 24 quarters of S&S Power's 2018-2023 revenue and profit history, keyed where nothing
    reads it, while the readable key held only 8 quarters back to 2024.

    ⚠️ THIS IS NOT A LOOSENING, AND IT IS NOT A LIST YOU MAY EDIT. The ledger is re-checked against
    bse_scrips.json on every run; an entry whose code no longer matches is IGNORED and the phantom
    falls back to the statistical gate. COX&AMP;KINGS has no proof (its era's filings carry no
    ScripCode) and stays REFUSED, which is the point: the override needs evidence, not a wish.
    Identity is all it settles — fill-only still stands, so a value that DISAGREES is never
    overwritten, only ever written where the target holds nothing.
    """
    try:
        proof = json.load(open(IDPROOF))
        by_id = (json.load(open(BSE_SCRIPS)) or {}).get("by_id") or {}
    except Exception:
        return {}
    ok = {}
    for ph, rec in proof.items():
        target = rec.get("real")
        ours = by_id.get(target)
        if ours is not None and str(ours) == str(rec.get("scrip_code")):
            ok[ph] = rec
    return ok


def retracted_evidence():
    """{phantom: [agree, disagree]} from cells this phantom USED to hold in sf_fundamentals.

    ★★★ A RETRACTION MUST NEVER IMPROVE A GATE SCORE (2026-08-26, runbook §115). The fundamentals
    phantom keys were retracted earlier the same day, and re-running this gate immediately after
    moved S&AMP;SPOWER from **18.3% REFUSED to 2.5% MERGE** — not because anything was learned, but
    because ten of its eleven disagreements were the very con cells that had just been deleted. The
    gate would then have merged its 230 values on the strength of evidence removal. Every one of the
    13 reconciles to the pre-retraction score once these cells are added back (measured), so the
    journal is read here as a first-class evidence source: DUP == an agreement, CONTESTED == a
    disagreement, exactly the cells the live scan can no longer see. SUBSET/UNIQUE counted neither
    then and count neither now (the gate only ever scored cells where BOTH sides held a value).
    """
    out = {}
    try:
        journal = json.load(open(RETRACT))
    except Exception:
        return out  # no journal yet -> nothing was retracted yet
    for e in journal.values():
        if e.get("store") != "docs/sf_fundamentals.json":
            continue  # the twin was never in this gate's scope
        slot = out.setdefault(e["phantom"], [0, 0])
        if e["verdict"] == "DUP":
            slot[0] += 1
        elif e["verdict"] == "CONTESTED":
            slot[1] += 1
    return out


def main():
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP))
    fund = json.load(open(FUND))
    ledger = json.load(open(LEDGER))
    renames = json.load(open(RENAMES)) if os.path.exists(RENAMES) else {}
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    prior = retracted_evidence()
    proven = identity_proven()
    created = set()
    out = json.load(open(FILLS)) if os.path.exists(FILLS) else {}  # APPEND-ONLY: a re-run finds the
    # August cells already merged (their target slots are no longer empty) so it would regenerate an
    # `out` without them and silently erase 324 entries of provenance. Same clobber class as the
    # retraction journal's, caught the same day by an idempotence re-run.

    phantoms = sorted({s for s in list(revop) + list(fund) if "&AMP;" in s.upper()})
    print("phantom symbols: %d" % len(phantoms))
    applied = refused = 0
    for ph in phantoms:
        clean = html.unescape(ph.replace("&AMP;", "&"))
        target = renames.get(clean) or clean
        agree, dis = prior.get(ph, [0, 0])
        cand = []
        # revenue/operating profit rows
        for q, r in (revop.get(ph) or {}).items():
            trow = (revop.get(target) or {}).get(q)
            for slot in range(len(r)):
                pv = r[slot]
                if pv is None:
                    continue
                tv = trow[slot] if trow and len(trow) > slot else None
                if tv is None:
                    cand.append(("revop", q, slot, pv))
                elif slot in SCORELESS_REVOP_SLOTS:
                    continue
                elif close(tv, pv):
                    agree += 1
                else:
                    dis += 1
        # ★ THE LEDGER IS A TARGET, NOT A MIRROR (2026-08-26, runbook §115). scripts/revop_fundamentals
        # .json is what `build_revop.py` RESUMES from (`data = json.load(open(OUT))`) and writes back to
        # BOTH itself and docs/sf_revop.json. Until now this script only wrote it for cells it merged
        # into docs, so a cell docs already had (merged in an earlier pass) was never carried across —
        # leaving 170 real values keyed to a phantom in the file that seeds every future build. They
        # are scored into the SAME gate, not a second one, and harvested under the same fill-only rule.
        for q, r in (ledger.get(ph) or {}).items():
            trow = (ledger.get(target) or {}).get(q)
            for slot in range(len(r)):
                pv = r[slot]
                if pv is None:
                    continue
                tv = trow[slot] if trow and len(trow) > slot else None
                if tv is None:
                    cand.append(("revled", q, slot, pv))
                elif slot in SCORELESS_REVOP_SLOTS:
                    continue
                elif close(tv, pv):
                    agree += 1
                else:
                    dis += 1
        # fundamentals PAT slots
        for r in fund.get(ph, []):
            trow = (fmap.get(target) or {}).get(r[0])
            for slot in (1, 3):
                pv = r[slot] if len(r) > slot else None
                if pv is None:
                    continue
                tv = trow[slot] if trow and len(trow) > slot else None
                if tv is None:
                    cand.append(("fund", r[0], slot, pv))
                elif close(tv, pv):
                    agree += 1
                else:
                    dis += 1
        rate = dis / float(agree + dis) if (agree + dis) else 1.0
        ok = agree >= MIN_AGREE and rate < MAX_DIS_RATE
        pr = proven.get(ph)
        if pr and not ok:
            ok = True  # identity settled by the filing; see identity_proven()
        pa, pd = prior.get(ph, [0, 0])
        stat = "MERGE" if (agree >= MIN_AGREE and rate < MAX_DIS_RATE) else "REFUSED"
        print(
            "  %-16s -> %-12s agree %3d  disagree %2d (%4.1f%%)  recoverable %3d   %s%s%s"
            % (
                ph,
                target,
                agree,
                dis,
                100 * rate,
                len(cand),
                "MERGE" if ok else "REFUSED",
                ("   [+%d/%d from the retraction journal]" % (pa, pd)) if (pa or pd) else "",
                (
                    "   [identity PROVEN: scrip {} {} — overrides the {} proxy]".format(
                        pr["scrip_code"], pr.get("company_name") or "", stat
                    )
                )
                if (pr and stat == "REFUSED")
                else "",
            )
        )
        if not ok:
            refused += len(cand)
            out[f"{ph}|REFUSED"] = {
                "target": target,
                "agree": agree,
                "disagree": dis,
                "why": (
                    "phantom-to-target agreement too weak to trust its unique values: %d "
                    "agreements, %d disagreements (%.1f%%). Its %d otherwise-recoverable values "
                    "stay where they are." % (agree, dis, 100 * rate, len(cand))
                ),
            }
            continue
        for kind, q, slot, pv in cand:
            # ★ AN EXACT 0 IS NOT A MEASUREMENT HERE. The revop row is
            # [revS, revC, opS, opC, patS, patC, fin, ebitS, ebitC] and slot 6 (finance cost) is
            # written 0 by the builder for rows where the figure was never present — propagating it
            # into an EMPTY target slot would assert "zero finance cost" where the truth is unknown
            # (memory: feedback-zero-is-a-no-base-sentinel). Skipped rather than merged.
            if pv == 0:
                out["%s|%s|%s|%d|SKIPPED-ZERO" % (target, kind, q, slot)] = {
                    "from_phantom": ph,
                    "why": "exact 0 may be the builder's not-present sentinel, not a measured zero",
                }
                continue
            if kind == "revled":
                row = (ledger.get(target) or {}).get(q)
                if row is None:
                    row = [None, None, None, None, None, None, 0, None, None]
                    ledger.setdefault(target, {})[q] = row
                    created.add((target + " (ledger)", q))
                if len(row) <= slot or row[slot] is not None:
                    continue
                if apply_it:
                    row[slot] = pv
            elif kind == "revop":
                row = (revop.get(target) or {}).get(q)
                # ★ "THE TARGET HAS NO ROW" IS NOT "NOTHING TO DO" (2026-08-26, runbook §115).
                # This branch used to `continue` on row is None, silently and with no ledger entry —
                # the three-state bug in reverse (memory: feedback-else-covers-two-states). It cost
                # 289 values across 4 gate-PASSING phantoms, and they were not edge quarters: the
                # readable SURANAT&P held 10 quarters while its phantom held 32 back to 2018-06, and
                # GMRP&UI held 5 against the phantom's 17 — years of revenue history for two live
                # companies, present in the file and keyed where nothing reads it.
                # Creating is safe here, and it is not an inference: the phantom is the SAME FILING
                # SET. build_revop parses NSESymbol out of the company's own XBRL, and the filings
                # behind these keys carry BSE ScripCode 517530 "Surana Telecom and Power Limited"
                # and 543490 "GMR POWER AND URBAN INFRA LIMITED" — our exact codes for those two
                # tickers. Nothing is added to the store; the same rows are re-keyed to where the
                # site can read them. Seeded with the builder's own default row (fin=0).
                if row is None:
                    row = [None, None, None, None, None, None, 0, None, None]
                    revop.setdefault(target, {})[q] = row
                    created.add((target, q))
                if len(row) <= slot or row[slot] is not None:
                    continue
                if apply_it:
                    row[slot] = pv
                    lr = ledger.setdefault(target, {}).get(q)
                    if lr is None:
                        ledger[target][q] = list(row)
                    elif len(lr) > slot and lr[slot] is None:
                        lr[slot] = pv
            else:
                row = (fmap.get(target) or {}).get(q)
                if row is None or len(row) <= slot or row[slot] is not None:
                    continue
                if apply_it:
                    row[slot] = pv
            out["%s|%s|%s|%d" % (target, kind, q, slot)] = {
                "value": pv,
                "from_phantom": ph,
                "row_created": (target, q) in created,
                "identity": (
                    "filing ScripCode {} == our code for {} ({})".format(pr["scrip_code"], target, pr["filing"])
                )
                if pr
                else "overlap gate",
                "gate": (
                    "%d values agree with %s on overlapping quarters, %d disagree (%.1f%%) — "
                    "same company, and this slot was empty" % (agree, target, dis, 100 * rate)
                ),
            }
            applied += 1

    print("\nrecoverable and merged: %d | refused on weak agreement: %d" % (applied, refused))
    if created:
        bysym = {}
        for t, q in created:
            bysym.setdefault(t, []).append(q)
        print(
            "quarters CREATED on the readable key (the target had no row at all): %d across %d symbols"
            % (len(created), len(bysym))
        )
        for t in sorted(bysym):
            qs = sorted(bysym[t])
            print("   %-12s %2d quarters  %s..%s" % (t, len(qs), qs[0], qs[-1]))
    if not apply_it:
        print("(dry run — re-run with --apply)")
        return
    json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
    json.dump(fund, open(FUND, "w"), separators=(",", ":"))
    json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
    json.dump(out, open(FILLS, "w"), indent=1, sort_keys=True)
    print("APPLIED %d values into keys the site can actually read" % applied)


if __name__ == "__main__":
    main()

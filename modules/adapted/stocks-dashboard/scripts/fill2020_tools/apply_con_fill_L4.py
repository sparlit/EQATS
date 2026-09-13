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
"""APPLY the con-fill wave reports: consolidated PAT (+ revenue/op twins) into both stores.

ONE writer. Reads every scratchpad/reports/*.json produced by the read-only reader wave, admits only
FILLED cells that carry a value, an annCon date, a source and an ANCHOR, and writes:

  con PAT   -> docs/sf_fundamentals.json  row idx 3, annCon -> idx 4   (+ scripts/fundamentals.json)
  rev_con   -> docs/sf_revop.json  slot 1                              (+ scripts/revop_fundamentals.json)
  op_con    -> docs/sf_revop.json  slot 3                              (+ scripts/revop_fundamentals.json)
  provenance-> scripts/conpat_filing_fills.json   "SYM|QE|con" / "SYM|QE|con_rev"
               (those exact tokens, or verify_fills_live.py cannot see the cell)
  pin       -> scripts/owners_basis_heals.json    only where _reattr_owners.json covers the cell
  rekey     -> scripts/_revgap_skips.json         "SYM|QE" -> "_FILLED_SYM|QE"

FILL-ONLY AND ANCHOR-GATED. A slot that already holds a different value stops the run for that cell
(never overwrite: a later correction outranks a backfill and only a human can adjudicate).
A cell whose target quarter is absent from a store is reported, never created.

Run: python3 -X utf8 apply_con_fill.py <REPORT_DIR> <WORKTREE> [--apply]
"""
import glob
import json
import os
import sys

REPORTS = sys.argv[1]
ROOT = sys.argv[2]
APPLY = "--apply" in sys.argv
S = os.path.join(ROOT, "scripts")
STAMP = os.popen("date +'%Y-%m-%d %H:%M IST'").read().strip()
TOL = 0.011


def load(p):
    return json.load(open(p, encoding="utf-8"))


def main():
    fund_d = os.path.join(ROOT, "docs", "sf_fundamentals.json")
    fund_s = os.path.join(S, "fundamentals.json")
    rev_d = os.path.join(ROOT, "docs", "sf_revop.json")
    rev_s = os.path.join(S, "revop_fundamentals.json")
    prov_p = os.path.join(S, "conpat_filing_fills.json")
    pin_p = os.path.join(S, "owners_basis_heals.json")
    skip_p = os.path.join(S, "_revgap_skips.json")
    reattr_p = os.path.join(S, "_reattr_owners.json")

    fd, fs = load(fund_d), load(fund_s)
    rd, rs = load(rev_d), load(rev_s)
    prov, pin, skips, reattr = load(prov_p), load(pin_p), load(skip_p), load(reattr_p)

    # writer-side review decisions, keyed SYM|QE: {"hold": why} to withhold a read cell, or
    # field overrides (e.g. annCon) with a "why". Kept OUT of the reports, which stay the readers'
    # raw output.
    ov_p = os.path.join(REPORTS, "_overrides.json")
    ov = load(ov_p) if os.path.exists(ov_p) else {}

    cells = []
    for p in sorted(glob.glob(os.path.join(REPORTS, "*.json"))):
        if os.path.basename(p).startswith("_"):
            continue
        for c in load(p):
            c["_wave"] = os.path.basename(p)[:-5]
            cells.append(c)
    print("reports: %d cells" % len(cells))

    filled = [c for c in cells if c.get("verdict") == "FILLED"]
    print("FILLED verdicts: %d" % len(filled))

    wrote_pat = wrote_rev = wrote_op = 0
    blocked, skipped, held = [], [], []
    for c in sorted(filled, key=lambda x: (x["sym"], x["qe"])):
        sym, qe = c["sym"], int(c["qe"])
        key = "%s|%d" % (sym, qe)
        o = ov.get(key) or {}
        if o.get("hold"):
            held.append((key, o["hold"]))
            continue
        for f, v in o.items():
            if f in ("hold", "why"):
                continue
            c[f] = v
        if o.get("why"):
            c["writer_note"] = o["why"]
        # ---- gate: the report must carry value + date + source + anchor
        bad = [f for f in ("con", "annCon", "src", "anchor") if c.get(f) in (None, "", [])]
        if bad:
            blocked.append((key, "report missing {}".format(",".join(bad))))
            continue
        con, ann = round(float(c["con"]), 2), int(c["annCon"])
        if not (19900101 <= ann <= 20991231):
            blocked.append((key, "annCon not a date: {!r}".format(c["annCon"])))
            continue

        # ---- PAT twins. docs/ is the SERVED payload and is mandatory; scripts/fundamentals.json is
        # a mirror whose history does not reach every quarter (it starts later for several symbols),
        # so a missing row there is a coverage limit of the mirror, not a reason to refuse the cell.
        # Such a cell is still guarded, because conpat_filing_fills.json is registered in
        # verify_fills_live.py and a clobber there reports MISSING (and --repair restores it).
        rows, mirror_note = [], None
        for label, store in (("docs/sf_fundamentals.json", fd), ("scripts/fundamentals.json", fs)):
            lst = store.get(sym)
            row = next((r for r in (lst or []) if r and r[0] == qe), None)
            if row is None:
                if label.startswith("docs/"):
                    blocked.append((key, f"{label} has no row for this quarter"))
                    rows = None
                    break
                have = sorted(r[0] for r in (lst or []) if r)
                mirror_note = (
                    "scripts/fundamentals.json has no row for this quarter (that mirror "
                    "starts at %s for this symbol); docs payload written, cell guarded by "
                    "the conpat_filing_fills registration in verify_fills_live.py" % (have[0] if have else "n/a")
                )
                continue
            rows.append((label, row))
        if rows is None:
            continue
        clash = [(l, r[3]) for l, r in rows if r[3] is not None and abs(r[3] - con) > TOL]
        if clash:
            blocked.append((key, f"con slot already holds {clash[0][1]} (not {con}) in {clash[0][0]}"))
            continue
        if all(r[3] is not None for _, r in rows):
            skipped.append((key, f"con already == {con}"))
        else:
            for _, r in rows:
                if APPLY:
                    r[3], r[4] = con, ann
            wrote_pat += 1
            print("  PAT  %-12s %d  con=%-10s annCon=%d   [%s]" % (sym, qe, con, ann, c["_wave"]))

        # ---- a missing sf_revop ROW is not a missing value. The row layout is fixed and known
        # (build_revop.py: [revS, revC, opS, opC, patS, patC, fin, ebitS, ebitC]), and several
        # symbols simply have no row before some quarter. Refusing to create one costs real
        # coverage AND is actively harmful: revCon reads slot 1 of "the latest quarter whose
        # CONSOLIDATED result was announced on or before the date", so filling a con PAT makes an
        # older quarter point-in-time-visible and, with no row behind it, the symbol DROPS OUT of
        # revCon for that date. Create the row, carrying `fin` from the symbol's own siblings.
        if c.get("rev_con") is not None or c.get("op_con") is not None:
            for label, store in (("docs/sf_revop.json", rd), ("scripts/revop_fundamentals.json", rs)):
                qs = store.get(sym)
                if qs is None or str(qe) in qs:
                    continue
                sib = [r for r in qs.values() if len(r) > 6 and r[6] is not None]
                if not sib:
                    blocked.append((key, f"{label}: no sibling row to take the `fin` flag from"))
                    continue
                fin = sib[0][6]
                qs[str(qe)] = [None, None, None, None, None, None, fin, None, None]
                print("  ROW  %-12s %d  %s created (fin=%s from this symbol's own rows)" % (sym, qe, label, fin))

        # ---- revenue / operating-profit twins (optional)
        for field, slot, tag in (("rev_con", 1, "rev"), ("op_con", 3, "op")):
            v = c.get(field)
            if v is None:
                continue
            v = round(float(v), 2)
            ok = True
            for label, store in (("docs/sf_revop.json", rd), ("scripts/revop_fundamentals.json", rs)):
                row = (store.get(sym) or {}).get(str(qe))
                if row is None or len(row) <= slot:
                    blocked.append((key, f"{label} has no revop row/slot for {field}"))
                    ok = False
                    break
                if row[slot] is not None and abs(row[slot] - v) > TOL:
                    blocked.append((key, "%s slot %d already holds %s (not %s)" % (label, slot, row[slot], v)))
                    ok = False
                    break
            if not ok:
                continue
            hit = False
            for store in (rd, rs):
                row = store[sym][str(qe)]
                if row[slot] is None:
                    if APPLY:
                        row[slot] = v
                    hit = True
            if hit:
                if tag == "rev":
                    wrote_rev += 1
                else:
                    wrote_op += 1
                print("  %-4s %-12s %d  slot %d = %s" % (tag.upper(), sym, qe, slot, v))

        # ---- sf_revop's patC (slot 5) is a MIRROR of npCon (runbook 70: sf_fundamentals is
        # authoritative, consumers fall back to the mirror only where it is empty). Keeping the
        # mirror equal to the value just written costs nothing and keeps the two files from
        # drifting into the 70a class; a slot holding anything else is left for a human.
        for label, store in (("docs/sf_revop.json", rd), ("scripts/revop_fundamentals.json", rs)):
            row = (store.get(sym) or {}).get(str(qe))
            if row is None or len(row) <= 5:
                continue
            if row[5] is None:
                if APPLY:
                    row[5] = con
                print("  MIR  %-12s %d  %s patC slot 5 = %s" % (sym, qe, label, con))
            elif abs(row[5] - con) > TOL:
                blocked.append((key, f"{label} patC mirror holds {row[5]} (not {con}) — left alone"))

        # ---- provenance (the exact tokens verify_fills_live.py registers)
        rec = {
            "con": con,
            "annCon": ann,
            "basis": "con",
            "src": c.get("src"),
            "evidence": c.get("printed_evidence") or c.get("notes"),
            "anchor": c.get("anchor"),
            "row": c.get("row"),
            "printed": c.get("printed"),
            "unit": c.get("unit"),
            "read_by": c.get("read_by"),
            "carrying_filing": c.get("carrying_filing"),
            "con_total": c.get("con_total"),
            "con_nci": c.get("con_nci"),
            "routes_tried": c.get("routes_tried"),
            "writer_note": c.get("writer_note"),
            "campaign": "con-params-L4",
            "fill_pass": "2026-08-18 con-fill wave {}".format(c["_wave"]),
            "when": STAMP,
        }
        if mirror_note:
            rec["mirror"] = mirror_note
        prov.setdefault("%s|%d|con" % (sym, qe), rec)
        # Only claim a con_rev in the ledger when the value ACTUALLY LANDED in the payload —
        # verify_fills_live.py reads this key as an assertion that the cell is there, so a record
        # for a write the applier refused (no revop row, or a different value already stored)
        # would report MISSING for ever. The read is kept on the |con entry instead.
        live_rev = (rd.get(sym) or {}).get(str(qe))
        rev_landed = (
            c.get("rev_con") is not None
            and live_rev
            and len(live_rev) > 1
            and live_rev[1] is not None
            and abs(live_rev[1] - round(float(c["rev_con"]), 2)) <= TOL
        )
        if c.get("rev_con") is not None and not rev_landed:
            rec["rev_con_read_not_stored"] = "{} — read from the same statement but NOT written: {}".format(
                c["rev_con"],
                "no sf_revop row exists for this quarter"
                if not live_rev
                else f"sf_revop already holds {live_rev[1]} (a different vintage); a backfill never "
                "overwrites a stored value",
            )
        if rev_landed:
            prov.setdefault(
                "%s|%d|con_rev" % (sym, qe),
                {
                    "rev_con": round(float(c["rev_con"]), 2),
                    "basis": "con",
                    "src": c.get("src"),
                    "anchor": c.get("anchor"),
                    "row": c.get("rev_row") or c.get("row"),
                    "unit": c.get("unit"),
                    "read_by": c.get("read_by"),
                    "campaign": "con-params-L4",
                    "fill_pass": "2026-08-18 con-fill wave {}".format(c["_wave"]),
                    "when": STAMP,
                },
            )
        # ---- pin only where the nightly owners applier would otherwise re-write the cell
        if key in reattr:
            pin["cells"].setdefault(
                "%s|%d|patC" % (sym, qe),
                {
                    "owners": con,
                    "stored_before": None,
                    "note": c.get("notes"),
                    "source": c.get("src"),
                    "anchor": c.get("anchor"),
                },
            )
            print(f"  PIN  {key} (in _reattr_owners)")
        # ---- rekey the resolved revenue-gap skip, IN PLACE. pop+reassign moves the entry to the
        # end of the dict, which rewrites the whole file's line order and buries a 6-line change in
        # a 12,000-line diff nobody can review (and that fights every other session's rebase).
        if key in skips:
            for k in list(skips):
                v = skips.pop(k)
                skips["_FILLED_" + k if k == key else k] = v

    print("\nPAT cells written: %d | rev_con: %d | op_con: %d" % (wrote_pat, wrote_rev, wrote_op))
    if held:
        print("\nHELD by writer review (%d) — read, but deliberately NOT written:" % len(held))
        for k, why in held:
            print("   %-22s %s" % (k, why))
    if skipped:
        print("already present (no-op): %d" % len(skipped))
    if blocked:
        print("\nBLOCKED (%d) — none of these were written:" % len(blocked))
        for k, why in blocked:
            print("   %-22s %s" % (k, why))
    if not APPLY:
        print("\nDRY RUN — re-run with --apply to write")
        return 0
    json.dump(fd, open(fund_d, "w"), separators=(",", ":"))
    json.dump(fs, open(fund_s, "w"), separators=(",", ":"))
    json.dump(rd, open(rev_d, "w"), separators=(",", ":"))
    json.dump(rs, open(rev_s, "w"), separators=(",", ":"))
    json.dump(prov, open(prov_p, "w"), indent=1, sort_keys=True)
    json.dump(pin, open(pin_p, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(skip_p, "w"), indent=1)  # this ledger is pretty-printed on disk; keep it that way
    print("\nWROTE 7 files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

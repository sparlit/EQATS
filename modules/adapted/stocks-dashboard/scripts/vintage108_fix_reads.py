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
"""REPLAY-PROOFING — correct the READS themselves, not just the cells they wrote.

A heal that leaves the source read wrong gets re-poisoned the moment anyone resets and replays the
applier (memory: feedback-a-heal-that-reapplies; §108 did exactly this for SYNGENE). Here the
source read IS the root cause: the 2026-07-27 pass recorded, per cell, the NSE archive page it
read — and for 326 window cells that page is the RESTATEMENT, not the original filing.

This rewrites those entries in place, in every reads ledger and in the `vision_rev_fills`
provenance mirror:

    rev / op / pat_seen  ->  the values on the EARLIEST-FILED page for that (sym, qe, basis)
    src                  ->  that page, with a note naming the wrong page it replaces

⚠️ ALL-OR-NOTHING PER ENTRY. If any needed as-filed line is unreadable — the Ind-AS "New" layout
prints no operating-profit subtotal at all — the entry is left ALONE and listed in the residue. A
half-corrected read (as-filed revenue beside a restated op) is worse than an honestly wrong one,
because nothing downstream can tell the two vintages apart any more.

RUN:  python3 scripts/vintage108_fix_reads.py            # report
      python3 scripts/vintage108_fix_reads.py --apply
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SEQ = re.compile(r"financial_res_([A-Za-z0-9&._-]+)_(\d+)\.html", re.IGNORECASE)
STAMP = "2026-08-24"
# Write each ledger the way ITS OWN writer does. vision_rev_fills.json is dumped by
# _apply_reads.py as indent=0/sort_keys — rewriting it at indent=1 reformats all 175k lines, which
# buries 316 real changes and turns a routine merge into a conflict (memory:
# feedback-minified-json-never-merge).
FMT = {"vision_rev_fills.json": {"indent": 0, "sort_keys": True}}


def vintages():
    """(sym, qe, basis) -> [vintage rows, earliest filed first]"""
    out = {}
    for name, basis in (("_vintage108_nse.json", "std"), ("_vintage108_nse_con.json", "con")):
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            print(f"  (ledger {name} absent — {basis} entries cannot be checked)")
            continue
        for v in json.load(open(p, encoding="utf-8")).values():
            vs = [x for x in v.get("vintages", []) if x.get("pat") is not None and x.get("cumulative") != "Cumulative"]
            if len(vs) > 1:
                out[(v["sym"], v["qe"], basis)] = vs
    return out


def fixed_src(sym, seq_new, seq_old, filed_old):
    return (
        f"nse-archive financial_res_{sym}_{seq_new}.html (AS-FILED) — CORRECTED {STAMP}: the original read "
        f"used _{seq_old}.html, the RESTATEMENT filed {filed_old} (runbook §108 vintage class)"
    )


def main():
    apply = "--apply" in sys.argv
    V = vintages()
    # A cell whose as-filed page an independent reader CONTRADICTS must not have that page's
    # numbers written into the reads ledger either — the correction would be as wrong as the
    # value it replaces (FSL Sep-2015: the as-filed page reads a tenth of what detres does).
    veto = set()
    pp = os.path.join(HERE, "_vintage108_proposals.json")
    if os.path.exists(pp):
        for q, ks in (json.load(open(pp, encoding="utf-8")).get("queues") or {}).items():
            if "detres-contradicts" in q or "as-filed-line-unreadable" in q:
                for k in ks:
                    sym, qe = k.split("|")
                    veto.add((sym, int(qe)))
    print("cells vetoed by a contradicting reader: %d" % len(veto))
    print("periods with more than one filing on record: %d" % len(V))
    residue, changed_files = [], {}

    def repair(sym, qe, basis, cell, seq):
        """-> (new_cell, note) or (None, reason)."""
        if (sym, int(qe)) in veto:
            return None, "vetoed-contradicting-reader"
        vs = V.get((sym, int(qe), basis))
        if not vs:
            return None, "no-vintage-record"
        if str(vs[0].get("seq")) == str(seq):
            return None, "already-as-filed"
        old = next((x for x in vs if str(x.get("seq")) == str(seq)), None)
        if old is None:
            return None, "src-page-not-in-list"
        need = [k for k in ("rev", "op") if k in cell and cell[k] is not None]
        if any(vs[0].get(k) is None for k in need) or vs[0].get("pat") is None:
            return None, "as-filed-line-unreadable"
        new = dict(cell)
        for k in need:
            new[k] = round(vs[0][k], 2)
        if "pat_seen" in cell:
            new["pat_seen"] = round(vs[0]["pat"], 2)
        new["src"] = fixed_src(sym, vs[0].get("seq"), seq, old.get("filed"))
        return new, "{} -> {}".format(seq, vs[0].get("seq"))

    # ---- reads ledgers: {SYM: {QE: {basis, rev, op, pat_seen, src}}} ----
    for path in sorted(glob.glob(os.path.join(HERE, "_*reads*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        n = 0
        for sym, per in d.items():
            if not isinstance(per, dict):
                continue
            for qe, cell in per.items():
                if not isinstance(cell, dict) or not str(qe).isdigit():
                    continue
                m = SEQ.search(cell.get("src") or "")
                if not m:
                    continue
                new, note = repair(sym, qe, cell.get("basis", "std"), cell, m.group(2))
                if new is None:
                    if note not in (
                        "already-as-filed",
                        "no-vintage-record",
                        "src-page-not-in-list",
                        "vetoed-contradicting-reader",
                    ):
                        residue.append(
                            "{} {}|{}|{} {}".format(os.path.basename(path), sym, qe, cell.get("basis"), note)
                        )
                    continue
                print("  %-26s %s|%s|%s  %s" % (os.path.basename(path), sym, qe, cell.get("basis"), note))
                per[qe] = new
                n += 1
        if n:
            changed_files[path] = (d, n)

    # ---- provenance mirror: {"SYM|QE": {"std": {...}, "con": {...}}} ----
    vp = os.path.join(HERE, "vision_rev_fills.json")
    if os.path.exists(vp):
        d = json.load(open(vp, encoding="utf-8"))
        n = 0
        for key, per in d.items():
            if "|" not in key or not isinstance(per, dict):
                continue
            sym, qe = key.split("|", 1)
            for basis in ("std", "con"):
                cell = per.get(basis)
                if not isinstance(cell, dict):
                    continue
                m = SEQ.search(cell.get("src") or "")
                if not m:
                    continue
                new, note = repair(sym, qe, basis, cell, m.group(2))
                if new is None:
                    if note not in (
                        "already-as-filed",
                        "no-vintage-record",
                        "src-page-not-in-list",
                        "vetoed-contradicting-reader",
                    ):
                        residue.append(f"vision_rev_fills {key}|{basis} {note}")
                    continue
                print("  %-26s %s|%s  %s" % ("vision_rev_fills.json", key, basis, note))
                per[basis] = new
                n += 1
        if n:
            changed_files[vp] = (d, n)

    print("\ncorrected entries: %d across %d files" % (sum(n for _, n in changed_files.values()), len(changed_files)))
    if residue:
        print("LEFT ALONE (all-or-nothing per entry): %d" % len(residue))
        for r in residue[:12]:
            print(f"   {r}")
    if apply:
        for path, (d, n) in changed_files.items():
            json.dump(d, open(path, "w"), **(FMT.get(os.path.basename(path)) or {"indent": 1, "ensure_ascii": False}))
            print("  wrote %s (%d)" % (os.path.basename(path), n))
    else:
        print("\n(dry run — pass --apply to rewrite the reads ledgers)")


if __name__ == "__main__":
    main()

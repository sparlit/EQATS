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
"""Per-quarter LINE ITEMS from Moneycontrol's quarterly-results feed, for the cells the NSE
XBRL cache (build_xbrl_extra.py) and the NSE archive HTML (xtra_nse_html.py) could not reach:
2002-2004 (the archive starts 2005), NSE index holes, refused EPS rows, companies NSE's results
list never carried (BAYERCROP / ABBOTINDIA / MCX / KENNAMET: 0-1 list rows, measured
2026-09-05), and the insurers whose IRDAI-format XBRL carries no per-share tag at all.

Written into the SAME ledger (scripts/xbrl_extra.json[.gz]) with `src: "mc:<sc_id>:<table>"`,
lowest precedence: never over an XBRL or an nse-html basis-cell.

THE FEED (runbook §81b; every label below was read off a live payload 2026-09-05, RELIANCE /
SBIN, standalone `quarterly` and consolidated `cons_quarterly`):
  Other Income · Interest (industrial finance cost) · Interest Expended (bank) · depreciat /
  Depreciation (the standalone and consolidated tables spell it differently — both are candidates,
  memory: agg_sources MC_ROWS) · Tax · P/L Before Tax · Exceptional Items · Employees Cost ·
  Consumption of Raw Materials · Basic EPS / Diluted EPS (before extraordinary) and
  "Basic EPS." / "Diluted EPS." with a TRAILING DOT (after extraordinary — preferred, matching the
  XBRL tag order and the archive's "after Extraordinary items" rows). "--" is absent; a printed
  0.00 is the not-reported sentinel (§81e B) and is held except for Exceptional Items.
  Reach: standalone back to Jun-1997 (RELIANCE 117 rows), consolidated from ~2013.

THE GATE (§81e, adapted — Moneycontrol is ONE vendor, so nothing here is corroboration, it is a
reader that has to prove itself against what the filings already gave us):
  T  TABLE identity, per (symbol, basis): the feed's PAT row (standalone "Net Profit/(Loss) For
     the Period"; consolidated "Net P/L After M.I & Associates" = owners) must reproduce our
     STORED PAT (sf_fundamentals) AT THE TARGET QUARTER within max(0.06 cr, 0.5%) (§123d's
     Moneycontrol anchor tolerance) AND pass agg_gate.check_series around it (>=2 local anchors,
     none disagreeing, one within 4 quarters, <15% global disagreement). Proves entity, basis,
     unit and that the column is the quarter, per cell.
  C  CON-COPY (§85): a consolidated target is refused when the feed's consolidated PAT equals its
     own standalone PAT for that quarter while our store shows con != std for the company
     elsewhere — the feed fell back to standalone.
  R  ROW identity, per (symbol, basis, field): the feed's row must reproduce the values this
     ledger already holds for that field (XBRL / archive reads) on >= MIN_ROW_ANCHORS quarters
     with ZERO disagreements at agg_gate's rounded tolerance and no more than 15% far-away
     disagreements (restatements) — a row that does not reproduce our figures is a DIFFERENT
     quantity (bank "Interest" vs finance cost, "Tax" incl./excl. deferred), not "close enough".
     A field with no overlap at all cannot be proven and is refused as `row-unproven`.
  Z  zero sentinel (above); B2 a target quarter that is a restated duplicate column in the feed
     is dropped by agg_sources (ambiguous vintage).

Run:  python3 scripts/xtra_mc.py [--universe n500|all] [--years 2002-2017] [--post2018]
        [--only SYM,SYM] [--limit N] [--apply]
      Journals to scripts/_xtra_mc_reads.json / _xtra_mc_skips.json; --apply writes the ledger.
"""
import collections
import gzip
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import _n500_member_bin as MB
import agg_gate as G  # check_series — the §81e series gate
import agg_sources as A  # mc_id / _get / qe_from_label / _num — the §81 transport

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGER = os.path.join(HERE, "xbrl_extra.json")
LEDGER_GZ = LEDGER + ".gz"
READS = os.path.join(HERE, "_xtra_mc_reads.json")
SKIPS = os.path.join(HERE, "_xtra_mc_skips.json")

PAT_ABS, PAT_REL = 0.06, 0.005  # §123d Moneycontrol PAT anchor tolerance
MIN_ROW_ANCHORS = 2
ROW_MAX_BAD = 0.15
FIELDS = ["oi", "fc", "int_exp", "dep", "tax", "pbt", "exc", "emp", "mat", "eps_b", "eps_d"]
# our field -> feed labels, most specific first; both spellings where the two tables differ
MC_LINE = {
    "oi": ("Other Income",),
    "fc": ("Interest",),
    "int_exp": ("Interest Expended",),
    "dep": ("depreciat", "Depreciation"),
    "tax": ("Tax",),
    "pbt": ("P/L Before Tax",),
    "exc": ("Exceptional Items",),
    "emp": ("Employees Cost",),
    "mat": ("Consumption of Raw Materials",),
    "eps_b": ("Basic EPS.", "Basic EPS"),
    "eps_d": ("Diluted EPS.", "Diluted EPS"),
}
MC_PAT = {"s": ("Net Profit/(Loss) For the Period",), "c": ("Net P/L After M.I & Associates",)}
KEEP_ZERO = {"exc"}


def mc_table(sym, basis):
    """{qe: {field: value, 'pat': v}} for one basis, straight off the feed; ('' , note) on miss."""
    ident = A.mc_id(sym)
    if not ident:
        return None, "mc: no exact symbol match in autosuggest", None
    tf = "cons_quarterly" if basis == "c" else "quarterly"
    txt = A._get(
        "appfeeds.moneycontrol.com",
        A.MC_FEED % (ident["sc_id"], tf),
        A.MC_PACE,
        "mc",
        "q_{}_{}".format(ident["sc_id"], tf),
    )
    if txt is None:
        return None, "mc: BLOCKED-TRANSPORT", ident
    try:
        rows = (json.loads(txt) or {}).get("data") or []
    except ValueError:
        return None, "mc: unparseable body", ident
    if not isinstance(rows, list) or not rows:
        return None, f"mc: empty {tf} table", ident
    out, dupes = {}, set()
    for r in rows:
        qe = A.qe_from_label(r.get("yrc0"))
        if qe is None or qe % 10000 not in (331, 630, 930, 1231):
            continue
        if qe in out:
            dupes.add(qe)
            continue
        vals = {}
        for f, labels in MC_LINE.items():
            for lbl in labels:
                if lbl in r:
                    v = A._num(r[lbl])
                    if v is not None:
                        vals[f] = v
                        break
        for lbl in MC_PAT[basis]:
            if lbl in r and A._num(r[lbl]) is not None:
                vals["pat"] = A._num(r[lbl])
                break
        if basis == "c":
            for lbl in MC_PAT["s"]:  # the feed's own standalone-style PAT row on the con table
                if lbl in r and A._num(r[lbl]) is not None:
                    vals["pat_period"] = A._num(r[lbl])
                    break
        if vals:
            out[qe] = vals
    for qe in dupes:
        out.pop(qe, None)
    return out, "mc: %d quarters" % len(out), ident


def load_ledger():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER))
    return json.loads(gzip.decompress(open(LEDGER_GZ, "rb").read()))


def build_targets(universe, y0, y1, post2018, ledger, fund):
    """{sym: {qe: {basis: stored_pat}}} — cells with a stored PAT whose ledger basis-cell lacks
    eps_b (or is absent), within the year window (+ every 2018+ hole with --post2018)."""
    tg = {}
    for sym, rows in fund.items():
        ns = MB.norm(sym)
        for r in rows:
            qe = int(r[0])
            y = qe // 10000
            if not ((y0 <= y <= y1) or (post2018 and y >= 2018)):
                continue
            bases = {}
            if r[1] is not None:
                bases["s"] = r[1]
            if len(r) > 3 and r[3] is not None:
                bases["c"] = r[3]
            if not bases:
                continue
            if universe == "n500" and ns not in MB.membership(qe):
                continue
            have = (ledger.get(sym) or {}).get(str(qe)) or {}
            for b in list(bases):
                cell = have.get(b)
                if cell and cell.get("eps_b") is not None and not str(cell.get("src", "")).startswith("mc"):
                    bases.pop(b)
            if bases:
                tg.setdefault(sym, {})[qe] = bases
    return tg


def ours_field(ledger, sym, basis, field):
    """{qe: value} this ledger holds for the field on that basis, XBRL or archive-HTML only."""
    out = {}
    for qe, cell in (ledger.get(sym) or {}).items():
        d = cell.get(basis)
        if d and d.get(field) is not None and not str(d.get("src", "")).startswith("mc"):
            out[int(qe)] = d[field]
    return out


def row_identity(series, ours, field):
    """Gate R: the feed row reproduces our stored values for this field."""
    matched, bad, worst = 0, [], 0.0
    for qe, mine in ours.items():
        theirs = (series.get(qe) or {}).get(field)
        if theirs is None:
            continue
        if G._agree(mine, theirs) == "no":
            bad.append("%d ours=%s mc=%s" % (qe, mine, theirs))
        else:
            matched += 1
            worst = max(worst, abs(mine - theirs))
    if matched + len(bad) == 0:
        return False, "row-unproven(no overlap)", matched
    if matched < MIN_ROW_ANCHORS:
        return False, "row-anchors %d<%d" % (matched, MIN_ROW_ANCHORS), matched
    if len(bad) / float(matched + len(bad)) > ROW_MAX_BAD or (bad and matched < 6):
        return False, "row-disagrees %d/%d: %s" % (len(bad), matched + len(bad), "; ".join(bad[:2])), matched
    return True, "row ok %d anchors, %d far disagreements, worst %.3f" % (matched, len(bad), worst), matched


def main():
    argv = sys.argv

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    universe = opt("--universe", "n500")
    y0, y1 = (int(x) for x in opt("--years", "2002-2017").split("-"))
    post2018 = "--post2018" in argv
    only = set(opt("--only", "").split(",")) - {""}
    limit = int(opt("--limit", 0) or 0)
    do_apply = "--apply" in argv

    ledger = load_ledger()
    fund = json.load(open(FUND))
    fmap = {s: {int(r[0]): r for r in rows} for s, rows in fund.items()}
    reads = json.load(open(READS)) if os.path.exists(READS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    targets = build_targets(universe, y0, y1, post2018, ledger, fund)
    syms = sorted(targets)
    if only:
        syms = [s for s in syms if s in only]
    if limit:
        syms = syms[:limit]
    print("targets: %d symbols, %d quarter-cells" % (len(syms), sum(len(targets[s]) for s in syms)), flush=True)

    landed = 0
    t0 = time.time()
    for si, sym in enumerate(syms, 1):
        want = targets[sym]
        bases_needed = sorted({b for q in want.values() for b in q})
        tables = {}
        for b in bases_needed:
            tbl, note, ident = mc_table(sym, b)
            if tbl is None:
                skips[f"{sym}|table|{b}"] = note
                continue
            tables[b] = (tbl, ident)
        if not tables:
            continue
        # our PAT series per basis (sf_fundamentals) for gate T
        ours_pat = {
            b: {
                q: r[1 if b == "s" else 3]
                for q, r in fmap[sym].items()
                if len(r) > (1 if b == "s" else 3) and r[1 if b == "s" else 3] is not None
            }
            for b in bases_needed
        }
        con_differs = any(
            r[1] is not None and len(r) > 3 and r[3] is not None and abs(r[1] - r[3]) > max(0.06, abs(r[3]) * 0.005)
            for r in fmap[sym].values()
        )
        # gate R per (basis, field), computed once per symbol
        row_ok = {}
        for b, (tbl, ident) in tables.items():
            for f in FIELDS:
                ok, why, n = row_identity(tbl, ours_field(ledger, sym, b, f), f)
                row_ok[(b, f)] = (ok, why)
        for qe in sorted(want):
            for b, stored in want[qe].items():
                if b not in tables:
                    continue
                tbl, ident = tables[b]
                key = "%s|%d|%s" % (sym, qe, b)
                row = tbl.get(qe)
                if not row:
                    skips[key] = "mc: no %s column for %d" % (b, qe)
                    continue
                pat = row.get("pat")
                if pat is None:
                    skips[key] = "mc: no PAT row at %d" % qe
                    continue
                if abs(pat - stored) > max(PAT_ABS, abs(stored) * PAT_REL):
                    skips[key] = f"T: PAT {pat} vs stored {stored}"
                    continue
                pser = {q: {"pat": v.get("pat")} for q, v in tbl.items()}
                # PAT anchors at the §123d Moneycontrol tolerance (max 0.06 cr, 0.5%): stored PAT
                # is often crore-rounded to 1-2 dp (360ONE Dec-2019 ours -2.6 vs feed -2.62 read
                # as a DISAGREEMENT at agg_gate's 0.02 and vetoed six quarters). Row identity
                # (gate R) keeps agg_gate's own print-precision tolerance.
                save = (G.ROUND_ABS, G.ROUND_REL)
                G.ROUND_ABS, G.ROUND_REL = PAT_ABS, PAT_REL
                try:
                    g = G.check_series(pser, ours_pat[b], "pat", qe, field="pat")
                finally:
                    G.ROUND_ABS, G.ROUND_REL = save
                if not g["ok"]:
                    skips[key] = "T-series: " + g["why"][:120]
                    continue
                if (
                    b == "c"
                    and con_differs
                    and row.get("pat_period") is not None
                    and abs(row["pat_period"] - pat) < 1e-9
                    and tables.get("s")
                    and (tables["s"][0].get(qe) or {}).get("pat") is not None
                    and abs(tables["s"][0][qe]["pat"] - pat) < 1e-9
                ):
                    skips[key] = "C: con PAT == std PAT on the feed (con-copy, §85)"
                    continue
                fields, notes = {}, {}
                for f in FIELDS:
                    v = row.get(f)
                    if v is None:
                        continue
                    ok, why = row_ok[(b, f)]
                    if not ok:
                        notes[f] = why[:80]
                        continue
                    if abs(v) < 1e-9 and f not in KEEP_ZERO:
                        notes[f] = "zero-sentinel"
                        continue
                    fields[f] = round(v, 2)
                if not fields:
                    skips[key] = "no field passed gate R: {}".format(
                        "; ".join("{}={}".format(*kv) for kv in list(notes.items())[:3])
                    )
                    continue
                skips.pop(key, None)
                reads.setdefault(sym, {}).setdefault(str(qe), {})[b] = {
                    "fields": fields,
                    "src": "mc:{}:{}".format(ident["sc_id"], "cons_quarterly" if b == "c" else "quarterly"),
                    "chk": {
                        "pat_anchor": pat,
                        "series": g["why"] or "ok %d local" % g["local"],
                        "rows": {f: row_ok[(b, f)][1][:60] for f in fields},
                        "held": notes,
                    },
                }
                landed += 1
        if si % 10 == 0 or si == len(syms):
            json.dump(reads, open(READS, "w"), separators=(",", ":"))
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            print(
                "  [%d/%d] %d landed, %d skips, %.0fs" % (si, len(syms), landed, len(skips), time.time() - t0),
                flush=True,
            )
    json.dump(reads, open(READS, "w"), separators=(",", ":"))
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    print("DONE: %d basis-cells landed this run; %d skips" % (landed, len(skips)))
    if do_apply:
        n = apply_reads(reads, ledger)
        json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
        open(LEDGER_GZ, "wb").write(gzip.compress(open(LEDGER, "rb").read(), 9))
        print("applied %d basis-cells -> %s (+gz)" % (n, os.path.basename(LEDGER)))


def apply_reads(reads, ledger):
    """Lowest precedence, two shapes:
    * no cell, or an `mc` cell        -> the cell is (re)written whole, `src: mc:…`
    * an XBRL / nse-html cell exists  -> ONLY fields that cell lacks are added (the insurers'
      IRDAI XBRL carries pbt/oi/assets but no per-share tag), listed under `src_mc` so the
      provenance stays per field; the cell-level `src` (or its absence = XBRL) is untouched.
      build_xbrl_extra's accumulate prunes `src_mc` when a later XBRL parse supplies a field."""
    n = 0
    for sym, qs in reads.items():
        for qe, pb in qs.items():
            for b, ent in pb.items():
                cell = ledger.setdefault(sym, {}).setdefault(str(qe), {})
                cur = cell.get(b)
                if cur and not str(cur.get("src", "")).startswith("mc"):
                    added = [f for f, v in ent["fields"].items() if cur.get(f) is None]
                    if not added:
                        continue
                    for f in added:
                        cur[f] = ent["fields"][f]
                    cur["src_mc"] = sorted(set(cur.get("src_mc", [])) | set(added))
                    n += 1
                    continue
                new = dict(ent["fields"])
                new["src"] = ent["src"]
                cell[b] = new
                n += 1
    return n


if __name__ == "__main__":
    main()

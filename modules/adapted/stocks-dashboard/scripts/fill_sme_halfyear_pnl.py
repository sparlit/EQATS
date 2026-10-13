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
"""P&L detail + operating profit for SME result rows PROVEN to be half-years (runbook §213).

WHY
  NSE SME companies file half-yearly: the Sep row is Apr-Sep, the Mar row Oct-Mar (§181d). build_xbrl_extra parses their
  half-year / yearly filings balance-sheet-only BY DESIGN (§148 parse_bs_only: a filing whose own period spans > 100 days
  never files P&L under a quarter), and the §181d filler stored revenue + profit only. So these rows had no depreciation /
  interest / tax detail, the stock page no annual P&L and no ROCE for them, and operating profit was EMPTY on 1,464 of
  them (ZEAL Apr-Sep 2025). scripts/row_periods.json now proves which rows are six months (§191); this fills them.

THE FILING (per row that row_periods marks m = 6, per basis whose revenue it proves)
  A half-year / yearly results XBRL of that company (its page by build_row_periods.page_resolver — one identity rule,
  §203 ISIN guards), routed BS-only by build_xbrl_extra (its period is > 100 days), whose OneD revenue EQUALS the proven
  half AND whose OneD profit equals the profit the page shows on the row (its fin slice — what build_row_periods proved
  against) — the row is tied to the column by two numbers, not one.
  Of several such filings the latest (a re-filing that left revenue and profit alone: an EPS or tax-split correction).
  Rows proven by a BSE h=1 cell ("bse-pf") are the BSE route's (fetch_bse_results_xbrl keeps OneD P&L there only when
  OneD IS the half, §196) and are left to it.

WRITES (fill-only; user decisions 2026-09-28: "Proven rows, no EPS", "Fill op + EBIT")
  1. scripts/xbrl_extra.json.gz — that column's P&L lines (build_xbrl_extra.PNL: other income, finance costs,
     depreciation, tax, current / deferred tax, exceptional, PBT, pre-exceptional PBT, employee / material cost, OCI,
     associates, minority), the audit flags, and "pm": 6 (this cell's P&L covers six months — the nightly then never
     blends a quarter parse into it), into the (symbol, quarter-end, basis) cell ONLY when it holds no P&L line yet.
     NOT EPS: in 252 of 984 years the two halves' EPS do not add up to the printed year (AIMTRON FY26 consolidated
     9.94 + 22.47 vs the printed 22.47 — the second column repeats the year's EPS).
  2. docs/sf_revop.json + scripts/revop_fundamentals.json — operating profit / EBIT into EMPTY slots only, from the same
     column with the stores' own reader (build_revop.metrics_for: op = pre-exceptional PBT + finance costs +
     depreciation - other income; EBIT = op - depreciation), only when all four lines are printed (a missing line is
     never read as 0 — §209), never a new row, never a bank / NBFC row, strip_lender_ebit applied. On these files the
     reader reproduces the op the stores already hold on 706 of 707 halves (GOLDKART: negative depreciation, held).
  Journal: scripts/sme_halfyear_fills.json {"SYM|QE|std|con": {f, rev, pat, pnl: [lines], aq: [flags added], op, ebit}}
  — op / ebit only when written here; verify_fills_live re-checks them after every refresh (BASIS_KEYED).
  RETRACTION (every run, before filling): a journalled row that LOST ITS PROOF — row_periods no longer marks it six
  months on that basis, or the page row no longer shows the revenue / profit the filing was matched on — gets back
  exactly what was written: op / EBIT still holding the journalled value (a store row left with nothing else is
  removed), the cell's P&L lines + pm (+ aq). A filing missing from this Mac is not a lost proof. More than max(50, 5 %)
  of the journal at once aborts unless --force-retract (a wrong slice set must not take everything back).
  HELD (printed, never written): negative depreciation (GOLDKART, ITALIANE, ROXHITECH — §205's class); no filing prints
  the stored profit (IPSL con 0.00 vs 3.88; MAHICKRA 2.53 vs 1.19; …); no filing whose OneD is the half (IEML: OneD
  empty, the half is in FourD); a filing armed in scale_fix (its revenue is read unscaled here — none today).

RUN (on the Mac — the SME XBRL cache is local; after every row_periods regeneration, §191 upkeep)
  SME_CACHE=/Users/dhruvan/stocks-dashboard/scripts/_xbrl_cache_sme \\
  XBRL_CACHE=/Users/dhruvan/stocks-dashboard/scripts/_xbrl_cache  python3 scripts/fill_sme_halfyear_pnl.py [--apply]
  [--plan OUT.json] [--check]
  Dry run by default. Idempotent: a second --apply writes nothing. --check: every journalled value still served?
"""
import argparse
import gzip
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import build_revop as BR  # noqa: E402  metrics_for: the stores' op / EBIT reader
import build_row_periods as R  # noqa: E402  parse() + page_resolver(): the row proof's own reader and identity
import build_xbrl_extra as X  # noqa: E402  parse_file routing + the P&L tag tables

GZ = os.path.join(HERE, "xbrl_extra.json.gz")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_L = os.path.join(HERE, "revop_fundamentals.json")
ROWP = os.path.join(HERE, "row_periods.json")
JOURNAL = os.path.join(HERE, "sme_halfyear_fills.json")
LINES = list(X.PNL)  # money lines only — EPS and ratios deliberately not
PNL_ANY = set(X.PNL) | set(X.EPS) | set(X.RATIO)
OP_IN = ("oi", "fc", "dep", "pbet")  # the four lines op / EBIT are made of
EQ = 0.0051  # two 2-dp crore figures that are the same number


def read(path):
    """One results XBRL: build_row_periods' facts (+ path, filing time, route). For a long-period (BS-only) file also its
    OneD P&L lines, audit flags and the stores' op / EBIT reading of the same column."""
    x = R.parse(path)
    if not x:
        return None
    f = os.path.basename(path)
    x["path"], x["ts"] = path, X.ts_key(f)
    try:
        r = X.parse_file(path, f)
    except Exception:
        r = None
    x["bso"] = bool(r and r.get("bso"))
    if not x["bso"]:
        return x
    xml = open(path, encoding="utf-8", errors="replace").read()
    x["armed"] = bool(X.scale_fix.factor(f))
    lines = {}
    for k in LINES:
        v = X.facts_by_ctx(xml, X.PNL[k]).get("OneD")
        if v is not None:
            lines[k] = round(v / X.CR, 2)
    x["lines"] = lines
    aud = X.RE_AUD.search(xml)
    x["aud"] = ("U" if "un" in aud.group(1).strip().lower()[:2] else "A") if aud else None
    x["qual"] = 1 if X.RE_QUAL.search(xml) else 0
    rev, op, ebit, _, _ = BR.metrics_for(xml, "OneD")
    x["m"] = [None if v is None else round(v, 2) for v in (rev, op, ebit)]
    x["lender"] = "InterestEarned" in xml or "NetPremiumIncome" in xml or "PremiumEarned" in xml
    return x


def load_json(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def check():
    """Every journalled value still where it was written: P&L lines in the ledger cell, op / EBIT in the served store."""
    jr = {k: v for k, v in load_json(JOURNAL, {}).items() if k.count("|") == 2}
    xl = json.loads(gzip.decompress(open(GZ, "rb").read()))
    revop = json.load(open(REVOP))
    miss = Counter()
    ex = []
    for k, v in jr.items():
        sym, qe, bs = k.split("|")
        b = "c" if bs == "con" else "s"
        cell = ((xl.get(sym) or {}).get(qe) or {}).get(b) or {}
        for ln in v.get("pnl") or []:
            if ln not in cell:
                miss["pnl line"] += 1
                ex.append((k, ln))
        row = (revop.get(sym) or {}).get(qe) or []
        for name, slot in (("op", 2), ("ebit", 7)):
            if name in v:
                s = slot + (1 if b == "c" else 0)
                cur = row[s] if len(row) > s else None
                if cur is None or abs(cur - v[name]) > 0.011:
                    miss[name] += 1
                    ex.append((k, name, v[name], cur))
    print("check: %d journalled cells; missing %s" % (len(jr), dict(miss) or 0))
    for e in ex[:20]:
        print("   MISSING", e)
    return 1 if miss else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--sme-cache", default=os.environ.get("SME_CACHE") or os.path.join(HERE, "_xbrl_cache_sme")
    )
    ap.add_argument(
        "--main-cache", default=os.environ.get("XBRL_CACHE") or os.path.join(HERE, "_xbrl_cache")
    )
    ap.add_argument("--fin", default=os.path.join(ROOT, "docs", "fin"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--plan", help="write every target with its verdict and values to this JSON")
    ap.add_argument("--check", action="store_true")
    ap.add_argument(
        "--force-retract",
        action="store_true",
        help="allow a retraction larger than max(50, 5%% of the journal)",
    )
    a = ap.parse_args()
    if a.check:
        sys.exit(check())

    # the SME cache (every half-year / yearly SME filing, §148) + the main cache's NON-Ind-AS files (later re-filings of
    # the same results land there through the nightly — ECOLINE / SPRL Mar-26)
    paths = []
    for d, only_na in ((a.sme_cache, False), (a.main_cache, True)):
        if not os.path.isdir(d):
            sys.exit(
                f"ABORT: {d} missing (set SME_CACHE / XBRL_CACHE) — refusing to fill from a partial file set"
            )
        paths += [
            os.path.join(d, f)
            for f in sorted(os.listdir(d))
            if not f.startswith(("list_", "."))
            and not f.endswith(".json")
            and (not only_na or "NONINDAS" in f.upper())
        ]
    with ProcessPoolExecutor(8) as ex:
        facts = [x for x in ex.map(read, paths, chunksize=32) if x]
    resolve, _, _ = R.page_resolver(a.fin)
    by = defaultdict(list)  # (page symbol, qe, basis) -> long-period filings
    for x in facts:
        if x["bso"]:
            sym, _ = resolve(x, "nse")
            if sym:
                by[(sym, x["qe"], x["b"])].append(x)

    rp = {k: v for k, v in load_json(ROWP, {}).items() if not k.startswith("_")}
    revop, revl = json.load(open(REVOP)), json.load(open(REVOP_L))
    from build_stock_fin import slug

    _sl = {}

    def slice_of(sym):
        if sym not in _sl:
            _sl[sym] = load_json(os.path.join(a.fin, slug(sym) + ".json"), {})
        return _sl[sym]

    xl = json.loads(gzip.decompress(open(GZ, "rb").read()))
    journal = load_json(JOURNAL, {})
    if "_note" not in journal:
        journal = dict(
            {
                "_note": "SME half-year P&L lines (xbrl_extra) and op / EBIT (sf_revop + revop_fundamentals) written "
                "by scripts/fill_sme_halfyear_pnl.py from the filing whose first column is the proven "
                "half (runbook §213). f = that filing, rev / pat = the row's revenue / profit it prints, "
                "pnl = detail lines added, op / ebit = store slots filled (absent = not written here)."
            },
            **journal,
        )
    C, H = Counter(), Counter()
    plan, n_lines, n_cells, n_op, n_ebit, n_rl = [], 0, 0, 0, 0, 0

    # RETRACT FIRST: an entry whose ROW lost its proof — row_periods no longer marks it six months on that basis, or the
    # page row no longer shows the revenue / profit the filing was matched on (another writer retracted or changed them)
    # — takes back exactly what this script wrote there: op / EBIT still holding the journalled value, a store row left
    # with nothing else in it, the cell's P&L lines + pm (+ the audit flags once the cell is balance-sheet-only again,
    # which is what it was). A filing merely missing from this Mac is NOT a lost proof and retracts nothing.
    # (§210c's retraction of 2020-25 PDF halves left 24 rows holding only this script's op / EBIT, 2026-09-28.)
    def row_ok(key, v):
        sym, qe, bs = key.split("|")
        b, i = ("s", 0) if bs == "std" else ("c", 1)
        e = (rp.get(sym) or {}).get(qe) or {}
        if e.get("m") != 6 or e.get("src") == "bse-pf" or e.get(b) is None:
            return False
        F = slice_of(sym)
        prow = (F.get("revop") or {}).get(qe) or []
        prof = ({r[0]: r for r in (F.get("fund") or [])}.get(int(qe)) or [None] * 5)[
            1 if b == "s" else 3
        ]
        return (
            len(prow) > i
            and prow[i] is not None
            and abs(prow[i] - v["rev"]) <= EQ
            and prof is not None
            and R.same_row(prof, v["pat"])
        )

    stale = [
        k
        for k, v in journal.items()
        if k.count("|") == 2 and isinstance(v, dict) and not row_ok(k, v)
    ]
    n_jr = sum(1 for k in journal if k.count("|") == 2)
    if len(stale) > max(50, n_jr // 20) and not a.force_retract:
        sys.exit(
            "ABORT: %d of %d journalled rows lost their proof — more than expected; check row_periods / the slices, "
            "or pass --force-retract" % (len(stale), n_jr)
        )
    n_ret, kept_other = Counter(), []
    for key in stale:
        v = journal.pop(key)
        sym, qe, bs = key.split("|")
        b, i = ("s", 0) if bs == "std" else ("c", 1)
        for store, label in ((revop, "sf_revop"), (revl, "revop_fundamentals")):
            row = (store.get(sym) or {}).get(qe)
            if not row:
                continue
            nulled = False
            for name, slot in (("op", 2 + i), ("ebit", 7 + i)):
                if name in v and len(row) > slot and row[slot] is not None:
                    if abs(row[slot] - v[name]) <= 0.011:
                        row[slot] = None
                        nulled = True
                        n_ret[label + " " + name] += 1
                    else:
                        kept_other.append(
                            (key, label, name, row[slot], v[name])
                        )  # another writer's value: untouched
            if nulled and all(row[j] is None for j in (0, 1, 2, 3, 4, 5, 7, 8)):
                del store[sym][qe]
                n_ret[label + " rows left empty -> removed"] += 1
                if not store[sym]:
                    del store[sym]
        cell = ((xl.get(sym) or {}).get(qe) or {}).get(b)
        if cell and cell.get("pm") == 6:
            for k in (v.get("pnl") or []) + ["pm"]:
                cell.pop(k, None)
            if not any(k in cell for k in PNL_ANY):
                for k in v.get("aq", ("aud", "qual")):
                    cell.pop(k, None)
            if not cell:
                del xl[sym][qe][b]
                if not xl[sym][qe]:
                    del xl[sym][qe]
            n_ret["xbrl_extra cells"] += 1
        print(
            "  RETRACTED {} (row no longer proven / changed): {}".format(key, v.get("f", "")[:48])
        )
    for x in kept_other:
        print("  LEFT (another writer's value now):", x)

    for sym in sorted(rp):
        for qe, e in sorted(rp[sym].items()):
            if e.get("m") != 6:
                continue
            if e.get("src") == "bse-pf":
                C["row proven by a BSE h=1 cell — the BSE route's"] += 1
                continue
            for b, i in (("s", 0), ("c", 1)):
                prov = e.get(b)
                if prov is None:
                    continue
                C["targets (proven 6-month row, basis)"] += 1
                key = "{}|{}|{}".format(sym, qe, "std" if b == "s" else "con")
                rec = {"key": key}
                plan.append(rec)
                # the row as the PAGE publishes it (the slice — BSE folds and aliases included), exactly what
                # build_row_periods proved; the store row matters only for the op / EBIT write below
                F = slice_of(sym)
                prow = (F.get("revop") or {}).get(qe) or []
                prof = ({r[0]: r for r in (F.get("fund") or [])}.get(int(qe)) or [None] * 5)[
                    1 if b == "s" else 3
                ]
                row = (revop.get(sym) or {}).get(qe)

                def hold(why):
                    H[why] += 1
                    rec["held"] = why

                if len(prow) <= i or prow[i] is None or abs(prow[i] - prov) > EQ:
                    hold("the page's row no longer holds the proven revenue")
                    continue
                fl = by.get((sym, int(qe), b), [])
                cands = [x for x in fl if x["one"] is not None and abs(x["one"] - prov) <= EQ]
                if not cands:
                    hold(
                        "no half-year filing on this Mac"
                        if not fl
                        else "no filing whose first column is the proven half"
                    )
                    continue
                if prof is None:
                    hold("no profit stored on this basis")
                    continue
                m = [x for x in cands if any(R.same_row(prof, p) for p in x["pone"])]
                if not m:
                    hold("no such filing prints the stored profit")
                    continue
                x = max(m, key=lambda x: (x["ts"], os.path.basename(x["path"])))
                rec.update(f=os.path.basename(x["path"]), rev=prov, pat=prof)
                if x["armed"]:
                    hold("filing armed in scale_fix")
                    continue
                ln = x["lines"]
                if ln.get("dep") is not None and ln["dep"] < 0:
                    hold("negative depreciation (§205)")
                    continue
                entry = {"f": rec["f"], "rev": prov, "pat": prof}
                # 1. P&L lines into the ledger cell — only a cell with no P&L line yet (never blend two filings)
                cell = ((xl.get(sym) or {}).get(qe) or {}).get(b) or {}
                if cell.get("pm") == 6:
                    C["P&L: already filled (pm)"] += 1
                elif any(k in cell for k in PNL_ANY):
                    C["P&L: cell already holds P&L lines from another parse — left"] += 1
                elif ln:
                    cell = xl.setdefault(sym, {}).setdefault(qe, {}).setdefault(b, {})
                    if not cell:
                        C["P&L: cell created (no balance sheet on file)"] += 1
                    cell.update(ln)
                    aq = []
                    for k_, v_ in (("aud", x["aud"]), ("qual", x["qual"] or None)):
                        if v_ and k_ not in cell:
                            cell[k_] = v_
                            aq.append(k_)
                    cell["pm"] = 6
                    entry["pnl"] = sorted(ln)
                    if aq:
                        entry["aq"] = (
                            aq  # the flags this script added (a retraction takes back exactly these)
                        )
                    n_cells += 1
                    n_lines += len(ln)
                    C["P&L: cell filled"] += 1
                rec["lines"] = ln
                # 2. op / EBIT into EMPTY store slots, same column, the stores' reader
                rv_, op_, eb_ = x["m"]
                if not row or len(row) < 9 or row[i] is None or abs(row[i] - prov) > EQ:
                    C[
                        "op: no results-store row with this revenue (BSE fold / alias) — not filled"
                    ] += 1
                elif row[6] == 1 or x["lender"]:
                    C["op: bank / NBFC / insurer format — not filled"] += 1
                elif not all(k in ln for k in OP_IN):
                    C["op: a line of op not printed — not filled"] += 1
                elif rv_ is None or abs(rv_ - prov) > EQ or op_ is None:
                    C["op: the reader's revenue differs — not filled"] += 1
                else:
                    if sym in BR.LENDER_EBIT_NA:
                        eb_ = None
                    rec.update(op=op_, ebit=eb_)
                    for name, slot, v in (("op", 2 + i, op_), ("ebit", 7 + i, eb_)):
                        if v is None:
                            continue
                        cur = row[slot]
                        if cur is None:
                            row[slot] = v
                            entry[name] = v
                            if name == "op":
                                n_op += 1
                            else:
                                n_ebit += 1
                            C[name + ": slot filled"] += 1
                            rl = (revl.get(sym) or {}).get(qe)
                            if rl is not None and len(rl) > slot and rl[slot] is None:
                                rl[slot] = v
                                n_rl += 1
                        elif abs(cur - v) <= 0.011:
                            C[name + ": stored, equal"] += 1
                        else:
                            C[name + ": stored, DIFFERENT — left"] += 1
                            rec.setdefault("differs", []).append([name, cur, v])
                if len(entry) > 3:
                    journal[key] = dict(journal.get(key) or {}, **entry)
    for k in sorted(C):
        print("  %-58s %d" % (k, C[k]))
    for k in sorted(H):
        print("  HELD %-53s %d" % (k, H[k]))
    print(
        "write: %d cells gain %d P&L lines; op %d, EBIT %d slots in sf_revop (%d mirrored into revop_fundamentals)"
        % (n_cells, n_lines, n_op, n_ebit, n_rl)
    )
    print(
        "retract: %d journalled rows lost their proof — %s"
        % (len(stale), dict(n_ret) or "nothing to take back")
    )
    if a.plan:
        json.dump(plan, open(a.plan, "w"), separators=(",", ":"))
    if not a.apply:
        print("(dry run — pass --apply to write)")
        return
    rx = n_ret.get("xbrl_extra cells", 0)
    rs = sum(n for k, n in n_ret.items() if k.startswith("sf_revop"))
    rl_ = sum(n for k, n in n_ret.items() if k.startswith("revop_fundamentals"))
    if n_cells or rx:
        blob = json.dumps(xl, separators=(",", ":")).encode("utf-8")
        open(GZ, "wb").write(gzip.compress(blob, 9, mtime=0))
        print("wrote", os.path.relpath(GZ, ROOT))
    if n_op or n_ebit or rs:
        json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
        print("wrote", os.path.relpath(REVOP, ROOT))
    if n_rl or rl_:
        json.dump(revl, open(REVOP_L, "w"), separators=(",", ":"))
        print("wrote", os.path.relpath(REVOP_L, ROOT))
    if n_cells or n_op or n_ebit or stale:
        with open(JOURNAL, "w", encoding="utf-8") as fh:
            json.dump(journal, fh, ensure_ascii=False, indent=0, sort_keys=False)
            fh.write("\n")
        print("wrote", os.path.relpath(JOURNAL, ROOT), "(%d entries)" % (len(journal) - 1))


if __name__ == "__main__":
    main()

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


#!/usr/bin/env python3
"""N500 COVERAGE-100 CAMPAIGN — build and check the exhaustive per-stock work queue.

Campaign doc: scripts/N500_COVERAGE_100_CAMPAIGN.md  (Phase 0 tool)

WHAT IT DOES
  Turns "param X is 91.5%" into "these exact symbols, on these exact month-ends".
  Input is `--explain` output from build_coverage_matrix.js, which names the missing
  symbols from the SAME vm scan that wrote the payload — so the queue can never drift
  from the page (§92: measure THROUGH the engine, never re-implement it).

  build:  emits scripts/n500_cov_queue.json — one row per (param, symbol)
  --check: re-asserts every parity gate against the CURRENT payload

PARITY GATE (hard stop, campaign §3)
  For each param:  Σ(queue row month-counts)  ==  payload missing  ==  Σ(den − count)
  where den = members − na, exactly as docs/coverage.html:346-350 computes it.
  Roll members that never reached factorsAt (no price row at all) are carried in the
  explain file's `__norow` bucket and counted against EVERY param — omitting them
  would silently shrink the queue below the page's own numbers.

NO ASSUMPTIONS (campaign golden rule)
  This tool proposes a class ONLY where the proposal is itself a measurement:
    ebit/op/rev -> C1-candidate  when sf_revop holds the slot null in EVERY quarter
                   C4-candidate  when the slot is non-null in at least one quarter
  Everything else is emitted `unclassified`. A proposal is NOT a verdict: `class` stays
  null and `status` stays "open" until Phase 2 records per-name evidence. SPICEJET — an
  airline sitting in the never-has-ebit set — is why no category shortcut is allowed.

USAGE
  python3 scripts/n500_cov_cells.py build \
      [--from 2020-01-01] [--to 9999-12-31] [--campaign N500_COVERAGE_100] \
      [--explain scripts/n500_cov_explain.json] [--out scripts/n500_cov_queue.json]
  python3 scripts/n500_cov_cells.py --check [--out <queue>]   # window read FROM the queue file

WINDOW (added for the 2015→2020 era campaign, PLAN_N500_COVERAGE_2015_2020.md)
  --from/--to bound the payload AND explain dates. A queue file records its own from/to,
  and --check uses THOSE — never the CLI defaults — so checking an era queue can't silently
  re-window it. Defaults keep the original 2020→date behaviour byte-identical.
"""
import argparse
import collections
import gzip
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
SCRIPTS = os.path.join(ROOT, "scripts")
FROM = "2020-01-01"
TO = "9999-12-31"
CAMPAIGN = "N500_COVERAGE_100"
UNIVERSE = "nifty-500"


def load_payload():
    return json.load(open(os.path.join(DOCS, "coverage", f"{UNIVERSE}.json")))


def payload_missing(U):
    """Per-param missing counts and denominators, page math verbatim."""
    out = {}
    for pi, pk in enumerate(U["paramKeys"]):
        na_arr = U["na"][pi]
        miss = den = 0
        per_date = {}
        for di, d in enumerate(U["dates"]):
            if d < FROM or d > TO:
                continue
            mem, c = U["members"][di], U["params"][pi][di]
            if c < 0 or mem < 0:  # "–" no roll at this date
                continue
            na = na_arr[di] if (isinstance(na_arr, list) and na_arr[di] > 0) else 0
            dn = max(0, mem - na)
            m = max(0, dn - c)
            den += dn
            miss += m
            if m:
                per_date[d] = m
        out[pk] = {"missing": miss, "den": den, "per_date": per_date}
    return out


# ---------- sf_revop measurement (the only auto-proposed class) ----------
def revop_evidence():
    """symbol -> {field -> (n_quarters, n_with_value)} straight from sf_revop."""
    REVOP = json.load(open(os.path.join(DOCS, "sf_revop.json")))
    src = open(os.path.join(DOCS, "backtest-engine.js")).read()
    m = re.search(r"FUND_ALIAS\s*=\s*(\{.*?\})\s*;", src, re.DOTALL)
    alias = json.loads(re.sub(r"(\w+)\s*:", r'"\1":', m.group(1)).replace("'", '"')) if m else {}
    slot = {"rev": (1, 0), "op": (3, 2), "ebit": (8, 7)}

    def present(cell, f):
        ci, si = slot[f]
        return (len(cell) > ci and cell[ci] is not None) or (len(cell) > si and cell[si] is not None)

    def stats(sym, f):
        rmap = REVOP.get(sym) or REVOP.get(alias.get(sym, ""), None)
        if not rmap:
            return (0, 0, None)
        n = len(rmap)
        k = sum(1 for c in rmap.values() if present(c, f))
        # alias shadowing: a direct key that wins over an alias key holding MORE data
        shadow = None
        ali = alias.get(sym)
        if ali and sym in REVOP and ali in REVOP:
            d_q = {q for q, c in REVOP[sym].items() if present(c, f)}
            a_q = {q for q, c in REVOP[ali].items() if present(c, f)}
            extra = sorted(a_q - d_q)
            if extra:
                shadow = {"alias": ali, "quarters": extra}
        return (n, k, shadow)

    return stats


def build(explain_path, out_path):
    ex = json.load(open(explain_path))
    if ex.get("universe") != UNIVERSE:
        sys.exit(f"explain file is for {ex.get('universe')}, expected {UNIVERSE}")
    U = load_payload()
    pm = payload_missing(U)
    rvstats = revop_evidence()

    # ---- invert byDate -> (param, symbol) -> [months]
    cells = collections.defaultdict(lambda: collections.defaultdict(list))
    norow = collections.defaultdict(list)  # symbol -> [months] (missing EVERYTHING)
    for date, params in sorted(ex["byDate"].items()):
        if date < FROM or date > TO:
            continue
        for pk, syms in params.items():
            if pk == "__norow":
                for s in syms:
                    norow[s].append(date)
                continue
            for s in syms:
                cells[pk][s].append(date)

    rows = []
    for pk in sorted(cells):
        for sym, months in sorted(cells[pk].items()):
            proposed, note = "unclassified", ""
            if pk in ("rev", "op", "ebit"):
                nq, nk, shadow = rvstats(sym, pk)
                if nq == 0:
                    proposed = "unclassified"
                    note = f"no sf_revop rows for {sym}"
                elif nk == 0:
                    proposed = "C1-candidate"
                    note = f"{pk} slot null in all {nq} sf_revop quarters — needs a filing read to confirm the format lacks the line"
                else:
                    proposed = "C4-candidate"
                    note = f"{pk} present in {nk} of {nq} sf_revop quarters"
                if shadow:
                    proposed = "C4-candidate"
                    note += f" · ALIAS SHADOW: {len(shadow['quarters'])} {pk} quarters live under {shadow['alias']} ({', '.join(shadow['quarters'][:5])})"
            rows.append(
                {
                    "param": pk,
                    "symbol": sym,
                    "n": len(months),
                    "months": months,
                    "class_proposed": proposed,
                    "class": None,
                    "evidence": "",
                    "status": "open",
                    "ledger": "",
                    "note": note,
                }
            )

    for sym, months in sorted(norow.items()):
        rows.append(
            {
                "param": "__norow",
                "symbol": sym,
                "n": len(months),
                "months": months,
                "class_proposed": "unclassified",
                "class": None,
                "evidence": "",
                "status": "open",
                "ledger": "",
                "note": "roll member with no factorsAt row — missing EVERY parameter at these dates",
            }
        )

    parity = check_parity(rows, pm, verbose=True)
    doc = {
        "campaign": CAMPAIGN,
        "universe": UNIVERSE,
        "from": FROM,
        "to": TO,
        "payload_updated": U["updated"],
        "payload_dataEnd": U["dataEnd"],
        "explain_generated": ex.get("generated"),
        "n_rows": len(rows),
        "parity": parity,
        "rows": rows,
    }
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=1)
    print(
        f"\nwrote {out_path} · {len(rows)} rows · "
        f"{sum(r['n'] for r in rows if r['param'] != '__norow')} member-date cells"
    )
    return 0 if parity["ok"] else 1


def check_parity(rows, pm, verbose=False):
    """Σ(queue months) + norow contribution == payload missing, per param. Hard stop."""
    norow_dates = collections.Counter()
    for r in rows:
        if r["param"] == "__norow":
            for d in r["months"]:
                norow_dates[d] += 1
    by_param = collections.defaultdict(int)
    for r in rows:
        if r["param"] != "__norow":
            by_param[r["param"]] += r["n"]

    # PER-DATE counts too. A totals-only gate passes while the composition is wrong — the queue
    # could name the right NUMBER of cells on the wrong DATES and nothing would flag it.
    per_date = collections.defaultdict(collections.Counter)
    for r in rows:
        if r["param"] == "__norow":
            continue
        for d in r["months"]:
            per_date[r["param"]][d] += 1

    results, ok = {}, True
    gap_params = sorted(p for p, v in pm.items() if v["missing"] > 0)
    for pk in gap_params:
        want = pm[pk]["missing"]
        got = by_param.get(pk, 0) + sum(norow_dates.values())
        good = got == want
        bad_dates = []
        for d, m in pm[pk]["per_date"].items():
            if per_date[pk].get(d, 0) + norow_dates.get(d, 0) != m:
                bad_dates.append((d, per_date[pk].get(d, 0) + norow_dates.get(d, 0), m))
        for d, n in per_date[pk].items():
            if d not in pm[pk]["per_date"] and n:
                bad_dates.append((d, n, 0))
        good = good and not bad_dates
        ok &= good
        results[pk] = {
            "queue": got,
            "payload": want,
            "ok": good,
            "bad_dates": bad_dates[:5],
            "n_bad_dates": len(bad_dates),
        }
    # a param with zero missing must have zero queue rows
    for pk, n in by_param.items():
        if pm.get(pk, {}).get("missing", 0) == 0 and n:
            results[pk] = {"queue": n, "payload": 0, "ok": False}
            ok = False
    if verbose:
        print(f"{'param':14s} {'queue':>8s} {'payload':>8s}  parity (totals + per-date)")
        for pk in sorted(results):
            r = results[pk]
            tag = "OK" if r["ok"] else f"MISMATCH ({r.get('n_bad_dates', 0)} bad dates)"
            print(f"{pk:14s} {r['queue']:8d} {r['payload']:8d}  {tag}")
            for d, got, want in r.get("bad_dates", []):
                print(f"                 └─ {d}: queue {got} vs payload {want}")
        print(
            f"\nPARITY {'PASS' if ok else 'FAIL'} · {len(gap_params)} params with gaps · "
            f"{sum(pm[p]['missing'] for p in gap_params):,} missing cells total"
        )
    return {"ok": bool(ok), "params": results}


def main():
    global FROM, TO, CAMPAIGN
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="build", choices=["build"])
    ap.add_argument("--explain", default=os.path.join(SCRIPTS, "n500_cov_explain.json"))
    ap.add_argument("--out", default=os.path.join(SCRIPTS, "n500_cov_queue.json"))
    ap.add_argument("--from", dest="frm", default=FROM, help="first payload date counted (YYYY-MM-DD)")
    ap.add_argument("--to", dest="to", default=TO, help="last payload date counted (YYYY-MM-DD)")
    ap.add_argument("--campaign", default=CAMPAIGN)
    ap.add_argument("--check", action="store_true", help="re-assert parity of the existing queue")
    a = ap.parse_args()
    FROM, TO, CAMPAIGN = a.frm, a.to, a.campaign
    if a.check:
        q = json.load(open(a.out))
        # The queue's own window governs the check — CLI defaults must never re-window an era
        # queue (a 2015-19 queue checked against the 2020→date window would read as total FAIL).
        FROM = q.get("from", FROM)
        TO = q.get("to", TO)
        U = load_payload()
        # ⚠️ BAKE SKEW comes first. A queue is only comparable to the payload it was built from.
        # Local bakes are reverted after building (the release asset lags CI — campaign P0 note 1),
        # so docs/coverage/ normally holds CI's payload, NOT the one behind this queue. Comparing
        # across bakes reports "PARITY FAIL" for a queue that is perfectly correct; that false
        # alarm is worse than no check at all, because it sends the next session hunting a
        # phantom. Measured case, 2026-08-16: queue built at 13:22 (dataEnd 08-12) vs CI's 01:26
        # payload (dataEnd 08-14) -> profitTTM read 525 vs 524 and the run said FAIL.
        if q.get("payload_updated") != U["updated"]:
            print("BAKE SKEW — not a parity failure.")
            print(f"  queue was built against : {q.get('payload_updated')}  (dataEnd {q.get('payload_dataEnd')})")
            print(f"  payload on disk is      : {U['updated']}  (dataEnd {U['dataEnd']})")
            print("  Re-bake and rebuild the queue before trusting a parity result:")
            print("    node --max-old-space-size=12288 scripts/build_coverage_matrix.js --bin auto \\")
            print(
                f"         --out docs/coverage --explain nifty-500 --explain-from {FROM}"
                + (f" --explain-to {TO}" if TO < "9999-12-31" else "")
            )
            print(f"    python3 scripts/n500_cov_cells.py build --from {FROM} --to {TO} --out {a.out}")
            print(f"  (stored parity at build time: {'PASS' if q.get('parity', {}).get('ok') else 'FAIL'})")
            return 2
        r = check_parity(q["rows"], _pm := payload_missing(U), verbose=True)
        return 0 if r["ok"] else 1
    return build(a.explain, a.out)


if __name__ == "__main__":
    sys.exit(main())

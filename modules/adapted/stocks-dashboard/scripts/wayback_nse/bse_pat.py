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
"""Standalone NET PROFIT from BSE's ARCHIVED results page (Wayback), `bseindia.com/qresann/result.asp` —
the PAT sibling of bse_rev.py, for the 1999-2001 std-PAT ROOT cells no other route reaches
(PLAN_STDPAT_SHP_COVERAGE_2002 WP-P1; runbook §128f named this rung as "not yet walked").

The page DECLARES period ("Date Begin / Date End") and scale ("Value(Rs. million)") and prints
Net Profit + Equity Capital; it does NOT declare the basis, and for a root cell there is no stored
value to anchor on. So identity, basis and scale are proven PER SYMBOL, on the same page family:

  A  ANCHORS — the symbol's own HELD std-PAT quarters (2000-2007) that have an indexed 3-month
     capture must be REPRODUCED by the page's Net Profit (tol = half the printed grid, bse_rev.TOL
     floor): >= MIN_ANCHORS exact and ZERO conflicts. A wrong company, a consolidated page family
     or a scale slip cannot reproduce our standalone series to the paisa across quarters.
  G1 the page's ScripCode == the BSE code resolved for the symbol (read_page, bse_rev.py)
  G2 the capture ends ON the target quarter and covers exactly 3 months (cumulative MC/DC/SC pages
     are NOT differenced in this pass — refused, counted)
  G4 scale declared (read_page)
  G5 the Net Profit row is present and the page's own arithmetic, where printed, closes
     (Profit before Tax − Tax == Net Profit, or Gross Profit − Depreciation == PBT) within the grid

Calibration FIRST (--calib): every held std cell of the target symbols with an indexed 3-month page
is read blind and compared to the store — the mismatch rate is the reader's error and is printed
with its denominator before anything is proposed. Provenance-filtered: aggregator-derived stored
cells are excluded from the TRUTH side (feedback-calibrate-gate-by-holdout / PLAN_FAV14_PRE2009 §2e).

Output = a props file in apply_agg_pat_fills.py's schema (fill-only, row-creating, journalled in
agg_pat_cell_fills.json with --gate/--label), never a direct store write.

  python3 -X utf8 scripts/wayback_nse/bse_pat.py --cells C.json --calib --fetch --out /tmp/calib.json
  python3 -X utf8 scripts/wayback_nse/bse_pat.py --cells C.json --fetch --out /tmp/props.json
  python3 -X utf8 scripts/agg_tools/apply_agg_pat_fills.py --props /tmp/props.json [--apply] \
          --gate "BSE-archive A/G1/G2/G4/G5" --label "BSE archived results page std-PAT (STEP B, WP-P1)"
"""
import argparse
import collections
import glob
import gzip
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import bse_rev  # noqa: E402  (read_page, _read_any, INDEX)
import wbcache  # noqa: E402

MIN_ANCHORS = 2
ARCHIVE_YEARS = range(1999, 2009)


def load_json(p):
    return json.load(open(p, encoding="utf-8"))


def key_variants(sym, fund_alias, rmap):
    ks = {sym}
    if sym in fund_alias:
        ks.add(fund_alias[sym])
    for o, n in fund_alias.items():
        if n == sym:
            ks.add(o)
    for o, n in rmap.items():
        if n == sym:
            ks.add(o)
    if sym in rmap:
        ks.add(rmap[sym])
    return ks


def codes_for(sym, keys, bse_by_id, master_by_id, era_ledger):
    out = {}
    for k in keys:
        if k in bse_by_id:
            out[str(bse_by_id[k])] = "bse_scrips:" + k
        if k in master_by_id:
            out.setdefault(str(master_by_id[k]), "bse_master:" + k)
        e = era_ledger.get(k)
        if e and e.get("code"):
            out.setdefault(str(e["code"]), "era-ledger:{}:{}".format(k, e.get("isin")))
    return out


def _row(t, label):
    """Value printed right after a ROW LABEL. The label must START a row: preceded by the previous row's
    number or by the header 'Value(Rs. million)' — bse_rev._num's lookbehind lets 'Tax' match inside
    'Profit before Tax 245.00' (measured: 226 good pages refused, WP-P1 2026-09-05)."""
    m = re.search(r"(?:(?<=\d)\s+|\)\s+)" + re.escape(label) + r"\s+(-?[\d,]*\d(?:\.\d+)?)(?![\d.])", t)
    return float(m.group(1).replace(",", "")) if m else None


def arith_ok(raw_txt, tol_raw):
    """G5: the page's own SIGNED chain closes where printed (values print with their sign: Tax -20.60).
    PBT + Tax + Provisions == Profit after Tax (when printed) ; PAT (or PBT+Tax) + Extraordinary + Prior
    period == Net Profit ; Gross Profit + Depreciation == PBT. Returns (ok, detail)."""
    t = raw_txt
    pbt, tax, pat, npf = (
        _row(t, "Profit before Tax"),
        _row(t, "Tax"),
        _row(t, "Profit after Tax"),
        _row(t, "Net Profit"),
    )
    gp, dep = _row(t, "Gross Profit"), _row(t, "Depreciation")
    prov = _row(t, "Provisions and Contingencies") or 0.0
    extra = (
        (_row(t, "Extraordinary Items") or 0.0)
        + (_row(t, "Prior Period Adjustments") or 0.0)
        + (_row(t, "Prior Period Items") or 0.0)
    )
    tol = tol_raw * 2 + 1e-9
    checks = []
    if gp is not None and dep is not None and pbt is not None:
        checks.append(("GP+Dep==PBT", abs(gp + dep - pbt) <= tol))
    if pbt is not None and tax is not None:
        base = pbt + tax + prov
        if pat is not None:
            checks.append(("PBT+Tax+Prov==PAT", abs(base - pat) <= tol))
            if npf is not None:
                checks.append(("PAT+Extra==NP", abs(pat + extra - npf) <= tol))
        elif npf is not None:
            checks.append(("PBT+Tax+Prov+Extra==NP", abs(base + extra - npf) <= tol))
    if not checks:
        return True, "no chain printed"
    return all(ok for _, ok in checks), ";".join("{}:{}".format(n, "ok" if ok else "FAIL") for n, ok in checks)


def read_quarter(idx, code, qe, fetch):
    r = bse_rev._read_any(idx, code, qe, fetch, want_months=3)
    if "refuse" in r:
        return r
    raw = wbcache.cached(r["ts"], r["url"]) or ""
    t = bse_rev._txt(raw)
    ok, det = arith_ok(t, 10 ** -r["prec"] if r["prec"] else 1.0)
    r["arith_ok"], r["arith"] = ok, det
    r["equity_mn"] = bse_rev._num(t, "Equity Capital")
    return r


def _read_ending(idx, code, qe, fetch):
    """Every capture under (code, qe) that parses with G1, as (r) dicts — cumulative pages included."""
    out = []
    for ts, url, qc in idx.get("%s|%d" % (code, qe), []):
        raw = wbcache.fetch_cached(ts, url) if fetch else wbcache.cached(ts, url)
        r = bse_rev.read_page(raw, code)
        if "refuse" in r or r["to"] != qe:
            continue
        r["ts"], r["url"], r["qc"] = ts, url, qc
        out.append(r)
    return out


def prev_qe(qe):
    y, m = qe // 10000, (qe // 100) % 100 - 3
    if m <= 0:
        y, m = y - 1, m + 12
    return y * 10000 + m * 100 + {3: 31, 6: 30, 9: 30, 12: 31}[m]


def read_quarter_cumdiff(idx, code, qe, fetch):
    """CUMULATIVE DIFFERENCING (WP-P1 pass 2): the quarter's only capture is a year-to-date page (BSE's MC/DC/SC
    codes: Apr..Dec, Apr..Sep, Apr..Mar). Quarter PAT = cumulative page − the page(s) covering exactly the
    cumulative period minus this quarter: a single prior cumulative page with the SAME 'from', or a chain of
    ≤3 legs walking back from the previous quarter-end that abut and start at the cumulative page's 'from'
    (wb_rev.py's rule, ported). Every leg passes G1 (ScripCode) and the arithmetic gate; the sum of leg
    months must equal cumulative months − 3."""
    cums = [r for r in _read_ending(idx, code, qe, fetch) if r["months"] in (6, 9, 12)]
    if not cums:
        return {"refuse": "no cumulative capture ends on this quarter"}
    r = cums[0]
    raw = wbcache.cached(r["ts"], r["url"]) or ""
    ok, det = arith_ok(bse_rev._txt(raw), 10 ** -r["prec"] if r["prec"] else 1.0)
    if not ok:
        return {"refuse": "G5 (cumulative page) " + det}
    chain, cur, bad = [], prev_qe(qe), None
    while True:
        legs = [c for c in _read_ending(idx, code, cur, fetch) if c["from"] >= r["from"] and c["to"] == cur]
        # prefer the leg whose 'from' equals the cumulative start (closes the chain in one step)
        legs.sort(key=lambda c: (c["from"] != r["from"], -c["months"]))
        if not legs:
            bad = "no page ends on %d" % cur
            break
        c = legs[0]
        craw = wbcache.cached(c["ts"], c["url"]) or ""
        cok, cdet = arith_ok(bse_rev._txt(craw), 10 ** -c["prec"] if c["prec"] else 1.0)
        if not cok:
            bad = "leg ending %d fails G5 %s" % (cur, cdet)
            break
        chain.append(c)
        if c["from"] == r["from"]:
            break
        if len(chain) >= 3:
            bad = "chain longer than 3 legs"
            break
        cur = prev_qe(cur)
        if cur < r["from"]:
            bad = "chain walked past the period start"
            break
    if bad:
        return {"refuse": "cumdiff: " + bad}
    months = sum(c["months"] for c in chain)
    if months != r["months"] - 3:
        return {"refuse": "cumdiff: legs cover %dm, expected %dm" % (months, r["months"] - 3)}
    pat = round(r["pat"] - sum(c["pat"] for c in chain), 4)
    tol = max(r["tol"], *(c["tol"] for c in chain))
    out = dict(r)
    out.update(
        {
            "pat": pat,
            "raw_pat": "{} - ({})".format(r["raw_pat"], " + ".join(str(c["raw_pat"]) for c in chain)),
            "mode": "cumdiff",
            "arith": det,
            "arith_ok": True,
            "tol": tol,
            "legs": [
                {
                    "from": c["from"],
                    "to": c["to"],
                    "months": c["months"],
                    "pat": c["pat"],
                    "qc": c["qc"],
                    "url": c["url"],
                }
                for c in chain
            ],
            "equity_mn": bse_rev._num(bse_rev._txt(raw), "Equity Capital"),
            "from": r["from"],
            "to": r["to"],
            "months": 3,
            "role": "%s (%dm cumulative) minus %s"
            % (r["role"], r["months"], " + ".join("%d..%d" % (c["from"], c["to"]) for c in chain)),
        }
    )
    return out


def cross_anchor(keys, code, idx, nse_idx, fetch, max_pages=8):
    """CROSS-SOURCE ANCHOR (WP-P1 pass 3): a symbol with no HELD quarter on the archive can still be anchored
    when NSE's archived results.jsp page and BSE's archived page exist for the SAME quarter: the NSE page
    DECLARES Non-Consolidated + 3 months + Non-Cumulative and prints Net Profit in a declared scale; if that
    equals BSE's 3-month page to the paisa, the BSE page family is proven to be this company's standalone
    series (two exchanges, two documents, one number). NSE pages that wbgate refused for its own landing
    gate (EPS untestable etc.) are still valid as a SECOND READER here — nothing is landed from them.
    Returns (exact, conflict, used)."""
    import wb_read

    exact = conflict = 0
    used = []
    qs = set()
    for k in keys:
        for key in nse_idx:
            if key.startswith(k + "|"):
                q = int(key.split("|")[1])
                if "%s|%d" % (code, q) in idx:
                    qs.add((q, key))
    for q, key in sorted(qs)[:max_pages]:
        ts, url = nse_idx[key][0], nse_idx[key][1]
        raw = wbcache.fetch_cached(ts, url) if fetch else wbcache.cached(ts, url)
        n = wb_read.parse(raw) if raw else None
        if not n or n.get("pat_cr") is None:
            continue
        rt = n.get("result_type") or ""
        if "Consolidated" in rt and "Non-Consolidated" not in rt:
            continue  # a declared consolidated page never anchors
        basis = "NC-declared" if "Non-Consolidated" in rt else "basis-undeclared"
        # the NSE template PRINTS 'Consolidated' when a statement is consolidated (ALFALAVAL Dec-2002 does), so a
        # page that omits the token is the filer's ordinary (standalone) results — recorded per anchor, never silent.
        nf = int(n["from"][7:11]) * 10000 + wb_read.MON[n["from"][3:6]] * 100 + int(n["from"][0:2])
        if n["months"] == 3 and not n["cumulative"]:
            b = read_quarter(idx, code, q, fetch)
            if "refuse" in b or b["from"] != nf:
                continue
        else:
            cands = [c for c in _read_ending(idx, code, q, fetch) if c["months"] == n["months"] and c["from"] == nf]
            if not cands:
                continue
            b = cands[0]
        tol = max(b["tol"], 0.011)
        agree = abs(b["pat"] - n["pat_cr"]) <= tol
        if agree:
            exact += 1
        else:
            conflict += 1
        used.append(
            [
                q,
                round(n["pat_cr"], 4),
                b["pat"],
                "ok" if agree else "CONFLICT",
                "nse %dm %s %s" % (n["months"], basis, url[-50:]),
            ]
        )
    return exact, conflict, used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True, help="json [[SYM, qeInt], ...]")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--calib", action="store_true", help="hold-out only: read HELD cells, report mismatch")
    ap.add_argument("--min-anchors", type=int, default=MIN_ANCHORS)
    ap.add_argument("--limit-syms", type=int, default=0)
    ap.add_argument(
        "--max-anchor-pages",
        type=int,
        default=6,
        help="held quarters read per code for the anchor test (nearest to the archive era first)",
    )
    a = ap.parse_args()

    idx = load_json(bse_rev.INDEX)
    global NSE_IDX
    NSE_IDX = load_json(os.path.join(HERE, "_wb_index.json"))
    fund = load_json(os.path.join(ROOT, "docs", "sf_fundamentals.json"))
    eng = open(os.path.join(ROOT, "docs", "backtest-engine.js"), encoding="utf-8").read()
    fund_alias = json.loads(re.search(r"const FUND_ALIAS = (\{.*?\});\n", eng).group(1))
    rmap = load_json(os.path.join(SCRIPTS, "_rename_map.json"))
    bse_by_id = load_json(os.path.join(SCRIPTS, "bse_scrips.json"))["by_id"]
    master_by_id = {
        r["scrip_id"]: r["SCRIP_CD"]
        for r in load_json(os.path.join(SCRIPTS, "_bse_master_all.json"))
        if r.get("scrip_id")
    }
    try:
        era_ledger = load_json(os.path.join(SCRIPTS, "_shp_aspx_resolved_era_syms.json"))
    except Exception:
        era_ledger = {}
    # provenance of stored cells: aggregator-derived ledgers are NOT truth for the hold-out
    agg_cells = set()
    for p in glob.glob(os.path.join(SCRIPTS, "agg_pat_cell_fills.json")) + glob.glob(
        os.path.join(SCRIPTS, "agg_tools", "*fills*.json")
    ):
        try:
            for k in load_json(p):
                if k.count("|") >= 1:
                    s, q = k.split("|")[:2]
                    agg_cells.add((s, int(q)))
        except Exception:
            pass

    cells = [(s, int(q)) for s, q in load_json(a.cells)]
    syms = sorted({s for s, q in cells})
    if a.limit_syms:
        syms = syms[: a.limit_syms]
    print(
        "cells %d · symbols %d · index keys %d · agg-derived stored cells excluded from truth %d"
        % (len(cells), len(syms), len(idx), len(agg_cells)),
        flush=True,
    )

    def stored_std(keys):
        out = {}
        for k in keys:
            for r in fund.get(k, []):
                if r[1] is not None:
                    out.setdefault(r[0], (r[1], k))
        return out

    props, report = {}, {"calib": [], "anchors": {}, "refused": collections.Counter(), "per_cell": {}}
    hold_n = hold_bad = 0
    t0 = time.time()
    for si, sym in enumerate(syms):
        keys = key_variants(sym, fund_alias, rmap)
        codes = codes_for(sym, keys, bse_by_id, master_by_id, era_ledger)
        targets = [q for s, q in cells if s == sym]
        if not codes:
            for q in targets:
                report["refused"]["no-bse-code"] += 1
                report["per_cell"]["%s|%d" % (sym, q)] = "no-bse-code"
            continue
        held = stored_std(keys)
        # ---- A: anchors over held cells in the archive years, per code
        best_code, best = None, None
        for code, via in codes.items():
            exact = conflict = 0
            used = []
            cand_q = [q for q in sorted(held) if q // 10000 in ARCHIVE_YEARS and "%s|%d" % (code, q) in idx]
            # bounded: Wayback serves ~1 page/s on one keep-alive session; 6 quarters decide the anchor test
            for q in cand_q[: a.max_anchor_pages]:
                v, k = held[q]
                r = read_quarter(idx, code, q, a.fetch)
                if "refuse" in r:
                    continue
                agree = abs(r["pat"] - v) <= r["tol"]
                is_truth = (k, q) not in agg_cells
                if is_truth:
                    hold_n += 1
                    if not agree:
                        hold_bad += 1
                    report["calib"].append(
                        [sym, k, q, v, r["pat"], r["tol"], "AGREE" if agree else "MISMATCH", r["url"]]
                    )
                if agree:
                    exact += 1
                else:
                    conflict += 1
                used.append([q, v, r["pat"], "ok" if agree else "CONFLICT"])
            score = (exact, -conflict)
            if best is None or score > best[0]:
                best_code, best = code, (score, exact, conflict, used, via)
        if best is None:
            for q in targets:
                report["refused"]["no-indexed-anchor-page"] += 1
                report["per_cell"]["%s|%d" % (sym, q)] = "no-indexed-anchor-page"
            continue
        _, exact, conflict, used, via = best
        xmode = ""
        if exact == 0 and conflict == 0 and not a.calib:
            for code, cvia in codes.items():
                xe, xc, xu = cross_anchor(keys, code, idx, NSE_IDX, a.fetch)
                if xe > 0 or xc > 0:
                    best_code, exact, conflict, used, via = (
                        code,
                        xe,
                        xc,
                        xu,
                        cvia + " | cross-anchored on NSE results.jsp (same quarter, both archives)",
                    )
                    xmode = "X"
                    break
        report["anchors"][sym] = {
            "code": best_code,
            "via": via,
            "exact": exact,
            "conflict": conflict,
            "used": used,
            "cross": bool(xmode),
        }
        if a.calib:
            continue
        if conflict > 0 or exact < a.min_anchors:
            why = "anchor-gate: exact %d conflict %d (need >=%d, 0)" % (exact, conflict, a.min_anchors)
            for q in targets:
                report["refused"]["anchor-gate"] += 1
                report["per_cell"]["%s|%d" % (sym, q)] = why
            continue
        # ---- targets
        for q in targets:
            k = "%s|%d" % (sym, q)
            if q in held:
                report["refused"]["already-held"] += 1
                report["per_cell"][k] = "already-held"
                continue
            r = read_quarter(idx, best_code, q, a.fetch)
            if "refuse" in r and (
                r["refuse"].startswith("no BSE capture")
                or r["refuse"].startswith("period")
                or r["refuse"].startswith("G2a")
            ):
                r2 = read_quarter_cumdiff(idx, best_code, q, a.fetch)
                r = r2 if "refuse" not in r2 else {"refuse": r["refuse"] + " | " + r2["refuse"]}
            if "refuse" in r:
                report["refused"][r["refuse"].split(" ")[0][:24]] += 1
                report["per_cell"][k] = r["refuse"]
                continue
            if not r["arith_ok"]:
                report["refused"]["G5-arith"] += 1
                report["per_cell"][k] = "G5 " + r["arith"]
                continue
            props["%s|%d|patS" % (sym, q)] = {
                "value": round(r["pat"], 4),
                "state": "BSE-archive:%s%d/G1/G2/G4/G5%s"
                % (xmode or "A", exact, "/CUMDIFF" if r.get("mode") == "cumdiff" else ""),
                "src": "bseindia.com/qresann/result.asp (Wayback {}) scripcd={} quarter={} — {}".format(
                    r["ts"], best_code, r["qc"], r["url"]
                ),
                "resolved_via": via,
                "evidence": (
                    "BSE archived results page: ScripCode %s == repo code (%s); period %d..%d = 3 months; "
                    "scale %s (÷%g); Net Profit raw %s; page arithmetic %s. ANCHORS: this code's pages reproduce "
                    "%d %s exactly with 0 conflicts (%s)."
                    % (
                        best_code,
                        via,
                        r["from"],
                        r["to"],
                        r["scale"],
                        r["div"],
                        r["raw_pat"],
                        r["arith"],
                        exact,
                        (
                            "of the symbol's held standalone quarters"
                            if not xmode
                            else "quarters where NSE's archived results.jsp (declared Non-Consolidated, 3 months) prints the SAME Net Profit"
                        ),
                        ", ".join("%d=%s" % (u[0], u[1]) for u in used[:6]),
                    )
                ),
                "page": {
                    "name": r["name"],
                    "equity_mn": r["equity_mn"],
                    "role": r["role"],
                    "prec": r["prec"],
                    "legs": r.get("legs"),
                },
            }
            report["per_cell"][k] = "PROPOSE {:.4f}".format(r["pat"])
        if si % 20 == 0:
            print(
                "  %d/%d symbols · %d props · hold-out %d/%d mismatch · %.0fs"
                % (si, len(syms), len(props), hold_bad, hold_n, time.time() - t0),
                flush=True,
            )

    report["hold_out"] = {
        "n": hold_n,
        "mismatch": hold_bad,
        "rate_pct": round(100.0 * hold_bad / hold_n, 2) if hold_n else None,
    }
    json.dump({"proposals": props, "report": report}, open(a.out, "w"), indent=0)
    print(
        "\nHOLD-OUT: %d truth cells read blind, %d mismatch (%s%%)" % (hold_n, hold_bad, report["hold_out"]["rate_pct"])
    )
    print(
        "anchored symbols: %d (>=%d exact & 0 conflict: %d)"
        % (
            len(report["anchors"]),
            a.min_anchors,
            sum(1 for v in report["anchors"].values() if v["exact"] >= a.min_anchors and v["conflict"] == 0),
        )
    )
    print("proposals: %d · refused: %s" % (len(props), dict(report["refused"])))
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()

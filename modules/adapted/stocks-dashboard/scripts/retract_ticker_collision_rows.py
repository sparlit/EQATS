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
"""Take ANOTHER company's rows off a ticker the site uses for a different company (runbook §203).

WHY. One ticker string can name two companies: the NSE symbol of one and the BSE scrip_id of another. ZEAL is Zeal
Global Services on NSE (SME, INE0PPS01018) and Zeal Aqua on BSE (539963, INE819S01025). Which company the SITE's page
is comes from docs/stock_data.bin meta (bse_resolve.page_company): "ZEAL.NS" -> the NSE company. Writers that keyed a
filing by the bare ticker put the other company's numbers on that page:
  * the 2026-06-15 BSE text-layer campaign stored Zeal Aqua's 29 quarters under ZEAL in both fundamentals stores;
  * BSE result detail (P&L, cash flow, balance sheet) is filed under the BSE ticker (fetch_bse_results_xbrl, the only
    writer that keys a BSE file by ticker) — its clash guard knew the committed tape's keys, which hold no SME symbol —
    so xbrl_extra[ZEAL] / [GSTL] were mostly Zeal Aqua's / Globalspace's (their P&L blocks' pbt - tax = the twin's
    own px profit);
  * the vision route filed Focus Lighting's (NSE FOCUS) quarters under BSE 543312, Focus Business Solution;
  * and the reverse: KEL's page is Kotia Enterprises (BSE 539599, "KEL.BO" only) since NSE's KEL, Kundan Edifice,
    stopped trading — its NSE filings were still keyed KEL (so were DRL, INNOVATIVE, BRIGHT).

WHAT IT DOES. Every action needs a proof measured from the filings or the stores; nothing is moved on a name.
  A. NSE page K whose BSE twin is recorded in bse_scrip_isin_conflicts.json (scrip C):
     1. px[C] cells in PX_RETRACT (the NSE company's figures filed under the twin's code) are dropped, each only
        after re-checking that its revenue AND profit equal K's served row on the same basis;
     2. KEY-LEVEL PROOF: >= 2 served profit rows under K equal the twin's own px[C] profit at the same quarter.
        Unproven keys are left alone and named.
     3. fund rows: a row equal to the twin's px profit, or one the page company cannot have filed (it files only
        half-years, or the quarter predates its first filing), is the twin's. At a half-year end the page company
        DID file, the row is REWRITTEN from its own filings (std = ProfitLossForThePeriod of the standalone file;
        con = owners' profit of the consolidated file; each half proven by H1 + H2 = the Yearly filing's FY total;
        announce slot = that file's filing day) and journalled in fund_cell_fix.json (re-asserted nightly and
        watched by verify_fills_live). Every other twin row is dropped.
     4. revop rows: the profit mirror (slots 4/5) of a rewritten quarter takes the page company's figures where it
        holds the twin's (revop_cell_fix.json); a row whose revenue equals the twin's px revenue is dropped.
     5. xbrl_extra (an SME page company only — its detail can only come from its own SME filings): every field that
        is not what its own filing yields through build_xbrl_extra.parse_file is dropped.
  B. BSE page K (the site lists only K.BO) with an NSE twin of another issuer whose filings were keyed K: fund /
     revop rows equal to the twin's filing (same quarter, same basis) and xbrl_extra fields equal to its parse are
     dropped. Anything else under K is the BSE company's and stays.
  C. Ledgers that journal the twin's values as K's cells are retired (pat_defects -> _RETRACTED_<qe>, owners heal
     re-pointed, nosub_con_lag verdicts marked retired, no_con_filing entry withdrawn) — else a nightly re-apply or
     verify_fills_live (BLOCKING) would write the other company back or read MISSING.
Every removed or rewritten value is logged in scripts/ticker_collision_retractions.json (reversible).

Needs the NSE SME XBRL cache (SME_CACHE, default scripts/_xbrl_cache_sme — the local cache fetch_sme_xbrl keeps).
Run:  python3 scripts/retract_ticker_collision_rows.py [--apply]      (default: dry run, prints the plan)
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
import bse_resolve as R  # noqa: E402

SME_CACHE = os.environ.get("SME_CACHE") or os.path.join(HERE, "_xbrl_cache_sme")
LOG = os.path.join(HERE, "ticker_collision_retractions.json")
FUND_STORES = [os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(HERE, "fundamentals.json")]
REVOP_STORES = [os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(HERE, "revop_fundamentals.json")]
XTRA = os.path.join(HERE, "xbrl_extra.json.gz")
BSEF = os.path.join(ROOT, "docs", "bse_fundamentals.json")
TOL = 0.011  # 2-dp store vs a crore-converted filing value

# The NSE company's figures filed under the twin's scrip by the vision route (src "vision"; bse_vision_prep mapped
# tickers to scrips without the ISIN guard until §187). 543312 files HALF-YEARLY (its own bse-xbrl cells are h=1
# pairs, revenue 6-10 cr a half), so a June cell cannot be its own, and each cell equals FOCUS's served row on revenue
# and profit to the paisa.
PX_RETRACT = {"543312": {"page": "FOCUS", "quarters": ["20250630", "20260331", "20260630"]}}

# A BSE page's OWN cells that the heal exposes (the twin's row used to hide them) and that the vision route stored 100x
# too large — lakh read as crore, the §184 class. Replaced by what the scrip's own results XBRL prints (the values the
# bse-xbrl route's parse_values yields), guarded on the stored value; the old cell is kept in "was".
PX_FIX = {
    "539599": {
        "page": "KEL",
        "cells": {
            "20250630": {
                "was": (0.0, -5.45),
                "now": (0.0, -0.05),
                "ann": 20250814,
                "f": "Integrated_Finance_Ind_As_539599_148202513189.xml (filed 2025-08-14 13:18): RevenueFromOperations 0, "
                "ProfitLossForPeriod -545000 INR",
            },
            "20260331": {
                "was": (131.0, -222.17),
                "now": (1.31, -2.22),
                "ann": 20260529,
                "f": "Integrated_Finance_Ind_As_539599_2952026172245.xml (filed 2026-05-29 17:22): RevenueFromOperations "
                "13100000, ProfitLossForPeriod -22217000 INR; the revisions _01062026010050 and _306202616156 print the "
                "same; FY2026 ProfitLossForPeriod (FourD) -24992000 = Jun -0.05 + Sep -0.11 + Dec -0.11 + Mar -2.22 cr",
            },
            "20260630": {
                "was": (0.0, 5.25),
                "now": (0.0, 0.05),
                "ann": 20260814,
                "f": "Integrated_Finance_Ind_As_539599_1482026173622.xml (filed 2026-08-14 17:36): RevenueFromOperations 0, "
                "ProfitLossForPeriod 525000 INR; _14082026054518 prints the same",
            },
        },
    }
}

RE_ISIN = re.compile(r"<in-(?:capmkt|bse-fin):ISIN[^>]*>\s*([A-Z0-9]{12})\s*<")


def _text(p):
    raw = open(p, "rb").read()
    return (gzip.decompress(raw) if p.endswith(".gz") else raw).decode("utf-8")


def _load(p):
    return json.loads(_text(p))


_FMT = {}


def _fmt(p):
    """The exact json.dumps arguments that reproduce file p byte for byte — so a rewrite changes only the entries this
    script touched (payloads are compact, journals indent=1, some ASCII-escaped, some not). None: no round-trip."""
    if p not in _FMT:
        raw = _text(p)
        d = json.loads(raw)
        _FMT[p] = None
        for ind in (None, 1, 2):
            for sep in ((",", ":"), (",", ": "), (", ", ": ")):
                for ea in (True, False):
                    t = json.dumps(d, indent=ind, separators=sep, ensure_ascii=ea)
                    for nl in ("", "\n"):
                        if t + nl == raw and _FMT[p] is None:
                            _FMT[p] = (ind, sep, ea, nl)
    return _FMT[p]


def _dumps_like(p, d):
    f = _fmt(p)
    if f is None:
        sys.exit(f"ABORT: {p} does not round-trip through json — refusing to rewrite it")
    ind, sep, ea, nl = f
    return json.dumps(d, indent=ind, separators=sep, ensure_ascii=ea) + nl


def _save(p, d):
    blob = _dumps_like(p, d).encode("utf-8")
    open(p, "wb").write(gzip.compress(blob, 9) if p.endswith(".gz") else blob)


def same(a, b, tol=TOL):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def tag(xml, name, ctx):
    """Value of <prefix:name contextRef="ctx"> in crore, or None."""
    m = re.search(rf'<[\w-]+:{name} contextRef="{ctx}"[^>]*>\s*(-?[\d.]+)\s*<', xml)
    return round(float(m.group(1)) / 1e7, 4) if m else None


def filed_day(fname):
    """The filing day in an NSE XBRL file name (..._DDMMYYYYhhmmss_...) as YYYYMMDD."""
    m = re.search(r"_(\d{2})(\d{2})(20\d{2})\d{6}", fname)
    return int(m.group(3) + m.group(2) + m.group(1)) if m else None


def own_half(path, fname):
    """One SME half-year / Yearly filing -> {qe, b, rev, pat, rev_fy, pat_fy, start, filed, f} (crore, OneD = the
    half, FourD = the year). Standalone profit = ProfitLossForThePeriod (Ind AS: ProfitLossForPeriod); consolidated =
    owners' share: ProfitOrLossAttributableToOwnersOfParent, else the non-Ind-AS bottom line after minority interest
    and associates (ProfitLossForThePeriod)."""
    import build_row_periods as BRP

    x = BRP.parse(path)
    if not x:
        return None
    xml = open(path, encoding="utf-8", errors="replace").read()
    cons = x["b"] == "c"

    def pat(ctx):
        for t in (("ProfitOrLossAttributableToOwnersOfParent",) if cons else ()) + (
            "ProfitLossForThePeriod",
            "ProfitLossForPeriod",
        ):
            v = tag(xml, t, ctx)
            if v is not None:
                return v
        return None

    return {
        "qe": x["qe"],
        "b": x["b"],
        "rev": tag(xml, "RevenueFromOperations", "OneD"),
        "pat": pat("OneD"),
        "rev_fy": tag(xml, "RevenueFromOperations", "FourD"),
        "pat_fy": pat("FourD"),
        "start": x["start"],
        "rq": x["rq"],
        "filed": filed_day(fname),
        "f": fname,
        "isin": x["isin"],
        "sym": x["sym"],
        "pone": x["pone"],
        "one": x["one"],
    }


def sme_files_by_issuer(issuers):
    """{issuer: [(path, fname)]} of the SME cache files whose ISIN issuer is wanted (whole-file read: the ISIN can sit
    past the first 40 KB)."""
    out = collections.defaultdict(list)
    for f in sorted(os.listdir(SME_CACHE)):
        if f.startswith(("list_", ".")) or f.endswith(".json"):
            continue
        p = os.path.join(SME_CACHE, f)
        m = RE_ISIN.search(open(p, encoding="utf-8", errors="replace").read())
        if m and R.issuer(m.group(1)) in issuers:
            out[R.issuer(m.group(1))].append((p, f))
    return out


def parse_fields(files, key):
    """{qe: {basis: {field: set(json values)}}} — what build_xbrl_extra.parse_file yields for these filings (the
    parser that wrote the stored fields; sym_override bypasses its own §203 refusal so a twin's filing can be read)."""
    import build_xbrl_extra as BX

    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for p, f in sorted(files, key=lambda t: BX.ts_key(t[1])):
        r = BX.parse_file(p, f, sym_override=key)
        if not r:
            continue
        for b in ("s", "c"):
            for k, v in (r.get(b) or {}).items():
                out[str(r["qe"])][b].setdefault(k, set()).add(json.dumps(v))
    return out


def main():
    apply = "--apply" in sys.argv
    if not os.path.isdir(SME_CACHE):
        sys.exit(f"ABORT: SME XBRL cache {SME_CACHE} missing (set SME_CACHE) — the proofs read the filings")
    R.identities()
    conflicts = R.conflicts()
    fund = {p: _load(p) for p in FUND_STORES}
    revop = {p: _load(p) for p in REVOP_STORES}
    served_fd, served_rv = fund[FUND_STORES[0]], revop[REVOP_STORES[0]]
    xtra = _load(XTRA)
    bfd = _load(BSEF)
    px = bfd.get("px") or {}
    site = R.identities()["site"]
    log = _load(LOG) if os.path.exists(LOG) else {"_README": __doc__.split("\n\n")[0].strip(), "runs": []}
    run = {"at": time.strftime("%Y-%m-%d %H:%M"), "keys": {}}
    changed = set()
    cell_fix = {"fund": [], "revop": []}  # new reviewed-correction ledger entries

    # ---- A1. the NSE company's figures filed under the twin's scrip ------------------------------------------------
    for code, spec in sorted(PX_RETRACT.items()):
        k = spec["page"]
        fr = {str(r[0]): r for r in served_fd.get(k) or []}
        out = []
        for q in spec["quarters"]:
            c = (px.get(code) or {}).get(q)
            if not c:
                continue
            i = 3 if c.get("basis") == "C" else 1
            rv = (served_rv.get(k) or {}).get(q) or []
            ok = (
                q in fr
                and same(fr[q][i], c.get("pat"), 0.005)
                and len(rv) > 1
                and same(rv[1 if i == 3 else 0], c.get("rev"), 0.005)
                and str(c.get("src", "")).startswith("vision")
            )
            if not ok:
                print(f"px[{code}] {q} NOT dropped — no longer equals {k}'s served row: {c}")
                continue
            out.append({"q": q, "cell": c, "action": f"dropped ({k}'s own figures filed under BSE {code})"})
            del px[code][q]
        if out:
            run["keys"].setdefault(k, {"page": "nse", "stores": {}})["stores"][
                f"docs/bse_fundamentals.json px[{code}]"
            ] = out
            changed.add(BSEF)
            print(
                "px[%s] (%s): %d cell(s) of %s's own figures dropped"
                % (code, conflicts.get(k, {}).get("bse_name"), len(out), k)
            )

    # ---- A. NSE pages with a recorded BSE twin ---------------------------------------------------------------------
    wanted = {R.issuer(e.get("nse_isin")) for e in conflicts.values() if e.get("nse_isin")}
    group_b = {}  # K -> twin issuers (found below)
    all_nse = {s: {R.issuer(i) for i in iss} for s, iss in R.identities()["nse"].items()}
    for s, iss in all_nse.items():
        own, piss = R.page_company(s)
        if own == "bse" and piss and (iss - piss):
            group_b[s] = iss - piss
    files = sme_files_by_issuer(wanted | {i for v in group_b.values() for i in v})

    for k, e in sorted(conflicts.items()):
        code = str(e.get("bse_code"))
        tw = px.get(code) or {}
        rows = served_fd.get(k) or []
        hits = [
            r[0]
            for r in rows
            if str(r[0]) in tw
            and tw[str(r[0])].get("pat") not in (None, 0)
            and any(same(v, tw[str(r[0])]["pat"], 0.005) for v in (r[1], r[3]))
        ]
        if len(hits) < 2:
            continue  # no key-level proof (FOCUS, GSTL, MAL, ...)
        own_files = [own_half(p, f) for p, f in files.get(R.issuer(e["nse_isin"]), [])]
        own_files = [x for x in own_files if x and x["qe"]]
        halves_only = all(x["rq"] in ("Half yearly", "Half Yearly", "Yearly") for x in own_files)
        first = min((int(x["start"].replace("-", "")) for x in own_files if x.get("start")), default=None)
        # the page company's own figure per (qe, basis): earliest filing, proven by H1 + H2 = FY
        byq = collections.defaultdict(list)
        for x in own_files:
            byq[(x["qe"], x["b"])].append(x)
        mine = {}
        for (qe, b), xs in byq.items():
            x = min(xs, key=lambda t: t["filed"] or 99999999)
            if any(not same(y["pat"], x["pat"], 0.005) or not same(y["rev"], x["rev"], 0.005) for y in xs):
                print(
                    "  {} {} {}: its filings disagree ({}) — not rewritten".format(
                        k, qe, b, [(y["f"], y["pat"]) for y in xs]
                    )
                )
                continue
            yr = qe // 10000 + (1 if qe % 10000 == 930 else 0)
            sep, mar = byq.get(((yr - 1) * 10000 + 930, b)), byq.get((yr * 10000 + 331, b))
            if not (
                sep
                and mar
                and mar[0]["pat_fy"] is not None
                and same(sep[0]["pat"] + mar[0]["pat"], mar[0]["pat_fy"])
                and same(sep[0]["rev"] + mar[0]["rev"], mar[0]["rev_fy"])
            ):
                print(f"  {k} {qe} {b}: H1 + H2 = FY does not close — not rewritten")
                continue
            mine[(qe, b)] = {
                "pat": round(x["pat"], 2),
                "rev": round(x["rev"], 2),
                "ann": x["filed"],
                "f": x["f"],
                "proof": "H1 {} + H2 {} = FY {} ({})".format(
                    round(sep[0]["pat"], 4), round(mar[0]["pat"], 4), mar[0]["pat_fy"], mar[0]["f"]
                ),
            }
        rec = run["keys"].setdefault(k, {"page": "nse", "stores": {}})
        rec.update(
            twin="BSE {} {} ({})".format(code, e.get("bse_name"), e.get("bse_isin")),
            proof_rows=len(hits),
            page_company_first_period=first,
            page_company_files_half_yearly=halves_only,
        )
        print(
            "%-10s page = NSE %s; %d served profit rows equal BSE %s %s's own px profit — the twin's rows"
            % (k, e.get("nse_isin"), len(hits), code, e.get("bse_name"))
        )
        # ---- A3. fund rows ------------------------------------------------------------------------------------------
        for p, d in fund.items():
            out, keep = [], []
            for r in d.get(k) or []:
                qe = r[0]
                c = tw.get(str(qe)) or {}
                twin = c.get("pat") not in (None, 0) and any(same(v, c.get("pat"), 0.005) for v in (r[1], r[3]))
                why = (
                    "equals BSE {}'s own profit {}".format(code, c.get("pat"))
                    if twin
                    else "a quarter the page company never files (it files half-years only)"
                    if halves_only and qe % 10000 in (630, 1231)
                    else f"predates the page company's first filed period ({first})"
                    if first and qe < first
                    else None
                )
                ms, mc = mine.get((qe, "s")), mine.get((qe, "c"))
                if why and (ms or mc):
                    new = [
                        qe,
                        ms["pat"] if ms else None,
                        ms["ann"] if ms else None,
                        mc["pat"] if mc else None,
                        mc["ann"] if mc else None,
                    ]
                    keep.append(new)
                    out.append(
                        {
                            "row": r,
                            "now": new,
                            "action": f"rewritten from the page company's own filings ({why})",
                            "files": [m["f"] for m in (ms, mc) if m],
                            "proof": [m["proof"] for m in (ms, mc) if m],
                        }
                    )
                    if p == FUND_STORES[0]:
                        for b, m, i in (("std", ms, 1), ("con", mc, 3)):
                            if m and not same(r[i], m["pat"], 0.005):
                                cell_fix["fund"].append(
                                    {
                                        "sym": k,
                                        "qe": str(qe),
                                        "basis": b,
                                        "was": r[i],
                                        "fixed": m["pat"],
                                        "why": "§203: {} on this site is {} (NSE, {}); the stored {} was {}'s (BSE {}) "
                                        "profit for the quarter. Page company's own filing {}: {} profit {} cr. "
                                        "SECOND document: {}.".format(
                                            k,
                                            site.get(k + ".NS", {}).get("name"),
                                            e.get("nse_isin"),
                                            r[i],
                                            e.get("bse_name"),
                                            code,
                                            m["f"],
                                            b,
                                            m["pat"],
                                            m["proof"],
                                        ),
                                        "found": "ticker-collision heal 2026-09-27 (runbook §203)",
                                    }
                                )
                elif why:
                    out.append({"row": r, "action": f"dropped ({why})"})
                else:
                    keep.append(r)
            if out:
                if keep:
                    d[k] = sorted(keep, key=lambda x: x[0])
                else:
                    d.pop(k, None)
                rec["stores"][os.path.relpath(p, ROOT)] = out
                changed.add(p)
        # ---- A4. revop rows ------------------------------------------------------------------------------------------
        rewrote = {e_["row"][0]: e_["now"] for e_ in rec["stores"].get("docs/sf_fundamentals.json", []) if "now" in e_}
        for p, d in revop.items():
            out = []
            for q, r in sorted((d.get(k) or {}).items()):
                c = tw.get(q) or {}
                if c.get("rev") not in (None, 0) and any(same(r[i], c["rev"], 0.005) for i in (0, 1) if i < len(r)):
                    out.append(
                        {"q": q, "row": r, "action": "dropped (revenue equals BSE {}'s own {})".format(code, c["rev"])}
                    )
                    del d[k][q]
                    continue
                now = rewrote.get(int(q))
                if now:
                    r2 = list(r) + [None] * (9 - len(r))
                    for slot, v, b in ((4, now[1], "pat_std"), (5, now[3], "pat_con")):
                        if (
                            v is not None
                            and r2[slot] is not None
                            and same(r2[slot], c.get("pat"), 0.005)
                            and not same(r2[slot], v, 0.005)
                        ):
                            out.append(
                                {
                                    "q": q,
                                    "slot": slot,
                                    "was": r2[slot],
                                    "now": v,
                                    "action": f"profit mirror: BSE {code}'s {r2[slot]} -> the page company's {v}",
                                }
                            )
                            if p == REVOP_STORES[0]:
                                cell_fix["revop"].append(
                                    {
                                        "sym": k,
                                        "qe": q,
                                        "basis": b,
                                        "was": r2[slot],
                                        "fixed": v,
                                        "why": "§203: the profit mirror of {} {} held {}'s (BSE {}) quarter profit {}; "
                                        "{}'s own filing prints {} (see fund_cell_fix §203 entries for the documents).".format(
                                            k,
                                            q,
                                            e.get("bse_name"),
                                            code,
                                            r2[slot],
                                            site.get(k + ".NS", {}).get("name"),
                                            v,
                                        ),
                                        "found": "ticker-collision heal 2026-09-27 (runbook §203)",
                                    }
                                )
                            r2[slot] = v
                    if r2[: len(r)] != list(r):
                        d[k][q] = r2[: len(r)]
            if out:
                rec["stores"][os.path.relpath(p, ROOT)] = out
                changed.add(p)
        # ---- A5. xbrl_extra (SME page company only) --------------------------------------------------------------------
        if site.get(k + ".NS", {}).get("sme") and xtra.get(k):
            ownp = parse_fields(files.get(R.issuer(e["nse_isin"]), []), k)
            out = []
            for q, cell in sorted(xtra[k].items()):
                for b in list(cell):
                    blk = cell[b]
                    if not isinstance(blk, dict):
                        continue
                    pv = ownp.get(q, {}).get(b, {})
                    gone = {f: v for f, v in blk.items() if not (f in pv and json.dumps(v) in pv[f])}
                    if gone:
                        for f in gone:
                            del blk[f]
                        out.append(
                            {
                                "q": q,
                                "b": b,
                                "dropped": gone,
                                "kept": sorted(blk),
                                "action": "fields the page company's own filing does not yield — the twin's detail",
                            }
                        )
                    if not blk:
                        del cell[b]
                if not cell:
                    del xtra[k][q]
            if not xtra[k]:
                del xtra[k]
            if out:
                rec["stores"]["scripts/xbrl_extra.json.gz"] = out
                changed.add(XTRA)
        n = {s: len(v) for s, v in rec["stores"].items()}
        print(f"           {n}")

    # GSTL-type: no fund contamination, but the twin's detail under an SME page (its P&L blocks' pbt - tax = the twin's
    # px profit at the same quarter, >= 2 blocks)
    for k, e in sorted(conflicts.items()):
        if k in run["keys"] and run["keys"][k].get("proof_rows"):
            continue
        code = str(e.get("bse_code"))
        tw = px.get(code) or {}
        if not (site.get(k + ".NS", {}).get("sme") and xtra.get(k)):
            continue
        blocks = [
            (q, b)
            for q, cell in xtra[k].items()
            for b, blk in cell.items()
            if isinstance(blk, dict)
            and blk.get("pbt") is not None
            and blk.get("tax") is not None
            and (tw.get(q) or {}).get("pat") not in (None, 0)
            and same(blk["pbt"] - blk["tax"], tw[q]["pat"], 0.011)
        ]
        if len(blocks) < 2:
            continue
        ownp = parse_fields(files.get(R.issuer(e["nse_isin"]), []), k)
        out = []
        for q, cell in sorted(xtra[k].items()):
            for b in list(cell):
                blk = cell[b]
                pv = ownp.get(q, {}).get(b, {})
                gone = {f: v for f, v in blk.items() if not (f in pv and json.dumps(v) in pv[f])}
                if gone:
                    for f in gone:
                        del blk[f]
                    out.append(
                        {
                            "q": q,
                            "b": b,
                            "dropped": gone,
                            "kept": sorted(blk),
                            "action": "fields the page company's own filing does not yield — the twin's detail",
                        }
                    )
                if not blk:
                    del cell[b]
            if not cell:
                del xtra[k][q]
        if not xtra[k]:
            del xtra[k]
        if out:
            run["keys"].setdefault(k, {"page": "nse", "stores": {}})
            run["keys"][k].update(
                twin="BSE {} {} ({})".format(code, e.get("bse_name"), e.get("bse_isin")), proof_blocks=len(blocks)
            )
            run["keys"][k]["stores"]["scripts/xbrl_extra.json.gz"] = out
            changed.add(XTRA)
            print(
                "%-10s page = NSE %s; %d detail blocks' pbt - tax = BSE %s's own profit — %d block(s) cleaned"
                % (k, e.get("nse_isin"), len(blocks), code, len(out))
            )

    # ---- B. BSE pages whose NSE twin's filings were keyed under them -----------------------------------------------
    for k, iss in sorted(group_b.items()):
        tfiles = [pf for i in iss for pf in files.get(i, [])]
        if not tfiles:
            continue
        tw = [own_half(p, f) for p, f in tfiles]
        tw = [x for x in tw if x and x["qe"]]
        rev = collections.defaultdict(set)
        pat = collections.defaultdict(set)
        for x in tw:
            if x["one"] is not None:
                rev[(x["qe"], x["b"])].add(x["one"])
            for v in x["pone"]:
                pat[(x["qe"], x["b"])].add(v)
        rec = {"page": "bse", "twin": "NSE {} ({})".format(k, "/".join(sorted(iss))), "stores": {}}
        for p, d in fund.items():
            out, keep = [], []
            for r in d.get(k) or []:
                hit = [
                    b
                    for b, i in (("s", 1), ("c", 3))
                    if r[i] is not None and any(same(r[i], v) for v in pat.get((r[0], b), ()))
                ]
                if hit and all(r[i] is None or b in hit for b, i in (("s", 1), ("c", 3))):
                    out.append(
                        {"row": r, "action": "dropped (equals the NSE twin's own {} filing)".format("/".join(hit))}
                    )
                else:
                    keep.append(r)
            if out:
                if keep:
                    d[k] = keep
                else:
                    d.pop(k, None)
                rec["stores"][os.path.relpath(p, ROOT)] = out
                changed.add(p)
        for p, d in revop.items():
            out = []
            for q, r in sorted((d.get(k) or {}).items()):
                hit = [
                    b
                    for b, i in (("s", 0), ("c", 1))
                    if i < len(r) and r[i] is not None and any(same(r[i], v) for v in rev.get((int(q), b), ()))
                ]
                if hit and all(r[i] is None or b in hit for b, i in (("s", 0), ("c", 1)) if i < len(r)):
                    out.append(
                        {
                            "q": q,
                            "row": r,
                            "action": "dropped (revenue equals the NSE twin's own {} filing)".format("/".join(hit)),
                        }
                    )
                    del d[k][q]
            if out:
                if not d[k]:
                    d.pop(k)
                rec["stores"][os.path.relpath(p, ROOT)] = out
                changed.add(p)
        if xtra.get(k):
            tp = parse_fields(tfiles, k)
            out = []
            for q, cell in sorted(xtra[k].items()):
                for b in list(cell):
                    blk = cell[b]
                    pv = tp.get(q, {}).get(b, {})
                    gone = {f: v for f, v in blk.items() if f in pv and json.dumps(v) in pv[f]}
                    if gone:
                        for f in gone:
                            del blk[f]
                        out.append(
                            {
                                "q": q,
                                "b": b,
                                "dropped": gone,
                                "kept": sorted(blk),
                                "action": "fields equal to the NSE twin's own filing",
                            }
                        )
                    if not blk:
                        del cell[b]
                if not cell:
                    del xtra[k][q]
            if not xtra[k]:
                del xtra[k]
            if out:
                rec["stores"]["scripts/xbrl_extra.json.gz"] = out
                changed.add(XTRA)
        if rec["stores"]:
            run["keys"][k] = rec
            print(
                "%-10s page = BSE %s; NSE twin's rows removed: %s"
                % (k, site.get(k + ".BO", {}).get("name"), {s: len(v) for s, v in rec["stores"].items()})
            )

    # ---- B2. the BSE page's own cells the heal exposes, mis-scaled by the vision route ---------------------------------
    for code, spec in sorted(PX_FIX.items()):
        out = []
        for q, fx in sorted(spec["cells"].items()):
            c = (px.get(code) or {}).get(q)
            if (
                not c
                or c.get("basis") != "S"
                or not (same(c.get("rev"), fx["was"][0], 0.005) and same(c.get("pat"), fx["was"][1], 0.005))
            ):
                continue  # applied already, or moved on: never forced
            was = {k: c[k] for k in ("rev", "pat", "ann", "src") if k in c}
            c.update(rev=fx["now"][0], pat=fx["now"][1], ann=fx["ann"], src="bse-xbrl", was=was)
            out.append(
                {
                    "q": q,
                    "was": was,
                    "now": {"rev": fx["now"][0], "pat": fx["now"][1], "ann": fx["ann"]},
                    "action": "the scrip's own cell, stored 100x (lakh as crore) — replaced from its own filing",
                    "filing": fx["f"],
                }
            )
        if out:
            run["keys"].setdefault(spec["page"], {"page": "bse", "stores": {}})["stores"][
                f"docs/bse_fundamentals.json px[{code}]"
            ] = out
            changed.add(BSEF)
            print(
                "px[%s] (%s's own cells): %d mis-scaled cell(s) replaced from its XBRL" % (code, spec["page"], len(out))
            )

    # ---- C. ledgers --------------------------------------------------------------------------------------------------
    led_changed = retire_ledgers(run, conflicts, cell_fix, apply)

    if not changed and not led_changed:
        print("nothing to retract (already applied)")
        return 0
    if not apply:
        print(
            "DRY RUN — re-run with --apply to write %d store(s) + %d ledger(s) + %s"
            % (len(changed), len(led_changed), os.path.relpath(LOG, ROOT))
        )
        return 0
    for p in changed:
        _save(p, xtra if p == XTRA else bfd if p == BSEF else fund[p] if p in fund else revop[p])
    for p, (text) in led_changed.items():
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    log["runs"].append(run)
    with open(LOG, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(
        "wrote {} + {}".format(
            ", ".join(os.path.relpath(p, ROOT) for p in sorted(changed) + sorted(led_changed)),
            os.path.relpath(LOG, ROOT),
        )
    )
    return 0


def retire_ledgers(run, conflicts, cell_fix, apply):
    """Ledgers that journal the twin's value as the page's cell. -> {path: new file text}."""
    out = {}

    def note(k):
        return (
            "§203 (2026-09-27): {} on this site is {} (NSE {}); this entry journalled BSE {} {}'s figure "
            "under the shared ticker".format(
                k,
                R.identities()["site"].get(k + ".NS", {}).get("name"),
                conflicts[k].get("nse_isin"),
                conflicts[k].get("bse_code"),
                conflicts[k].get("bse_name"),
            )
        )

    keys = {k for k, v in run["keys"].items() if v.get("proof_rows")}

    def dump(p, d, indent=None):
        text = _dumps_like(p, d)
        if text != _text(p):
            out[p] = text

    # pat_defects: withdraw by the house convention (key -> _RETRACTED_<qe>, verify_fills_live skips it)
    p = os.path.join(HERE, "pat_defects.json")
    d = json.load(open(p, encoding="utf-8"))
    log_ = []
    for k in sorted(keys):
        for q in [q for q in (d.get(k) or {}) if q.isdigit()]:
            e = d[k].pop(q)
            e["retracted_why"] = note(k) + " — the stored and 'correct' values here are both that company's."
            d[k]["_RETRACTED_" + q] = e
            log_.append(f"{k}/{q}")
    if log_:
        dump(p, d)
        run.setdefault("ledgers", {})["pat_defects.json"] = log_
    # owners_basis_heals: apply_owners_full pins `owners` nightly — re-point it to the page company's own owners' profit
    p = os.path.join(HERE, "owners_basis_heals.json")
    d = json.load(open(p, encoding="utf-8"))
    log_ = []
    fixes = {(f["sym"], f["qe"], f["basis"]): f for f in cell_fix["fund"]}
    for ck, e in sorted((d.get("cells") or {}).items()):
        k, q, slot = ([*ck.split("|"), "", ""])[:3]
        if k in keys and slot == "patC" and (k, q, "con") in fixes and e.get("owners") != fixes[(k, q, "con")]["fixed"]:
            e["superseded_2026_09_27"] = {x: e[x] for x in ("owners", "note", "also_npStd", "stored_before") if x in e}
            e["owners"] = fixes[(k, q, "con")]["fixed"]
            e.pop("also_npStd", None)
            e["note"] = (
                note(k)
                + ". The page company's own consolidated filing: "
                + fixes[(k, q, "con")]["why"].split("Page company's own filing ", 1)[-1]
            )
            log_.append("{} owners -> {}".format(ck, e["owners"]))
    if log_:
        dump(p, d)
        run.setdefault("ledgers", {})["owners_basis_heals.json"] = log_
    # nosub_con_lag_verdicts: a one-off applier re-run would write the twin's figure back — mark the entries retired
    p = os.path.join(HERE, "nosub_con_lag_verdicts.json")
    d = json.load(open(p, encoding="utf-8"))
    log_ = []
    for sec in ("cells", "companions", "mirror"):
        for ck, e in (d.get(sec) or {}).items():
            if ck.split("|")[0] in keys and isinstance(e, dict) and not e.get("retired"):
                e["retired"] = note(ck.split("|")[0])
                log_.append(f"{sec}/{ck}")
    if log_:
        dump(p, d)
        run.setdefault("ledgers", {})["nosub_con_lag_verdicts.json"] = log_
    # no_con_filing: "never files consolidated" was the twin's cadence, and the page company files both bases
    p = os.path.join(HERE, "no_con_filing.json")
    d = json.load(open(p, encoding="utf-8"))
    log_ = []
    for k in sorted(keys):
        if k in d.get("never_filed_con", []) and any(f["sym"] == k and f["basis"] == "con" for f in cell_fix["fund"]):
            d["never_filed_con"].remove(k)
            d["_evidence_notes"][k + "__withdrawn_203"] = (
                note(k) + "; that company files consolidated results too (see fund_cell_fix §203 entries)."
            )
            log_.append(f"never_filed_con -{k}")
    if log_:
        dump(p, d)
        run.setdefault("ledgers", {})["no_con_filing.json"] = log_
    # the reviewed-correction ledgers: re-asserted nightly after CI's rebuild, watched by verify_fills_live
    for name, new in (("fund_cell_fix.json", cell_fix["fund"]), ("revop_cell_fix.json", cell_fix["revop"])):
        if not new:
            continue
        p = os.path.join(HERE, name)
        d = json.load(open(p, encoding="utf-8"))
        have = {(f["sym"], str(f["qe"]), f["basis"]) for f in d["fixes"]}
        add = [f for f in new if (f["sym"], f["qe"], f["basis"]) not in have]
        if add:
            d["fixes"].extend(add)
            dump(p, d)
            run.setdefault("ledgers", {})[name] = [
                "{} {} {} {} -> {}".format(f["sym"], f["qe"], f["basis"], f["was"], f["fixed"]) for f in add
            ]
    for n, v in (run.get("ledgers") or {}).items():
        print("ledger %-28s %d: %s" % (n, len(v), ", ".join(v[:6]) + (" ..." if len(v) > 6 else "")))
    return out


if __name__ == "__main__":
    sys.exit(main())

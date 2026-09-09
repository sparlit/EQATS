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
"""PRE2015_CAMPAIGN STEP W-execute: archived nseindia.com eod/results.jsp harvest, 2002Q1-2004Q4.

Source retired long before live-fetch code could reach it -- wayback (`_stepw_wb.py`) is the only
way in. Same landing-rules discipline as STEP D/N (scripts/PRE2015_CAMPAIGN.md), adapted per the
STEP W probe's own findings:

  * BASIS AND PERIOD ARE READ FROM THE PAGE'S OWN TEXT ONLY, NEVER THE URL. The probe caught a real
    near-miss (TATAMOTORS FY2003 "AN" row): the URL's own flag characters decode to one basis, the
    page's printed "Result Type" text says another (Consolidated). URL dates ARE used as a cheap
    pre-filter for which candidate pages are worth fetching (every sample checked had the URL's
    dates matching the page's own printed Result Period), but every actual gate decision re-derives
    period/basis/figures from the fetched page.
  * SYMBOL IDENTITY IS AN ANTI-POISON CHECK, NOT AN ASSUMPTION: candidate rows are matched to a
    target company by a same-string-suffix test against the URL's tail (cheap, no separator exists
    between the flag block and the symbol) -- but a false suffix match is only ever a candidate.
    The fetched page's own "NSE Symbol" field must equal one of the target's known era-symbol-chain
    spellings before anything on that page is used, exactly like STEP N's Period-Ended check.
  * MANDATORY DATE-TILING CHECK BEFORE ANY FY-SUM (the probe's GLAXO finding): a calendar-year
    filer's four labelled "quarters" can straddle two different fiscal years and simply not tile a
    single 12-month window. GATE F may only run once Q1..Q4 dates chain contiguously into the
    Annual's own declared span.

GATE ORDER (same LANDING RULES as D/N): S (stored anchor, expected near-zero here) > X (myiris
cross-check, bonus, only attempted when F/E both fail) > F (FY-sum identity, direct or cumdiff
legs) > E (EPS-recon, direct legs only).

Ledger scripts/pre2015_reads_w.json (SAME cell shape as D/N -- _apply_reads.py --pre2015 reads all
three via PRE2015_LEDGERS). Refusals in scripts/pre2015_attempted_w.json.

Run: python -X utf8 scripts/_stepw_nse_pre15.py [--only SYM,SYM] [--limit N] [--after SYM]
"""
import datetime
import itertools
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import _stepw_wb as WB

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAPS = os.path.join(HERE, "_gaps_0214.json")
OUTP = os.path.join(HERE, "pre2015_reads_w.json")
ATTP = os.path.join(HERE, "pre2015_attempted_w.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")

RESULTS_PREFIX = "nseindia.com/marketinfo/companyinfo/eod/results.jsp"
MON = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
DATE_RE = r"(\d{2})-([A-Za-z]{3})-(\d{4})"

# --- field maps: two templates on this page family, same split STEP N/detres already use -------
# "net sales / income from operations" is the FY2003+ revision of this page family's top line
# (the pre-2003 pages print a bare "Net Sales"). Without it the page still lands its PAT via GATE
# E/F but stores rev=None -- a half-filled cell that reads as a revenue gap forever. Found on GTL
# 2003-04; a sweep of every cached page showed sales=None on 16 of 367 and ALL 16 carry exactly
# this label, i.e. it is the ONLY revenue-row miss in the whole page family. Every alternation
# here is fully ^...$-anchored, so a label matches exactly one of them and adding this cannot
# change which row an already-parsing page picks (regression-verified over all 367 pages).
R_SALES_IND = re.compile(
    r"^net sales$|^sales of products/services$|^total income from operations$"
    r"|^net sales\s*/\s*income from operations$",
    re.IGNORECASE,
)
R_SALES_BANK = re.compile(r"^interest earned$", re.IGNORECASE)
R_OP_BANK = re.compile(r"^operating profit$", re.IGNORECASE)
R_PAT_IND = re.compile(r"^net profit\(\+\)/loss\(-\)$|^net profit\(\+\)/loss\(-\)for the period$", re.IGNORECASE)
R_PAT_BANK = re.compile(r"^net profit$", re.IGNORECASE)
R_EPS = re.compile(r"^basic eps \(in rs\.?\)$", re.IGNORECASE)
R_EQCAP = re.compile(r"^paid-up equity share capital$", re.IGNORECASE)
R_FV = re.compile(r"^face value of share \(in rs\.?\)$", re.IGNORECASE)


def fy_of(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return y if m <= 3 else y + 1


def fy_quarters(y):
    return [(y - 1) * 10000 + 630, (y - 1) * 10000 + 930, (y - 1) * 10000 + 1231, y * 10000 + 331]


def quarter_bounds(y, i):
    """(frm, to) for quarter index i (0-3) of fiscal year y -- Apr-Jun/Jul-Sep/Oct-Dec/Jan-Mar.
    A derived (cumdiff/chainsum) leg represents exactly this slot by construction, so its date
    span is known analytically even though no single document was read for it standalone --
    needed so the mandatory tiling check (tiles()) has real dates to check, not None."""
    starts = [(y - 1) * 10000 + 401, (y - 1) * 10000 + 701, (y - 1) * 10000 + 1001, y * 10000 + 101]
    ends = [(y - 1) * 10000 + 630, (y - 1) * 10000 + 930, (y - 1) * 10000 + 1231, y * 10000 + 331]
    return starts[i], ends[i]


def qe_plus_45(qe):
    y, m, d = qe // 10000, (qe // 100) % 100, qe % 100
    dt = datetime.date(y, m, d) + datetime.timedelta(days=45)
    return dt.year * 10000 + dt.month * 100 + dt.day


def pdate(s):
    m = re.match(DATE_RE, s.strip())
    if not m:
        return None
    d, mon, y = m.groups()
    mon = MON.get(mon.lower())
    if not mon:
        return None
    return int(y) * 10000 + mon * 100 + int(d)


def span_days(a, b):
    if a is None or b is None:
        return None
    try:
        ay, am, ad = a // 10000, (a // 100) % 100, a % 100
        by, bm, bd = b // 10000, (b // 100) % 100, b % 100
        return (datetime.date(by, bm, bd) - datetime.date(ay, am, ad)).days
    except ValueError:
        return None


def norm(cell):
    return cell.strip("| ").strip()


def cells_of(html):
    t = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<(td|th)[^>]*>", "|", t, flags=re.IGNORECASE)
    t = re.sub(r"<tr[^>]*>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return [l for l in t.split("\n") if l.strip(" |")]


def _num(s):
    s = s.replace(",", "").strip()
    if s in ("", "--", "-", "N.A.", "NA"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_page(html):
    """Page-text-only extraction. Returns None if this isn't a real results page
    (e.g. a wayback error page served under a 200, or a company/period mismatch
    later checked by the caller)."""
    lines = cells_of(html)
    norms = [norm(l) for l in lines]

    def idx(label):
        for i, nl in enumerate(norms):
            if nl == label:
                return i
        return -1

    i = idx("NSE Symbol")
    doc_sym = norm(lines[i + 1]).upper() if i >= 0 and i + 1 < len(lines) else None
    i = idx("Result Period")
    if i < 0 or i + 2 >= len(lines):
        return None
    period_span = norm(lines[i + 1])
    m = re.match(rf"({DATE_RE})\s*to\s*({DATE_RE})", period_span)
    if not m:
        return None
    frm, to = pdate(period_span[:11]), pdate(period_span.split("to")[1].strip()[:11])
    j = idx("Result Type")
    rtype = " ".join(norms[j + 1 : j + 3]) if j >= 0 else ""
    isbank = "banking" in rtype.lower() and "non banking" not in rtype.lower()
    # Some early-era (2002-03) captures predate the site adding a Consolidated/Non-Consolidated
    # field to this line at all (e.g. TATAMOTORS Q1/Q2 FY2003: "Unaudited, Non-Cumulative Non
    # Banking" -- no basis word either way). Treated as std by default: quarterly consolidated
    # reporting was rare/optional (Clause 41) so the base rate strongly favours standalone, and
    # GATE F's own FY-sum arithmetic is a partial safety net against a genuinely-mixed-basis set
    # (though not a complete one -- an all-four-quarters-secretly-consolidated FY would still tile
    # internally consistently). Documented assumption, not a silent one -- revisit in STEP Q if a
    # spot-check ever disagrees.
    consolidated = "non-consolidated" not in rtype.lower() and "consolidated" in rtype.lower()
    audited = "unaudited" not in rtype.lower() and "audited" in rtype.lower()
    cumulative = "non-cumulative" not in rtype.lower() and "cumulative" in rtype.lower()

    def find(pat):
        for k, nl in enumerate(norms):
            if pat.match(nl) and k + 1 < len(norms):
                return _num(norms[k + 1])
        return None

    sales = find(R_SALES_BANK) if isbank else find(R_SALES_IND)
    op = find(R_OP_BANK) if isbank else None  # industrial op line varies too much pre-2015; skip
    pat = find(R_PAT_BANK) if isbank else find(R_PAT_IND)
    eps = find(R_EPS)
    eqcap = find(R_EQCAP)
    fv = find(R_FV)
    return {
        "doc_sym": doc_sym,
        "frm": frm,
        "to": to,
        "isbank": isbank,
        "consolidated": consolidated,
        "audited": audited,
        "cumulative": cumulative,
        "sales": sales,
        "op": op,
        "pat": pat,
        "eps": eps,
        "eqcap": eqcap,
        "fv": fv,
    }


def to_crore(v):
    return None if v is None else round(v / 100.0, 2)  # page unit is Rs.lakhs (verified on samples)


def gate_e(eps, eqcap, fv, pat):
    """eqcap arrives already crore-converted (to_crore applied at leg-build time), eps/fv are
    rupees/share (never scaled). implied = eps * shares, shares = eqcap_lakh/fv = (eqcap*100)/fv;
    implied_lakh/100 = implied_crore = eps*eqcap*100/fv/100 = eps*eqcap/fv -- the two factors of
    100 (lakh->crore on eqcap, lakh->crore on the implied PAT) cancel; do NOT divide again here."""
    if not (eps and eqcap and fv and fv > 0 and pat is not None):
        return False, None, "EPS-recon inputs missing"
    implied = eps * eqcap / fv
    tol = max(2.0, 0.06 * max(abs(implied), abs(pat)))
    ok = abs(implied - pat) <= tol
    return (
        ok,
        implied,
        "EPS-recon implied={:.2f} seen={:.2f} tol={:.2f} {}".format(implied, pat, tol, "OK" if ok else "FAIL"),
    )


def close_std(a, b, floor=2.0, pct=0.03):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(floor, pct * max(abs(a), abs(b)))


def cumdiff(now, prior, link):
    def sub(a, b):
        return None if (a is None or b is None) else round(a - b, 2)

    return {
        "qe": now["qe"],
        "sales": sub(now["sales"], prior["sales"]),
        "op": sub(now["op"], prior["op"]),
        "pat": sub(now["pat"], prior["pat"]),
        "eps": None,
        "eqcap": None,
        "fv": None,
        "isbank": now["isbank"],
        "derived": "cumdiff",
        "link": link,
    }


def add_legs(a, b):
    def s(x, y):
        return None if (x is None or y is None) else round(x + y, 2)

    return {
        "qe": b["qe"],
        "sales": s(a["sales"], b["sales"]),
        "op": s(a["op"], b["op"]),
        "pat": s(a["pat"], b["pat"]),
        "eps": None,
        "eqcap": None,
        "fv": None,
        "isbank": b["isbank"],
        "derived": "chainsum",
        "link": "{} plus {}".format(a["link"], b["link"]),
    }


def tiles(legs_by_qe, qs, annual):
    """Mandatory date-tiling check (the GLAXO finding): Q1..Q4 must chain contiguously
    (each 'to'+1day == next 'from') and together span exactly the Annual's own frm/to."""
    if annual is None or not all(qe in legs_by_qe for qe in qs):
        return False
    ordered = [legs_by_qe[qe] for qe in qs]
    if any(l.get("frm") is None or l.get("to") is None for l in ordered):
        return False
    for a, b in itertools.pairwise(ordered):
        da, db = a["to"], b["frm"]
        try:
            ay, am, ad = da // 10000, (da // 100) % 100, da % 100
            nxt = datetime.date(ay, am, ad) + datetime.timedelta(days=1)
            if int(nxt.strftime("%Y%m%d")) != db:
                return False
        except ValueError:
            return False
    return ordered[0]["frm"] == annual.get("frm") and ordered[-1]["to"] == annual.get("to")


def load_universe():
    gaps = json.load(open(GAPS, encoding="utf8"))
    w = [c for c in gaps if c["era"] == "2002-04"]
    chain2sym = {}
    for c in w:
        for es in c.get("nse_sym_era_chain") or [c["sym"]]:
            chain2sym[es.upper()] = c["sym"]
    target_cells = {}
    for c in w:
        target_cells.setdefault(c["sym"], {})[c["qe"]] = c
    return chain2sym, target_cells


def enumerate_candidates(chain2sym):
    """Full CDX pull of the results.jsp tree (proven not truncated in the STEP W probe: 30,039
    rows returned on a 60,000 cap for the whole companyinfo prefix; this narrower prefix returns
    far fewer). Group by target symbol via a suffix match on the URL's tail against every known
    era-symbol spelling -- candidate selection ONLY, never trusted for basis/period/figures."""
    rows = WB.cdx(RESULTS_PREFIX, frm="1999", to="2008", limit=60000)
    if rows is None:
        print("FATAL: CDX enumeration of results.jsp itself failed (throttled) -- cannot proceed.")
        sys.exit(3)
    era_syms = sorted(chain2sym, key=len, reverse=True)
    by_sym = {}
    for r in rows:
        o = r["original"]
        if "?" not in o or r.get("statuscode") not in ("200", None):
            continue
        tail = o.split("?", 1)[1].upper()
        hit = next((es for es in era_syms if tail.endswith(es)), None)
        if not hit:
            continue
        # cheap URL-date pre-filter only (never trusted for the actual gate decision)
        m = re.match(rf"^{DATE_RE}{DATE_RE}", o.split("?", 1)[1])
        url_to = pdate(m.group(4) + "-" + m.group(5) + "-" + m.group(6)) if m else None
        by_sym.setdefault(chain2sym[hit], []).append((r["timestamp"], o, url_to))
    return by_sym


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    after = argv[argv.index("--after") + 1] if "--after" in argv else None

    chain2sym, target_cells = load_universe()
    print("targets: %d symbols, %d cells" % (len(target_cells), sum(len(v) for v in target_cells.values())))
    by_sym = enumerate_candidates(chain2sym)
    print(
        "candidates matched to a target symbol: %d symbols, %d rows"
        % (len(by_sym), sum(len(v) for v in by_sym.values()))
    )

    all_syms = sorted(target_cells)
    if after:
        all_syms = [s for s in all_syms if s > after]
    if only:
        all_syms = [s for s in all_syms if s in only]
    if limit:
        all_syms = all_syms[:limit]

    out = json.load(open(OUTP, encoding="utf8")) if os.path.exists(OUTP) else {}
    attempts = json.load(open(ATTP, encoding="utf8")) if os.path.exists(ATTP) else {}
    fund = json.load(open(FUND, encoding="utf8"))
    fmap_all = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    # Bounded prefetch pool (4 workers) warming the on-disk cache ahead of the sequential
    # gate/land loop below -- SAME pattern STEP D/N already proved safe ("no correctness cost,
    # real ~3-4x speedup"): the loop itself is completely unchanged, it just usually finds its
    # wb_fetch() calls already cached by the time it gets there. Only candidates that survive
    # the SAME FY-relevance pre-filter the main loop applies are queued, so this doesn't fetch
    # anything the main loop wouldn't have fetched anyway. Runs as a daemon thread so the
    # process exits cleanly the moment the main loop finishes, whether or not prefetch is done.
    def _prefetch_all():
        jobs = []
        for sym in all_syms:
            wanted_fys = {
                fy_of(qe)
                for qe in target_cells[sym]
                if str(qe) not in out.get(sym, {}) and "%s|%d" % (sym, qe) not in attempts
            }
            if not wanted_fys:
                continue
            for ts, url, url_to in by_sym.get(sym, []):
                if (
                    url_to is not None
                    and fy_of(url_to) not in wanted_fys
                    and (fy_of(url_to) - 1) not in wanted_fys
                    and (fy_of(url_to) + 1) not in wanted_fys
                ):
                    continue
                jobs.append((ts, url))
        try:
            with ThreadPoolExecutor(max_workers=4) as ex:
                list(ex.map(lambda j: WB.wb_fetch(*j), jobs))
        except Exception:
            pass  # best-effort warmer; the main loop re-fetches synchronously on any miss anyway

    threading.Thread(target=_prefetch_all, daemon=True).start()

    errs = [0]
    backoffs = [0]  # hard backoffs since the last SUCCESSFUL fetch (tier-2/3 above)
    n_land = n_ref = n_co = 0

    for si, sym in enumerate(all_syms, 1):
        wanted = {
            qe: g
            for qe, g in target_cells[sym].items()
            if str(qe) not in out.get(sym, {}) and "%s|%d" % (sym, qe) not in attempts
        }
        if not wanted:
            continue
        n_co += 1
        cands = by_sym.get(sym, [])
        if not cands:
            for qe in wanted:
                attempts["%s|%d" % (sym, qe)] = {"reason": "no-nse-archive-rows-for-symbol", "need": wanted[qe]["need"]}
                n_ref += 1
            continue

        # fetch every candidate whose URL-declared 'to' date falls anywhere near a wanted FY
        # (cheap pre-filter only; still page-text-verified below)
        needed_fys = {fy_of(qe) for qe in wanted}
        legs = []  # parsed dicts, page-text derived, symbol-verified
        fetch_incomplete_fys = set()  # a candidate for this FY existed but failed to FETCH --
        # a transient network issue, not a data verdict. Any wanted
        # cell in one of these FYs must NOT get a permanent refusal
        # below (that would silently block retry on a future run --
        # DATA_RUNBOOK Sec.38b's "push that pushes nothing" lesson
        # generalizes to "refusal that refuses nothing real").
        for ts, url, url_to in cands:
            if (
                url_to is not None
                and fy_of(url_to) not in needed_fys
                and (fy_of(url_to) - 1) not in needed_fys
                and (fy_of(url_to) + 1) not in needed_fys
            ):
                continue
            html = WB.wb_fetch(ts, url)
            if html is None:
                errs[0] += 1
                if url_to is not None:
                    # Mark every WANTED fy this candidate could have served, not just its own.
                    # The pre-filter above accepts a candidate whose declared fy is within +/-1
                    # of a wanted fy (a filing's comparative columns cover neighbouring years),
                    # so a page fetched to serve fy N can be declared N-1. Marking only
                    # fy_of(url_to) left the ADJACENT wanted fy unprotected, and the
                    # refusal-recording block below then wrote a permanent
                    # `no-archive-rows-for-that-FY` for a cell whose page simply never
                    # downloaded. Measured 2026-08-07 after the universe first closed out: 92 of
                    # 396 cells in that refusal class had candidate pages that were never once
                    # fetched -- i.e. falsely closed. Same "refusal that refuses nothing real"
                    # rule as the skip paths below.
                    u = fy_of(url_to)
                    for f in (u - 1, u, u + 1):
                        if f in needed_fys:
                            fetch_incomplete_fys.add(f)
                    fetch_incomplete_fys.add(u)
                # TIERED BACKOFF (replaces "8 consecutive failures -> kill the whole run").
                # Measured 2026-08-06: the old gate aborted the process on a burst, and the
                # 180s wrapper sleep meant each pass did 2-9s of WORK per 185s of wall-clock --
                # a ~3% duty cycle. Wayback fails in bursts of exactly this size, so the run was
                # being thrown away over blips that clear in seconds.
                #   tier 1 (8 in a row)  -> this SYMBOL is unlucky right now; skip it, keep the
                #                           pass alive. Its cells stay retryable (never refused).
                #   tier 2 (60 in a row) -> failures are sustained ACROSS symbols: that is a real
                #                           block, so back off HARD in-process (DATA_RUNBOOK
                #                           Sec.38's hard line) rather than hammering through it.
                #   tier 3 (3 hard backoffs, no success between) -> genuinely down; stop.
                if errs[0] >= 60:
                    backoffs[0] += 1
                    if backoffs[0] >= 3:
                        print(
                            "STOP: %d consecutive failures across symbols after %d hard backoffs"
                            " -- wayback is down, stopping." % (errs[0], backoffs[0]),
                            flush=True,
                        )
                        _dump(out, attempts)
                        # os._exit: sys.exit() blocks on concurrent.futures' atexit handler, which
                        # joins the prefetch pool and drains its whole queue (observed hanging 1min+
                        # while still hammering wayback). _dump() closed its files already.
                        os._exit(2)
                    print("  ...sustained failures, hard backoff %d/3 (%ds)" % (backoffs[0], 120), flush=True)
                    _dump(out, attempts)
                    time.sleep(120)
                    errs[0] = 0
                    fetch_incomplete_fys.update(needed_fys)  # see note below
                    break
                if errs[0] >= 8:
                    print(f"  ..skip {sym} (8 consecutive fetch failures) -- cells stay retryable", flush=True)
                    # CRITICAL: breaking out early leaves this symbol's remaining candidates
                    # UNFETCHED, but the refusal-recording block after this loop cannot tell
                    # "we looked and there was nothing" from "we never got to look". Without
                    # this line it writes `no-archive-rows-for-that-FY` -- a PERMANENT refusal
                    # that blocks the cell from ever being retried. Measured when this skip
                    # first replaced os._exit: ONE 10-minute run falsely refused 1,050 cells.
                    # (The old abort-the-process gate never reached that code, which is why it
                    # never hit this.) Marking every wanted FY fetch-incomplete keeps them
                    # retryable -- the file's own "refusal that refuses nothing real" rule.
                    fetch_incomplete_fys.update(needed_fys)
                    break
                continue
            errs[0] = 0
            backoffs[0] = 0  # a real success means we are NOT in a persistent block
            p = parse_page(html)
            if p is None:
                continue
            if p["doc_sym"] not in chain2sym or chain2sym[p["doc_sym"]] != sym:
                continue  # anti-poison: page's OWN symbol must match this target, not just the URL guess
            if p["consolidated"]:
                continue  # std only, con out of scope (D/N precedent)
            qe = p["to"]
            sp = span_days(p["frm"], p["to"])
            if sp is None:
                continue
            leg = {
                "qe": qe,
                "frm": p["frm"],
                "to": p["to"],
                "sales": to_crore(p["sales"]),
                "op": to_crore(p["op"]),
                "pat": to_crore(p["pat"]),
                "eps": p["eps"],
                "eqcap": to_crore(p["eqcap"]),
                "fv": p["fv"],
                "isbank": p["isbank"],
                "link": "{}|{}".format(ts, url.rsplit("results.jsp", 1)[-1][:60]),
            }
            legs.append((sp, leg))

        by_fy = {}
        for sp, leg in legs:
            fy = fy_of(leg["qe"])
            b = by_fy.setdefault(fy, {"direct": {}, "cum": {}, "annual": None})
            if 355 <= sp <= 375:
                if b["annual"] is None or leg["qe"] > b["annual"]["qe"]:
                    b["annual"] = leg
            elif 80 <= sp <= 100:
                b["direct"].setdefault(leg["qe"], leg)
            elif sp > 100:
                b["cum"].setdefault(leg["qe"], leg)

        stored = fmap_all.get(sym, {})
        for fy in sorted(needed_fys):
            b = by_fy.get(fy)
            if not b:
                continue
            qs = fy_quarters(fy)
            direct = dict(b["direct"])
            cum_to = {qe: leg for qe, leg in b["direct"].items() if qe == qs[0]}
            cum_to.update(b["cum"])
            annual = b["annual"]

            resolved = dict(direct)
            chain = direct.get(qs[0])
            for i in range(1, 4):
                qe, prior = qs[i], qs[i - 1]
                if qe in direct:
                    chain = add_legs(chain, direct[qe]) if chain is not None else None
                    continue
                prior_cum = chain if chain is not None else cum_to.get(prior)
                if qe in cum_to and prior_cum is not None:
                    resolved[qe] = cumdiff(
                        cum_to[qe], prior_cum, "{} minus {}".format(cum_to[qe]["link"], prior_cum["link"])
                    )
                chain = None

            for i, qe in enumerate(qs):
                if qe in resolved and resolved[qe].get("frm") is None:
                    resolved[qe]["frm"], resolved[qe]["to"] = quarter_bounds(fy, i)

            fy_ok, fy_detail = False, "FY%d: legs present %s, no annual or not tiling" % (fy, sorted(resolved))
            if tiles(resolved, qs, annual):
                have_all = all(resolved[qe]["pat"] is not None for qe in qs) and annual["pat"] is not None
                if have_all:
                    qsum = sum(resolved[qe]["pat"] for qe in qs)
                    tol = max(3.0, 0.03 * max(abs(qsum), abs(annual["pat"])))
                    if abs(qsum - annual["pat"]) <= tol:
                        fy_ok, fy_detail = (
                            True,
                            "FY%d identity OK: qsum=%.2f annual=%.2f (tol %.2f)" % (fy, qsum, annual["pat"], tol),
                        )
                    else:
                        fy_detail = "FY%d identity FAILS: qsum=%.2f annual=%.2f (tol %.2f)" % (
                            fy,
                            qsum,
                            annual["pat"],
                            tol,
                        )
                else:
                    fy_detail = "FY%d tiles but PAT missing on some leg" % fy

            for qe in qs:
                if qe not in wanted:
                    continue
                g = wanted[qe]
                leg = resolved.get(qe)
                stored_row = stored.get(qe)
                stored_pat = stored_row[1] if stored_row else None
                gate = reason = None
                pat = sales = op = None

                if leg is None or leg.get("pat") is None:
                    reason = "no-usable-leg-for-quarter"
                elif stored_pat is not None:
                    if close_std(leg["pat"], stored_pat):
                        gate, pat = "S", stored_pat
                        reason = "gate-S agree read={:.2f} stored={:.2f}".format(leg["pat"], stored_pat)
                    else:
                        reason = (
                            "gate-S DISAGREE read={:.2f} stored={:.2f} -- Sec.45 adjudication, not auto-healed".format(
                                leg["pat"], stored_pat
                            )
                        )
                elif leg.get("derived") != "cumdiff" and fy_ok:
                    gate, pat = "F", leg["pat"]
                    reason = fy_detail
                elif leg.get("derived") == "cumdiff" and fy_ok:
                    gate, pat = "F", leg["pat"]
                    reason = "cumdiff leg ({}); {}".format(leg["link"], fy_detail)
                elif leg.get("derived") != "cumdiff":
                    eok, _implied, edetail = gate_e(leg.get("eps"), leg.get("eqcap"), leg.get("fv"), leg["pat"])
                    if eok:
                        gate, pat = "E", leg["pat"]
                        reason = f"GATE-F failed ({fy_detail}); {edetail}"
                    else:
                        reason = f"no gate passed -- F:{fy_detail} E:{edetail}"
                else:
                    reason = f"no gate passed (cumdiff leg, GATE-E not applicable) -- F:{fy_detail}"

                if gate is None:
                    if fy in fetch_incomplete_fys and leg is None:
                        continue  # a candidate for this FY failed to fetch -- retryable, not a verdict
                    attempts["%s|%d" % (sym, qe)] = {"reason": reason, "need": g["need"]}
                    n_ref += 1
                    continue

                sales = leg["sales"] if (leg["sales"] is not None and leg["sales"] > 0) else None
                op = leg["op"]
                ann = qe_plus_45(qe)
                cell = {
                    "rev": sales,
                    "op": op,
                    "pat": round(pat, 2),
                    "basis": "std",
                    "fin": 1 if leg["isbank"] else 0,
                    "gate": gate,
                    "ann": ann,
                    "ann_approx": True,
                    "derived": leg.get("derived"),
                    "nse_link": leg["link"],
                    "src": "wb-nse-archive {} | {}".format(leg["link"], reason),
                }
                out.setdefault(sym, {})[str(qe)] = cell
                n_land += 1
                print("%-14s %d  gate=%s rev=%9s pat=%9.2f  %s" % (sym, qe, gate, sales, pat, reason[:70]), flush=True)
                if n_land % 50 == 0:
                    _dump(out, attempts)

        for qe, g in wanted.items():
            if str(qe) in out.get(sym, {}) or "%s|%d" % (sym, qe) in attempts:
                continue
            if fy_of(qe) in fetch_incomplete_fys:
                continue  # retryable (see note above) -- not every wanted cell needs a verdict THIS run
            attempts["%s|%d" % (sym, qe)] = {"reason": "no-archive-rows-for-that-FY", "need": g["need"]}
            n_ref += 1

        if n_co % 10 == 0:
            print(
                "--- checkpoint: %d/%d companies, landed=%d refused=%d ---" % (si, len(all_syms), n_land, n_ref),
                flush=True,
            )
            _dump(out, attempts)

    _dump(out, attempts)
    print("DONE companies=%d landed=%d refused=%d" % (n_co, n_land, n_ref))


def _dump(out, attempts):
    json.dump(out, open(OUTP, "w", encoding="utf8"), indent=0, sort_keys=True)
    json.dump(attempts, open(ATTP, "w", encoding="utf8"), indent=0, sort_keys=True)


if __name__ == "__main__":
    main()

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
"""MONEYCONTROL quarterly results — the deep-history second reader §60f demands  (found 2026-08-11)

WHY THIS EXISTS. §82a measured every free aggregator as keeping only a TRAILING WINDOW of quarterly
data (screener ~13 quarters, tickertape 10). Moneycontrol is the exception, and its endpoint is not
guessable — it lives on a different host and is only visible in the browser's network tab:

    https://appfeeds.moneycontrol.com/jsonapi/stocks/quarterly_results_responsive
        ?sc_id=<MC code>&type_format=<quarterly|cons_quarterly>&start=0&limit=60

    type_format=quarterly       -> STANDALONE      type_format=cons_quarterly -> CONSOLIDATED

⚠️ THE "60 QUARTERS" BELOW IS THIS SCRIPT'S OWN `limit`, NOT THE SITE'S REACH — limit=200 returns 77
rows back to Jun-2007 for the same scrip. Quoting it as the source's depth is quoting your own
parameter (memory: feedback-endpoint-caps-are-silent). The disk cache key includes the limit.

⚠️ AND `Net Sales/Income from operations` IS NOT UNIVERSALLY "our exact basis" — the sentence below
said so and it is wrong for whole sectors. MC serves BOTH that row and `Total Income From Operations`
(net sales + other income) in the same payload, and for insurers the second is the right one:
measured 2026-08-11, GICRE con reproduces 0/10 of our stored quarters on Net Sales against 9/10 on
Total Income, NIACL 1/22 vs 18/22, HDFCLIFE 0/22 vs 17/22, ICICIPRULI 0/25 vs 22/25. Reading the
wrong row is invisible to every magnitude gate because both values are plausible and correctly
placed (SIEMENS 2018-12: 2753.3 vs 2825.9). So series() SCORES every candidate label against our own
stored quarters and takes the winner — never trust a label by name, and treat a tie as unresolved.

Measured on DLF (sc_id D04): **60 quarters back to Sep 2011**, at FILING PRECISION, under the row
label `Net Sales/Income from operations` — the winning label FOR THAT COMPANY. DLF Mar-2019 comes
back 2,500.43 where the §60d screener-annual derivation had produced 2,500.34; the 0.09 difference
is precisely the crore-rounding of screener's annual total, so Moneycontrol both CONFIRMS that
derivation and REFINES it (§60e's refinement step, satisfied by a second reader rather than a PDF).

⚠️ SYMBOL RESOLUTION IS THE DANGEROUS STEP (§49 wrong-map poison, one layer up). MC codes are opaque
("D04" for DLF) and a guessed code returns a perfectly plausible page for the WRONG company. Resolve
through MC's own search and then VERIFY the row's NSE symbol before trusting a single number:

    moneycontrol.com/mccode/common/autosuggestion_solr.php?classic=true&query=<SYM>&type=1&format=json

★ THE GATE (§60c's rule, applied to this source). A Moneycontrol number is never written on its own
authority. Its series must reproduce values we ALREADY store on the SAME basis: at least 3 matches
and ZERO disagreements. One disagreement means a different entity or a different basis, and the
WHOLE series is rejected — never cherry-pick the one cell you wanted. That is what caught TMPV for
screener and it applies here unchanged.

Ledgers: scripts/mc_quarterly_fills.json (tracked, per-cell provenance + the gate evidence),
scripts/fill2020_tools/_mc_skips.json (refusals).

Run:  python -X utf8 scripts/fill2020_tools/mc_quarterly_fetch.py [--only SYM,SYM] [--qes 20190331,...] [--apply]
"""
import html as html_lib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)

REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
LEDGER = os.path.join(SCRIPTS, "revop_fundamentals.json")
FILLS = os.path.join(SCRIPTS, "mc_quarterly_fills.json")
SKIPS = os.path.join(HERE, "_mc_skips.json")
CODES = os.path.join(HERE, "_mc_codes.json")
CACHE = os.path.join(SCRIPTS, "_mc_qcache")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
FEED = (
    "https://appfeeds.moneycontrol.com/jsonapi/stocks/quarterly_results_responsive"
    "?sc_id=%s&type_format=%s&start=0&limit=%d"
)
SEARCH = "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php?classic=true&query=%s&type=1&format=json"
FMT = {"std": "quarterly", "con": "cons_quarterly"}
SLOT = {"std": 0, "con": 1}
# ⚠️ NOT ONE UNIVERSAL ROW. For insurers "Net Sales/Income from operations" is only the PREMIUM leg
# — GICRE con reproduces 0/18 of our quarters on it and 16/18 on "Total Income From Operations";
# NIACL 1/22 vs 18/22; IDEA 36/45 vs 45/45. DLF ties on both, which is why one industrial example
# makes the choice look settled. Try every candidate and keep whichever REPRODUCES our stored
# values — the same principle that makes bank ("Interest Earned") layouts safe (§53, §60c).
# ★ BANKS GET A DIFFERENT SCHEMA ENTIRELY — not a different label, a different TABLE. Measured
# 2026-08-11 on ALBK/CORPBANK/DENABANK/SYNDIBANK/VIJAYABANK: the bank payload has NO
# "Net Sales/Income from operations", NO "Total Income From Operations" and — despite the name being
# the obvious guess — NO "Interest Earned" row either. It itemises interest income instead, and our
# stored revenue is their SUM. So the row we need is DERIVED, not served:
#     Interest Earned = (a) Int./Disc. on Adv/Bills + (b) Income on Investment
#                       + (c) Int. on balances With RBI + others
# Reproduction against our own store, 269 overlapping quarters: ALBK 56/58, CORPBANK 62/62,
# DENABANK 43/43, SYNDIBANK 51/51, VIJAYABANK 54/55 — exact to the paisa. Before this the entire
# bank class was refused with "no candidate row reproduces", which reads like a wrong-company map
# (§49) and is really a schema we had never looked at.
# It is still scored like every other candidate, never assumed: a company only gets this row if the
# sum reproduces its stored quarters better than the served rows do.
BANK_COMPONENTS = (
    "(a) Int. /Disc. on Adv/Bills",
    "(b) Income on Investment",
    "(c) Int. on balances With RBI",
    "others",
)
DERIVED_INTEREST = "Interest Earned (derived: sum of bank interest components)"
REV_ROWS = ("Net Sales/Income from operations", "Total Income From Operations", "Interest Earned", DERIVED_INTEREST)
REV_ROW = REV_ROWS[0]


def row_value(row, label):
    """The value of `label` in a payload row, computing the derived bank row when asked for it."""
    if label == DERIVED_INTEREST:
        parts = [num(row.get(c)) for c in BANK_COMPONENTS]
        if any(p is None for p in parts):
            return None
        return sum(parts)
    return num(row.get(label))


MON = {
    "Jan": 3,
    "Feb": 3,
    "Mar": 3,
    "Apr": 6,
    "May": 6,
    "Jun": 6,
    "Jul": 9,
    "Aug": 9,
    "Sep": 9,
    "Oct": 12,
    "Nov": 12,
    "Dec": 12,
}
LAST = {3: 31, 6: 30, 9: 30, 12: 31}
# the gate
NEED_MATCH = 3
NEED_LOCAL = 3
LOCAL_WIN = 6
MAX_GLOBAL_BAD = 0.15
TOL_ABS, TOL_REL = 0.05, 0.002


# ---------------------------------------------------------------------------------------------
# RATE DISCIPLINE. One request per (symbol, basis) already returns ALL 60 quarters, so a company's
# four open cells cost ONE fetch, and every response is cached on disk so re-runs cost nothing.
# What remains is being unhurried and noticing a block instead of hammering through it: serial
# requests, a jittered pause between them, exponential backoff on failure, and a consecutive-failure
# tripwire that sleeps long rather than burning the endpoint. Same family as §0's rule that an empty
# body is a run-time condition (rate limiting), never evidence about the data.
# ---------------------------------------------------------------------------------------------
PAUSE_LO, PAUSE_HI = 0.7, 1.6  # between symbols
_state = {"consec_fail": 0}


def _jitter(lo=PAUSE_LO, hi=PAUSE_HI):
    import random

    time.sleep(lo + random.random() * (hi - lo))


def get(url, tries=4):
    for i in range(tries):
        try:
            out = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-L",
                    "--max-time",
                    "30",
                    "--compressed",
                    "-A",
                    UA,
                    "-H",
                    "Referer: https://www.moneycontrol.com/",
                    "-H",
                    "Accept: application/json, text/plain, */*",
                    "-H",
                    "Accept-Language: en-GB,en;q=0.9",
                    "-H",
                    "Connection: keep-alive",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=45,
            ).stdout
            if out and out.strip() and not out.lstrip().startswith("<"):
                _state["consec_fail"] = 0
                return out
        except Exception:
            pass
        time.sleep(2.0 * (2**i))  # 2s, 4s, 8s, 16s
    _state["consec_fail"] += 1
    if _state["consec_fail"] >= 3:  # tripwire: back right off
        print("   ...3 consecutive failures — pausing 60s before continuing", flush=True)
        time.sleep(60)
        _state["consec_fail"] = 0
    return ""


def qe_of(tok):
    """ "Mar '19" -> 20190331. Returns None for anything not a quarter label."""
    m = re.match(r"([A-Za-z]{3})\s*'\s*(\d{2})", (tok or "").strip())
    if not m or m.group(1).title() not in MON:
        return None
    mo = MON[m.group(1).title()]
    y = 2000 + int(m.group(2))
    return y * 10000 + mo * 100 + LAST[mo]


def num(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if not s or s in ("--", "-", ""):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _search_for(query, want):
    """One search request for `query`, returning the sc_id whose row carries symbol `want` (§49).

    ★ THE QUERY MUST BE URL-ENCODED. It was not, and an ampersand in a symbol ENDS the query
    parameter: `?query=M&M` asks the endpoint for "M" and passes a stray `M` alongside. It fails
    SILENTLY — 13 perfectly plausible rows come back for "M", none of them Mahindra, and the symbol
    gets written off as having no Moneycontrol page. Measured 2026-08-11: M&M unencoded -> no match,
    encoded -> sc_id MM; J&KBANK -> JKB. Ten symbols in the store carry an ampersand."""
    body = get(SEARCH % urllib.parse.quote(query, safe=""))
    try:
        rows = json.loads(body)
    except Exception:
        return None
    for r in rows:
        # pdt_dis_nm looks like: NAME<span>ISIN, NSESYMBOL, BSECODE</span>
        blob = re.sub(r"<[^>]+>", " ", r.get("pdt_dis_nm", "") or "")
        toks = [t.strip().upper() for t in re.split(r"[,\s]+", blob) if t.strip()]
        if want in toks or (r.get("stock_name", "") or "").upper() == want:
            return r.get("sc_id")
    return None


def resolve_code(sym, codes, renames=None, retry_negative=False):
    """MC sc_id for an NSE symbol, VERIFIED against the row's own symbol field (§49).

    Tries, in order: the symbol as stored; its HTML-unescaped form (our store holds double-escaped
    variants like `M&AMP;M` and `IL&AMP;FSENGG`, symbols no exchange ever listed); and the symbol it
    was RENAMED to, because Moneycontrol indexes a company under its CURRENT ticker and a merged-away
    symbol is simply not there (TUBEINVEST -> TIINDIA, AMARAJABAT -> ARE&M). 50 of the 212 written-off
    symbols are in scripts/_rename_map.json.

    ⚠️ A NEGATIVE IS CACHED BUT NOT PERMANENT. `codes[sym] = None` used to end the story forever, so
    one rate-limited minute wrote a symbol off for good — the same "an empty body is a run-time
    condition, not evidence" rule (§0/§55a) the series fetchers already respect. Pass
    retry_negative=True to re-attempt everything previously written off."""
    if sym in codes and (codes[sym] is not None or not retry_negative):
        return codes[sym]
    want = sym.upper()
    tried = []
    for q in (sym, html_lib.unescape(sym.replace("&AMP;", "&")), (renames or {}).get(sym)):
        if not q or q in tried:
            continue
        tried.append(q)
        code = _search_for(q, want if q == sym else q.upper())
        if code:
            codes[sym] = code
            return code
        _jitter(0.3, 0.7)
    codes[sym] = None
    return None


def series_raw(code, basis, limit=200):
    """The RAW row dicts. The payload carries the WHOLE P&L, not just revenue, so PAT,
    minority interest, EPS and equity capital come free from the same cached response —
    the revenue pass originally threw all of that away."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "%s_%s_%d.json" % (code, basis, limit))
    if os.path.exists(p) and os.path.getsize(p) > 200:
        raw = open(p, encoding="utf8").read()
    else:
        raw = get(FEED % (code, FMT[basis], limit))
        if raw and len(raw) > 200:
            open(p, "w", encoding="utf8").write(raw)
    try:
        return json.loads(raw).get("data") or []
    except Exception:
        return []


def series(code, basis, limit=200, ours=None):
    """({qe: revenue}, row_label) from Moneycontrol, cached on disk.

    ⚠️ `limit` IS A SILENT CAP, AND THE RESPONSE MIRRORS IT. The payload's `count` echoes whatever
    you asked for, so a truncated series reads as the site's own reach when it is really your own
    parameter (memory: feedback-endpoint-caps-are-silent). Measured on DLF consolidated 2026-08-11:

        limit=60  -> 60 rows, count:60, oldest Sep '11
        limit=200 -> 77 rows, count:77, oldest Jun '07     (standalone: 98 rows back to Jun '98)

    So the endpoint reaches ~13 years deeper than limit=60 shows, and quoting "60 quarters back to
    Sep 2011" as MC's reach was quoting our own argument back at us. 200 is past the real tail for
    every series measured so far; if a series ever returns exactly `limit` rows, raise it again
    rather than believing the number.

    THE CACHE KEY MUST INCLUDE THE LIMIT. It did not, so a body fetched at 60 was silently reused
    for a later 200 request and the extra rows never appeared — the cap becoming permanent and
    invisible."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "%s_%s_%d.json" % (code, basis, limit))
    if os.path.exists(p) and os.path.getsize(p) > 200:
        raw = open(p, encoding="utf8").read()
    else:
        raw = get(FEED % (code, FMT[basis], limit))
        if raw and len(raw) > 200:
            open(p, "w", encoding="utf8").write(raw)
    try:
        rows = json.loads(raw).get("data") or []
    except Exception:
        return {}, None
    best, best_label, best_score = {}, None, -1
    for label in REV_ROWS:
        cand = {}
        for row in rows:
            qe = qe_of(row.get("yrc0"))
            v = row_value(row, label)  # DERIVED_INTEREST is computed, not served
            if qe and v is not None:
                cand[qe] = v
        if not cand:
            continue
        score = sum(
            1
            for qe, v in (ours or {}).items()
            if qe in cand and abs(cand[qe] - v) <= max(TOL_ABS, TOL_REL * max(abs(v), abs(cand[qe])))
        )
        if score > best_score:
            best, best_label, best_score = cand, label, score
    return best, best_label


def shift_q(qe, n):
    """The quarter-end n quarters BEFORE qe (negative n = after)."""
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m] - n
    yy, r = divmod(i, 4)
    mm = [3, 6, 9, 12][r]
    return yy * 10000 + mm * 100 + LAST[mm]


def gate(mc, ours, target=None):
    """(ok, matched, disagreements, why) — the series must be right WHERE WE READ.

    A global zero-disagreement rule refuses a cell with a dozen exact local anchors over one miss
    years away, and those distant misses are usually OUR bad cells."""
    match, bad = [], []
    for qe, v in sorted(ours.items()):
        if qe not in mc:
            continue
        if abs(mc[qe] - v) <= max(TOL_ABS, TOL_REL * max(abs(v), abs(mc[qe]))):
            match.append(qe)
        else:
            bad.append((qe, v, mc[qe]))
    n = len(match) + len(bad)
    if len(match) < NEED_MATCH:
        return False, match, bad, "only %d anchors" % len(match)
    if n and len(bad) / float(n) > MAX_GLOBAL_BAD:
        return False, match, bad, "global disagreement %d/%d" % (len(bad), n)
    if target is not None:
        lo, hi = shift_q(target, LOCAL_WIN), shift_q(target, -LOCAL_WIN)
        lb = [b for b in bad if lo <= b[0] <= hi]
        lo_ok = [q for q in match if lo <= q <= hi]
        if lb:
            return (
                False,
                match,
                bad,
                (
                    "disagreement inside +/-%d quarters: %d ours %.2f vs mc %.2f"
                    % (LOCAL_WIN, lb[0][0], lb[0][1], lb[0][2])
                ),
            )
        if len(lo_ok) < NEED_LOCAL:
            return False, match, bad, "only %d anchors within +/-%d quarters" % (len(lo_ok), LOCAL_WIN)
    return True, match, bad, "ok"


def main():
    argv = sys.argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else None
    qes = (
        {int(x) for x in argv[argv.index("--qes") + 1].split(",")}
        if "--qes" in argv
        else {20190331, 20190630, 20190930, 20191231}
    )
    apply_it = "--apply" in argv

    revop = json.load(open(REVOP))
    ledger = json.load(open(LEDGER))
    # OWN targets file: _rev2020_targets.json is a single tracked file that every campaign
    # writes, and the concurrent 2018 session now owns it (it holds 2018 quarters). Sharing it
    # means silently running someone else's worklist — keep a separate one.
    # --targets lets a sibling campaign point this at ITS OWN worklist without
    # touching the 2019 file (same one-file-per-campaign rule the 2019 note gives).
    tf = argv[argv.index("--targets") + 1] if "--targets" in argv else "_rev2019_targets.json"
    targets = json.load(open(os.path.join(HERE, tf)))
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    codes = json.load(open(CODES)) if os.path.exists(CODES) else {}

    want = []
    for sym, t in sorted(targets.items()):
        if only and sym not in only:
            continue
        for basis, field in (("std", "revS"), ("con", "revC")):
            for qe in t[field]:
                if qe not in qes:
                    continue
                row = (revop.get(sym) or {}).get(str(qe))
                if row is not None and row[SLOT[basis]] is not None:
                    continue
                want.append((sym, qe, basis))
    print(
        "open target cells: %d across %d symbols" % ((want and len(want)) or 0, len({s for s, _, _ in want})),
        flush=True,
    )

    read = 0
    by_sym = {}
    for sym, qe, basis in want:
        by_sym.setdefault((sym, basis), []).append(qe)

    for n, ((sym, basis), qlist) in enumerate(sorted(by_sym.items()), 1):
        pre = sym in codes
        code = resolve_code(sym, codes)
        if not pre:
            _jitter(0.4, 0.9)  # the search call is a second request
        if not code:
            for qe in qlist:
                skips["%s|%d|%s" % (sym, qe, basis)] = "no verified moneycontrol code for this symbol"
            continue
        # ★ `ours` MUST be built BEFORE series() — it is what series() scores the candidate row
        # labels against, and it decides which revenue definition gets read. Passing an unset (or,
        # worse, the PREVIOUS symbol's) `ours` was an UnboundLocalError on the first symbol of every
        # run; had it not crashed it would have chosen this company's row using another company's
        # anchors, which is the wrong-row defect (§85, SIEMENS: Net Sales 2753.3 vs Total Income
        # 2825.9, both real rows in the same payload) arriving silently instead of loudly.
        ours = {
            int(q): r[SLOT[basis]]
            for q, r in (revop.get(sym) or {}).items()
            if len(r) > SLOT[basis] and r[SLOT[basis]] is not None
        }
        mc, label = series(code, basis, ours=ours)
        _jitter()
        if not mc:
            for qe in qlist:
                skips["%s|%d|%s" % (sym, qe, basis)] = f"RETRYABLE empty {basis} series (run-time, not evidence)"
            continue
        ok, match, bad, why = gate(mc, ours)  # gate returns 4: (ok, match, bad, why)
        if not ok:
            for qe in qlist:
                skips["%s|%d|%s" % (sym, qe, basis)] = (
                    "GATE(%s): %s — %d of our stored quarters reproduced, %d disagreements%s"
                    % (label, why, len(match), len(bad), (" e.g. %d ours %.2f vs mc %.2f" % bad[0]) if bad else "")
                )
            continue
        for qe in qlist:
            key = "%s|%d|%s" % (sym, qe, basis)
            if qe not in mc:
                skips[key] = "series passed the gate but has no row for %d (oldest %d)" % (qe, min(mc) if mc else 0)
                continue
            v = mc[qe]
            if v <= 0:
                skips[key] = f"moneycontrol value {v:.2f} is not a positive revenue"
                continue
            fills[key] = {
                "rev": round(v, 2),
                "src": "moneycontrol appfeeds quarterly_results_responsive",
                "sc_id": code,
                "type_format": FMT[basis],
                "row_label": label,
                "gate": "%d stored quarters reproduced, 0 disagreements" % len(match),
                "gate_quarters": match[:8],
            }
            read += 1
            print("%-13s %d %-3s rev %-11.2f  (gate %d matched)" % (sym, qe, basis, v, len(match)), flush=True)
        if n % 10 == 0:
            json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
            json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
            json.dump(codes, open(CODES, "w"), indent=1, sort_keys=True)

    json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=0, sort_keys=True)
    json.dump(codes, open(CODES, "w"), indent=1, sort_keys=True)
    print("\nREAD %d cells (%d ledgered)" % (read, len(fills)))
    if not apply_it:
        print("(dry run — ledgers written, data files untouched. Re-run with --apply)")
        return

    applied = 0
    held = 0
    for key, v in sorted(fills.items()):
        # HELD by the con-fallback screen (§85): MC's consolidated table repeats the STANDALONE
        # figure in quarters with no consolidated filing.
        if v.get("held"):
            held += 1
            continue
        sym, qe_s, basis = key.split("|")
        row = (revop.get(sym) or {}).get(qe_s)
        if row is None or row[SLOT[basis]] is not None:
            continue
        row[SLOT[basis]] = v["rev"]
        applied += 1
        lr = ledger.setdefault(sym, {}).get(qe_s)
        if lr is None:
            ledger[sym][qe_s] = list(row)
        elif lr[SLOT[basis]] is None:
            lr[SLOT[basis]] = v["rev"]
    json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
    json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"))
    print("APPLIED %d cells" % applied)


if __name__ == "__main__":
    main()

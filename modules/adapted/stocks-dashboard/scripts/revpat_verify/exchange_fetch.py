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
"""exchange_fetch.py — the EXCHANGE-LEG arbitration fetcher for the REV/PAT verify campaign.

Given (SYMBOL, quarter-end YYYYMMDD, basis in {'std','con'}) this returns quarterly REVENUE and
PAT read straight from the two exchanges' own machine-readable filings, independent of every
retail site and independent of anything already stored in this project's own JSONs. It is meant
to be the arbitration source: if a stored value disagrees with what this returns, THIS is right
(after passing its own gates) and the stored value is the thing under suspicion — never the
reverse.

TWO ROUTES, walked in this order:
  route 1 -- BSE detailed-results JSON (runbook §42)
             https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w
             STANDALONE ONLY (measured: capability_card.md §A). Never attempted for basis='con'.
  route 2 -- NSE per-basis XBRL (runbook §54/§59b, memory "NSE list rows carry per-basis XBRL")
             https://www.nseindia.com/api/corporates-financial-results -> one row per (quarter,
             basis), each with an `xbrl` URL once the filing is XBRL-era (~2018+ per company).
             BOTH bases.

REFUSAL DISCIPLINE (hard requirement, not a suggestion): a route only ever returns a value when,
FROM THE RESPONSE ITSELF (never assumed, never inferred from the request):
  * the basis matches what was asked (BSE: no in-band basis field exists at all, so route 1
    simply never claims to serve 'con' — see capability_card.md §A; NSE: the context's
    NatureOfReportStandaloneConsolidated tag, or the list row's own `consolidated` field when the
    tag is absent, with that fallback always reported in `basis_declared` so a caller can tell
    the two apart);
  * the period spans EXACTLY 3 calendar months and ends on the target quarter-end.
Anything else is a structured refusal: {"refused": True, "reason": ..., "routes_tried": [...]}.
No value is ever a guess.

WHY THIS DOES NOT JUST CALL build_revop.parse_file AND TRUST IT. That function (imported below
and used for the reproducibility cross-check in every result's `nightly_parser_agrees` field) is
the nightly's own parser, so agreement with it is worth reporting -- but it has one gap this tool
must not inherit: for a COMBINED filing (one XBRL with both bases, one basis in context "OneD",
the other in "FourD"), parse_file keys the OUTPUT quarter-end off OneD's end date only and never
separately checks that FourD's own end date is the SAME quarter (build_revop.py lines 373-384).
Runbook §45 documents exactly this failure mode elsewhere ("XBRL context IDs have NO fixed
meaning across filers: FourD = year-ago in one file, YTD in another, preceding-quarter in a
third"). So this tool re-derives the period independently per context (via build_revop's own
ctx_period/RE_NAT helpers -- same regexes the nightly uses, just not the same blind assignment)
and REFUSES if the context actually carrying the requested basis does not itself end on the
target quarter. See capability_card.md §E for the measured cases this caught.

Run standalone:  python3 -X utf8 exchange_fetch.py SYMBOL YYYYMMDD std|con
Import:          from exchange_fetch import fetch; fetch("RELIANCE", 20240331, "std")

Network: curl_cffi (chrome TLS impersonation) for nseindia.com, plain urllib for
api.bseindia.com (no impersonation needed there -- measured, see capability_card.md §B transport
note). Minimum 2s between live requests. Every response is cached to ./_cache/ by URL so a
re-run, or a second (symbol,quarter) that reuses the same filing, costs zero network calls.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_cache")
os.makedirs(CACHE, exist_ok=True)

# READ-ONLY reference tree pinned at origin/main SHA 8e72b277 -- import shared parsers from HERE,
# never from the possibly-stale live checkout (see this campaign's brief).
REF_SCRIPTS = "/Users/dhruvan/stocks-wt/revpat-verify/scripts"
sys.path.insert(0, REF_SCRIPTS)
import build_revop as BR  # noqa: E402  -- the nightly's own XBRL parser + ctx_period/RE_NAT helpers

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MIN_INTERVAL = 2.0  # seconds between LIVE requests (campaign hard constraint)
_last_request_t = [0.0]

MON = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def _throttle():
    dt = time.time() - _last_request_t[0]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    _last_request_t[0] = time.time()


def _cache_path(name):
    return os.path.join(CACHE, re.sub(r"[^A-Za-z0-9._-]", "_", name))


# --------------------------------------------------------------------------------------------
# ROUTE 1 -- BSE detailed-results JSON (standalone only)
# --------------------------------------------------------------------------------------------
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd=%s&qtr=%s"


def bse_qid(qe):
    """QID = 'NN.00', NN = 85 + 4*(calendar_year(qe)-2015) + {Mar:0,Jun:1,Sep:2,Dec:3}.
    85 = Mar-2015 (runbook §42, RE-VERIFIED this campaign against RELIANCE/SBIN -- see
    capability_card.md §A). The formula also extrapolates BACKWARD correctly: QID 56 (=Dec-2007)
    returned a full 27-row RELIANCE response this campaign, so the endpoint's live floor is at or
    below 2007, not 2015 -- §42's "2015+" claim is about VALIDATED reach, not the hard floor. QID
    1 (~Mar-1994 by the same arithmetic) returned a 3-row stub (Type/Date Begin/Date End only, no
    financials), so somewhere between 1994 and 2007 the data thins out; this campaign did not
    pin the exact boundary (out of scope -- see scripts/PRE2015_CAMPAIGN.md for the dedicated,
    paused effort on that range). The bound below is deliberately generous; the REAL gate is the
    response-level Date Begin/End check downstream, which refuses cleanly on a stub."""
    y, m = qe // 10000, (qe // 100) % 100
    off = {3: 0, 6: 1, 9: 2, 12: 3}.get(m)
    if off is None:
        return None
    n = 85 + (y - 2015) * 4 + off
    return None if not -150 <= n - 85 <= 100 else "%d.00" % n


def _bse_scrip_master():
    """symbol(scrip_id, upper) -> SCRIP_CD, from BSE's live active-equity list. Cached to disk
    once; delisted names are NOT resolved here (route documented but not built -- see
    capability_card.md §E, this campaign's time-box did not reach it)."""
    path = _cache_path("bse_active_equity.json")
    if not os.path.exists(path):
        _throttle()
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
            "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
        )
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"})
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read()
        js = json.loads(data.decode("utf-8", "replace"))
        if len(js) < 4000:  # §0 rate-limit-stub guard: a healthy pull is ~4,900 rows
            raise RuntimeError("bse-scrip-master suspiciously small (%d rows) -- rate limit stub?" % len(js))
        open(path, "w", encoding="utf-8").write(json.dumps(js))
    js = json.loads(open(path, encoding="utf-8").read())
    return {row["scrip_id"].strip().upper(): row["SCRIP_CD"] for row in js if row.get("scrip_id")}


_BSE_MASTER = {}


def resolve_bse_scrip(symbol):
    if not _BSE_MASTER:
        _BSE_MASTER.update(_bse_scrip_master())
    return _BSE_MASTER.get(symbol.upper())


def _bse_detres_fetch(scrip_cd, qid):
    key = f"bse_detres_{scrip_cd}_{qid}.json"
    path = _cache_path(key)
    if os.path.exists(path):
        return json.loads(open(path, encoding="utf-8").read())
    _throttle()
    url = BSE_API % (scrip_cd, qid)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    js = json.loads(data.decode("utf-8", "replace"))
    open(path, "w", encoding="utf-8").write(json.dumps(js))
    return js


def _bse_dt(s):
    """'31-Mar-24' -> (2024,3,31). BSE's 2-digit year is windowed 2000+ (route only reaches
    2015+ so no century ambiguity in practice)."""
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", (s or "").strip())
    if not m:
        return None
    d, mo, y = m.groups()
    y = int(y)
    if y < 100:
        y += 2000
    if mo.title() not in MON:
        return None
    return (y, MON[mo.title()], int(d))


def _qe_of(ymd_tuple):
    if not ymd_tuple:
        return None
    y, m, d = ymd_tuple
    return y * 10000 + m * 100 + d


def bse_read(symbol, qe, basis, source_url_holder):
    """route 1. Only ever answers basis='std' -- see module docstring / capability_card.md §A."""
    if basis == "con":
        return None, (
            "route-does-not-serve-consolidated (measured: no working consolidated "
            "variant found for Corp_detailedResult_Transpose_ng -- capability_card.md §A)"
        )
    q = bse_qid(qe)
    if not q:
        return None, "qe-not-a-quarter-end-month-or-outside-detres-id-range"
    scrip = resolve_bse_scrip(symbol)
    if not scrip:
        return None, "no-bse-scrip-code (active-equity master only; delisted names unresolved -- not attempted)"
    url = BSE_API % (scrip, q)
    source_url_holder.append(url)
    try:
        rows = _bse_detres_fetch(scrip, q)
    except Exception as ex:
        return None, f"fetch-error:{type(ex).__name__}"
    t1 = rows.get("table1") or []
    if not t1:
        return None, "empty-table1 (no filing at this scrip_cd/qid, or a 162-byte-style rate-limit stub)"
    f = {}
    for row in t1:
        d = (row.get("fld_desc") or "").strip()
        if d and d not in f:
            f[d] = row.get("Value")

    def num(*names):
        for n in names:
            v = f.get(n)
            if v not in (None, "", "-"):
                try:
                    return float(v)
                except ValueError:
                    pass
        return None

    beg, end = _bse_dt(f.get("Date Begin")), _bse_dt(f.get("Date End"))
    if not beg or not end:
        return None, "no-date-begin-end-in-response"
    span_months = (end[0] * 12 + end[1]) - (beg[0] * 12 + beg[1])
    end_qe = _qe_of(end)
    period_days = None
    try:
        import datetime

        period_days = (datetime.date(*end) - datetime.date(*beg)).days
    except Exception:
        pass
    # ★ THE GATE ★ -- must be exactly a 3-calendar-month span (span_months==2, e.g. Jan->Mar) AND
    # end exactly on the target quarter (annual/H1 rows live in the same id space -- §42).
    if span_months != 2 or end_qe != qe:
        return None, (
            "period-span-fail (Date Begin=%s Date End=%s -> %d cal-months, ends %s, "
            "wanted %s)" % (f.get("Date Begin"), f.get("Date End"), span_months, end_qe, qe)
        )
    is_bank = num("Interest Earned/Net Income from sales/services") is not None
    if is_bank:
        rev = num("Interest Earned/Net Income from sales/services")
        rev_label = "Interest Earned/Net Income from sales/services"
    else:
        rev = num("Net Sales/Revenue From Operations")
        rev_label = "Net Sales/Revenue From Operations"
    pat = num("Net Profit")
    pat_label = "Net Profit"
    if pat is None:
        pat = num("Net Profit (+)/ Loss (-) from Ordinary Activities after Tax")
        pat_label = "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax"
    if pat is None:
        return None, "no-pat-row-in-response"
    if rev is None:
        return None, f"no-revenue-row-in-response (bank={is_bank})"
    return {
        "revenue": round(rev / 10.0, 2),
        "pat": round(pat / 10.0, 2),
        "source_url": url,
        "unit_declared": "Rs MILLION (not declared in-band by this endpoint -- established by "
        "calibration, capability_card.md §A) -> /10 for crore",
        "basis_declared": "standalone (route never serves any other basis -- see refusal above "
        "for basis='con'; NOT an in-response field, see capability_card.md §A)",
        "period_span_days": period_days,
        "raw_labels": {
            "revenue_label": rev_label,
            "pat_label": pat_label,
            "date_begin": f.get("Date Begin"),
            "date_end": f.get("Date End"),
            "type": f.get("Type"),
            "is_bank_format": is_bank,
        },
        "route": "bse-detres",
    }, None


# --------------------------------------------------------------------------------------------
# ROUTE 2 -- NSE per-basis XBRL
# --------------------------------------------------------------------------------------------
NSE_LIST_API = "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=%s&period=Quarterly"
_NSE_SESSION = [None]


def _nse_session():
    if _NSE_SESSION[0] is None:
        from curl_cffi import requests as cr

        s = cr.Session(impersonate="chrome")
        _throttle()
        s.get("https://www.nseindia.com/", timeout=20)
        _NSE_SESSION[0] = s
    return _NSE_SESSION[0]


def _nse_list_fetch(symbol):
    path = _cache_path(f"nse_list_{symbol.upper()}.json")
    if os.path.exists(path):
        return json.loads(open(path, encoding="utf-8").read())
    s = _nse_session()
    _throttle()
    url = NSE_LIST_API % urllib.parse.quote(symbol.upper(), safe="")
    r = s.get(
        url,
        headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"},
        timeout=20,
    )
    if r.status_code in (401, 403, 429):
        raise PermissionError("NSE list HTTP %d for %s" % (r.status_code, symbol))
    rows = json.loads(r.text)
    open(path, "w", encoding="utf-8").write(json.dumps(rows))
    return rows


def _nse_xbrl_fetch(url):
    fname = url.rsplit("/", 1)[-1]
    path = _cache_path(fname)
    if os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read(), fname
    s = _nse_session()
    _throttle()
    r = s.get(url, timeout=20)
    if r.status_code in (401, 403, 429):
        raise PermissionError("NSE xbrl HTTP %d for %s" % (r.status_code, url))
    xml = r.content.decode("utf-8", "replace")
    open(path, "w", encoding="utf-8").write(xml)
    return xml, fname


def _to_qe(dstr):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", (dstr or "").strip())
    if not m or m.group(2).title() not in MON:
        return None
    return int(m.group(3)) * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))


def _is_con_row(s):
    return (s or "").strip().lower() == "consolidated"


def nse_read(symbol, qe, basis, source_url_holder):
    """route 2. Both bases. Re-derives period+basis PER CONTEXT (not via parse_file's blind
    OneD->qe assignment -- see module docstring)."""
    want_con = basis == "con"
    try:
        rows = _nse_list_fetch(symbol)
    except PermissionError as ex:
        return None, f"NSE-BLOCKED:{ex}"
    except Exception as ex:
        return None, f"list-fetch-error:{type(ex).__name__}"
    cands = [
        r
        for r in rows
        if _is_con_row(r.get("consolidated")) == want_con
        and _to_qe(r.get("toDate")) == qe
        and r.get("xbrl")
        and not r["xbrl"].rstrip("/").endswith("/-")
    ]
    if not cands:
        n_any_basis = len([r for r in rows if _to_qe(r.get("toDate")) == qe])
        return None, (
            "no-xbrl-row-for-%s-this-quarter (%d list rows exist for this quarter on "
            "ANY basis -- xbrl may be a placeholder '/-', or this basis was simply not "
            "filed)" % (basis, n_any_basis)
        )
    cands.sort(key=lambda r: r.get("filingDate") or "", reverse=True)  # latest filing wins (revisions)
    last_reason = None
    for r in cands:
        url = r["xbrl"]
        source_url_holder.append(url)
        try:
            xml, fname = _nse_xbrl_fetch(url)
        except PermissionError as ex:
            return None, f"NSE-BLOCKED:{ex}"
        except Exception as ex:
            last_reason = f"xbrl-fetch-error:{type(ex).__name__}"
            continue
        symf = re.search(r'<in-(?:bse-fin|capmkt):Symbol contextRef="OneD"[^>]*>([^<]+)<', xml)
        if symf and symf.group(1).strip().upper() != symbol.upper():
            last_reason = f"symbol-mismatch-in-file:{symf.group(1)}"
            continue
        # ★ THE GATE ★, and a measured trap it exists because of (capability_card.md §E):
        # NSE now files ONE XBRL PER BASIS (confirmed this campaign), so the file we fetched was
        # already selected by the LIST ROW's own declared basis -- OneD is by construction the
        # context for the basis+quarter we asked for, and this tool trusts ONLY OneD as a value
        # source. FourD is deliberately NEVER used to fill in a value, because on every sampled
        # Q3 filing this campaign pulled (RELIANCE/SBIN/TCS, both bases) FourD's <xbrli:context>
        # declares the IDENTICAL start/end dates as OneD while the VALUES tagged under it are the
        # 9-month YTD cumulative (~2.9-3.0x OneD's figure) -- a same-declared-period, different-
        # actual-scope mismatch that no date check on the context's own declared span can catch,
        # because the declared span is (falsely) a perfect 3-month match. Trusting FourD as "the
        # other basis, same quarter" -- the assumption baked into build_fundamentals.py's own
        # docstring -- would have landed RELIANCE Mar-2024 std PAT as 42042.0 (the actual figure
        # is 11283.0) in this very run before the fix. See capability_card.md §E for the measured
        # detail and why this generalises runbook §45's context-id warning.
        chosen_ctx, nat_used = None, None
        per = BR.ctx_period(xml, "OneD")
        if per:
            s_, e_ = per
            try:
                import datetime

                sd = datetime.date(*(int(x) for x in s_.split("-")))
                ed = datetime.date(*(int(x) for x in e_.split("-")))
                months = (ed.year * 12 + ed.month) - (sd.year * 12 + sd.month)
                end_qe = ed.year * 10000 + ed.month * 100 + ed.day
            except Exception:
                months = end_qe = None
            if months == 2 and end_qe == qe:
                natm = BR.RE_NAT["OneD"].search(xml)
                nat = natm.group(1).strip().lower() if natm else None
                if nat is None or ("consol" in nat) == want_con:
                    chosen_ctx = "OneD"
                    nat_used = (
                        nat if nat is not None else f"(untagged in OneD; trusting list row's own declared {basis})"
                    )
        if chosen_ctx is None:
            fourd_note = ""
            per4 = BR.ctx_period(xml, "FourD")
            if per4:
                fourd_note = (
                    f" (a FourD context exists with declared period {per4} -- NOT used as a "
                    "fallback; see module docstring / capability_card.md §E)"
                )
            last_reason = f"OneD-does-not-confirm-3mo+basis-{basis}-in-{fname}{fourd_note}"
            continue
        rev, _op, _ebit, pat_total, pat_owners = BR.metrics_for(xml, chosen_ctx)
        if rev is None and pat_total is None and pat_owners is None:
            last_reason = f"no-usable-tags-in-chosen-context:{chosen_ctx}"
            continue
        if want_con:
            pat, pat_src = (
                (
                    pat_owners,
                    (
                        "owners-attributable (ProfitOrLossAttributableToOwnersOfParent "
                        "or bank ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates)"
                    ),
                )
                if pat_owners is not None
                else (pat_total, ("period-total (owners tag absent -- NOT owners-attributable, flagged)"))
            )
        else:
            pat, pat_src = pat_total, "period-total (== owners for standalone: no NCI)"
        if pat is not None and abs(pat) < 1e-9:
            last_reason = f"blank-zero-PAT-in-{chosen_ctx}-context (template row, not a result -- §53b.1)"
            continue
        if pat is None:
            last_reason = "no-PAT-tag-in-chosen-context"
            continue
        # cross-check vs the nightly's own parser, for the reproducibility claim
        nightly = None
        try:
            parsed = BR.parse_file(_cache_path(fname), fname)
            slot = (parsed or {}).get("con" if want_con else "std")
            if slot:
                nightly_pat = slot.get("owners") if want_con and slot.get("owners") is not None else slot.get("pat")
                nightly = {"rev": slot.get("rev"), "pat": nightly_pat}
        except Exception:
            pass
        agrees = None
        if nightly and nightly.get("pat") is not None and pat is not None:
            agrees = abs(nightly["pat"] - pat) < 0.02
        return {
            "revenue": None if rev is None else round(rev, 2),
            "pat": None if pat is None else round(pat, 2),
            "source_url": url,
            "unit_declared": "INR, XBRL decimals=-7 (i.e. rupees) -> /1e7 for crore (declared in "
            "the tag's own unitRef/decimals attributes)",
            "basis_declared": nat_used,
            "period_span_days": (ed - sd).days,
            "raw_labels": {
                "context": chosen_ctx,
                "pat_source": pat_src,
                "pat_total_tag_value_cr": pat_total,
                "pat_owners_tag_value_cr": pat_owners,
                "filingDate": r.get("filingDate"),
                "revised_candidates_seen": len(cands),
            },
            "route": "nse-xbrl",
            "nightly_parser_agrees": agrees,
            "nightly_parser_reproduced": nightly,
        }, None
    return None, last_reason or "all-candidates-exhausted"


# --------------------------------------------------------------------------------------------
# THE LADDER
# --------------------------------------------------------------------------------------------
def fetch(symbol, qe, basis):
    """(SYMBOL, quarter-end YYYYMMDD int, 'std'|'con') -> result dict, or
    {'refused': True, 'reason': ..., 'routes_tried': [...]}"""
    symbol = symbol.upper().strip()
    if basis not in ("std", "con"):
        return {"refused": True, "reason": "basis must be 'std' or 'con'", "routes_tried": []}
    routes_tried = []
    urls = []
    res, reason = bse_read(symbol, qe, basis, urls)
    routes_tried.append({"route": "bse-detres", "outcome": "OK" if res else reason})
    if res:
        return res
    res2, reason2 = nse_read(symbol, qe, basis, urls)
    routes_tried.append({"route": "nse-xbrl", "outcome": "OK" if res2 else reason2})
    if res2:
        return res2
    return {
        "refused": True,
        "reason": "not-found-via:{}".format(",".join(t["route"] for t in routes_tried)),
        "routes_tried": routes_tried,
        "urls_attempted": urls,
    }


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: exchange_fetch.py SYMBOL YYYYMMDD std|con")
        sys.exit(1)
    sym, qe_s, basis = sys.argv[1], sys.argv[2], sys.argv[3]
    out = fetch(sym, int(qe_s), basis)
    print(json.dumps(out, indent=1, default=str))

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
"""
Daily INCREMENTAL refresh for docs/sf_fundamentals.json (the backtest's quarterly
net-profit dataset). Instead of re-fetching all 5,000+ stocks, it asks NSE's
integrated-filing-results endpoint for everything filed in the last ~21 days
(ALL companies, one date-range call), parses net profit from each new filing, and
upserts the quarter into the dataset. Light: one list call + a handful of XBRL
fetches during earnings season, ~nothing otherwise.

Picks up automatically: new quarters for existing stocks AND brand-new IPOs
(GROWW, LENSKART, …) the day they first file. A company that files only standalone
gets NO consolidated value here -- the old con=std auto-copy was removed 2026-08-18
(user decision; see the tombstone comment at the former is_nosub site): con slots
hold only filing-backed values, and no-subsidiary names are N/A'd in
scripts/coverage_na_ledger.json with per-name evidence instead.

KNOWN BLIND SPOT (fill manually when it shows gaps):
  1. INSURERS (LICI/HDFCLIFE/ICICIPRULI/ICICIGI/GICRE/NIACL/SBILIFE/STARHEALTH/
     GODIGIT/NIVABUPA) file IRDAI-format results (Revenue A/c + Shareholders' P&L)
     that xbrl_profit can't parse -> they get NEITHER std nor con here. Extract per
     scripts/INSURER_EXTRACTION_PLAYBOOK.md.

Run: python -X utf8 update_fundamentals.py
"""
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # reuse _get / nse_jar / iso / xbrl_profit / MIN_QE
import fund_dup_guard  # ONE row per (sym, quarter-end) -- the sibling-basis ann copy below walks EVERY row


def gated_ann(bstr):
    """15:30 IST availability gate (memory project-stocks-1530-gate).

    NSE `broadcast_Date` looks like "16-Jan-2025 20:20" — it carries the filing
    TIME. The backtest rebalances at the 15:30 close and checks `annDate <= rebalanceDate`
    at DATE granularity, so a result broadcast AFTER 15:30 on a rebalance day would be
    wrongly treated as available that day (same-day look-ahead). So: if the broadcast
    time is after 15:30, the result is only actionable from the NEXT trading day — return
    that date. (Next *weekday* is engine-equivalent to next *trading day* here: rebalance
    dates are always trading days, so a `<=` test against one never lands on a skipped
    weekend/holiday.) Returns YYYYMMDD str, or "99999999" when no date is present."""
    d = B.iso(bstr)  # YYYYMMDD (date part) or None
    if not d:
        return "99999999"
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", bstr or "")
    if m and int(m.group(1)) * 60 + int(m.group(2)) > 15 * 60 + 30:
        nd = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:])) + datetime.timedelta(days=1)
        while nd.weekday() >= 5:  # skip Sat/Sun
            nd += datetime.timedelta(days=1)
        return nd.strftime("%Y%m%d")
    return d


from build_revop import strip_lender_ebit, xbrl_revop  # revenue + operating profit from the SAME filing XBRL

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")  # parallel rev/op dataset for the Results Season chart
MARK = os.path.join(ROOT, "docs", ".fund_updated")
WINDOW_DAYS = 120  # wide overlap: a full quarter, so even if the workflow misses a few runs the
# next one self-heals. Cheap because we SKIP the iXBRL fetch for quarters/bases
# already stored (see loop) — most filings in the window are already on file.


def main():
    if os.path.exists(MARK):
        os.remove(MARK)
    data = json.load(open(DOCS))
    try:
        revop = json.load(open(REVOP))  # {SYM:{QE:[revStd,revCon,opStd,opCon,patStd,patCon,fin,ebitStd,ebitCon]}}
    except Exception:
        revop = {}
    jar = B.nse_jar()
    h = {
        "User-Agent": B.UA,
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
    }
    today = datetime.date.today()
    frm = (today - datetime.timedelta(days=WINDOW_DAYS)).strftime("%d-%m-%Y")
    to = today.strftime("%d-%m-%Y")

    # ⚠️ The endpoint PAGINATES and defaults to only 20 rows (size=20), even though a peak
    # earnings day carries 80+ filings and the 120-day window holds thousands (totalCount says so).
    # Without paging, the cron silently saw only the latest 20 filings and dropped the rest — so on
    # a heavy results day most companies (e.g. MAHABANK/ELECON on 2026-07-10) never got fetched.
    # Page through with a large size until we've pulled totalCount rows. Downstream dedups by
    # (sym, qe), so any page overlap is harmless.
    # ⚠️ Query BOTH the mainboard (index=equities) AND SME/Emerge (index=sme) boards. SME results
    # file XBRL too, but WITHOUT this pass their numbers never parse — the filing shows on the page
    # while the number stays perma "numbers being parsed" (VIGOR/SHERA/KARNIKA/GSMFOILS, 2026-07).
    # Mirrors the SME fix on the announcements side (fetch_announcements). Mainboard is essential
    # (abort on failure); SME is best-effort (skip). Fresh session per board — NSE throttles sme
    # when it follows equities in the same session (see DATA_RUNBOOK §14).
    # ⚠️ In peak results season this endpoint gets SLOW — a size=500 page took >60 s and the old
    # single-try fetch died with "read operation timed out", then `return`ed with exit 0. That made
    # the outage TRIPLY INVISIBLE (green runs, no .fund_updated, no rebuild): ZERO numbers parsed
    # 2026-07-17→20 while the page showed "numbers being parsed" for every new filing. Rules:
    # smaller pages (size=200), longer timeout, RETRY each page with a FRESH session, and if the
    # mainboard still yields nothing, EXIT NONZERO so the workflow goes red — never a silent no-op.
    def warm_jar():
        """Fresh cookie jar warmed like a real visit: homepage (nse_jar) THEN the financial-results
        page itself — Akamai often serves the API a block page unless the corresponding HTML page's
        cookies are in the jar. (2026-07-20: API returned a non-JSON body until the page visit.)"""
        j = B.nse_jar()
        try:
            B._get(
                "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
                headers={"User-Agent": B.UA, "Accept": "text/html,application/xhtml+xml"},
                jar=j,
                timeout=30,
            )
        except Exception as e:
            print(f"  (warm page visit failed: {str(e)[:60]})")
        return j

    # ⚠️ 2026-07-20: NSE's Akamai began serving the bot-challenge HTML to this API for plain-urllib
    # TLS fingerprints (page-cookie warmup no longer helps; other endpoints still pass). Fallback
    # transport: curl_cffi Chrome impersonation — the same trick fetch_insurers uses. Lazy session,
    # created only when urllib gets blocked.
    _cffi = {"s": None}

    def cffi_get(url):
        if _cffi["s"] is None:
            from curl_cffi import requests as cr  # ImportError → caller's except logs it

            s = cr.Session(impersonate="chrome")
            s.get("https://www.nseindia.com/", timeout=30)
            s.get("https://www.nseindia.com/companies-listing/corporate-filings-financial-results", timeout=30)
            _cffi["s"] = s
        r = _cffi["s"].get(url, headers=h, timeout=150)
        if r.status_code != 200:
            _cffi["s"] = None  # dead session — rebuild on next call
            raise RuntimeError("curl_cffi HTTP %d" % r.status_code)
        return r.text

    # Last-resort transport: the project's Cloudflare Worker proxies this one API from CF's edge
    # (?filings= route, live-quote-worker.js) — Akamai passes CF while blocking datacenter IPs.
    WORKER = "https://stocksworld-quotes.dhruvan2510.workers.dev"

    def worker_get(idx_, page_):
        import urllib.error
        import urllib.request

        u = "%s/?filings=%s&from=%s&to=%s&page=%d&size=200" % (WORKER, idx_, frm, to, page_)
        req = urllib.request.Request(u, headers={"User-Agent": B.UA})
        # A 5xx from the WORKER is a transient CF/upstream hiccup (cold start, gateway blip) —
        # NOT the Akamai block the other transports hit. Worth its own in-place retry: on
        # 2026-07-20 every scheduled run died with "worker: HTTP Error 502" as attempt 4 of 4,
        # so the one rung that could still have passed was spent on a temporary error and the
        # whole day's fundamentals went unfilled. An Akamai block (403) is NOT retried here —
        # that one is real and the ladder should move on.
        for tries in range(3):
            try:
                return urllib.request.urlopen(req, timeout=150).read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code not in (502, 503, 504) or tries == 2:
                    raise
                print("  [worker] HTTP %d (transient) — retrying in %ds" % (e.code, 10 * (tries + 1)))
                time.sleep(10 * (tries + 1))
        return None

    rows = []
    prefer = ["urllib"]  # sticky: lead with whichever transport last worked
    for idx in ("equities", "sme"):
        jar = warm_jar()
        base = (
            f"https://www.nseindia.com/api/integrated-filing-results?index={idx}&period=Quarterly"
            f"&from_date={frm}&to_date={to}"
        )
        got, page, total, dead = 0, 1, 0, False
        while True:
            url = base + "&page=%d&size=200" % page
            # Transport ladder: urllib ×2 (2nd with re-warmed jar) → curl_cffi Chrome-TLS →
            # Cloudflare Worker proxy. STICKY: once a transport works, every later page LEADS
            # with it (a blocked transport stays blocked for the whole run — don't re-pay it).
            plans = {
                "urllib": ["urllib", "urllib", "cffi", "worker"],
                "cffi": ["cffi", "cffi", "worker", "urllib"],
                "worker": ["worker", "worker", "cffi", "urllib"],
            }[prefer[0]]
            jb = None
            for attempt, transport in enumerate(plans):
                if attempt:
                    print("  [%s] page %d retry %d via %s" % (idx, page, attempt, transport))
                    time.sleep(4 * attempt)  # spaced retries — hammering keeps the block alive
                try:
                    if transport == "urllib":
                        if attempt:
                            jar = warm_jar()
                        body = B._get(url, headers=h, jar=jar, timeout=150)
                    elif transport == "cffi":
                        body = cffi_get(url)
                    else:
                        body = worker_get(idx, page)
                    parsed = json.loads(body)
                    if isinstance(parsed, dict) and parsed.get("error"):  # Worker's structured failure
                        msg = "worker: {}".format(parsed["error"])
                        raise RuntimeError(msg)
                    jb = parsed
                    prefer[0] = transport
                    break
                except json.JSONDecodeError:
                    print(
                        "  [%s] page %d attempt %d [%s]: NON-JSON body: %r"
                        % (idx, page, attempt + 1, transport, body[:150])
                    )
                except Exception as e:
                    print("  [%s] page %d attempt %d [%s] failed: %s" % (idx, page, attempt + 1, transport, e))
            if jb is None:
                dead = page == 1  # page 1 dead = the board yielded nothing at all
                break  # deeper page dead = keep what we have (window overlaps self-heal)
            if isinstance(jb, list):  # defensive: pre-pagination shape (no envelope)
                rows.extend(jb)
                got += len(jb)
                break
            d = jb.get("data", []) or []
            rows.extend(d)
            got += len(d)
            # totalCount FLAPS between responses (observed 30080 → 12 mid-fetch) — trust the MAX
            # seen, never the latest, else a flaky envelope ends the loop early and drops filings.
            total = max(total, jb.get("totalCount") or 0)
            if not d or got >= total or page > 150:  # page cap = hard stop against a bad envelope
                break
            page += 1
        print("filings [%s] last %d days: +%d (%d pages)" % (idx, WINDOW_DAYS, got, page))
        if idx == "equities" and dead:
            print("FATAL: mainboard filings fetch yielded nothing — failing LOUD (no silent no-op)")
            sys.exit(1)  # red run = visible outage, not a quiet skip
    print("total filings: %d" % len(rows))

    byq = {}
    for r in rows:
        sym = r.get("symbol")
        qe = B.iso(r.get("qe_Date"))
        xb = r.get("xbrl", "")
        if not sym or not qe or not xb.startswith("http") or int(qe) < B.MIN_QE:
            continue
        if "governance" in (r.get("type", "") or "").lower():
            continue  # Governance filing has no P&L
        byq.setdefault((sym, qe), []).append(
            {"ann": gated_ann(r.get("broadcast_Date")), "xbrl": xb, "basis": r.get("consolidated", "")}
        )

    changed = newsyms = revop_changed = 0
    for (sym, qe), filings in byq.items():
        existing = next((x for x in data.get(sym, []) if x[0] == int(qe)), None)
        er = revop.get(sym, {}).get(str(qe))  # existing rev/op row for this (sym, quarter)
        std = con = None
        annStd = annCon = None
        rStd = rCon = oStd = oCon = eStd = eCon = None
        rFin = 0
        for f in sorted(filings, key=lambda x: x["ann"]):
            is_con = B.is_con_basis(f.get("basis"))  # NOT `"consol" in ...` -- see build_fundamentals.is_con_basis
            # Skip the ~1 MB iXBRL fetch only when BOTH net-profit AND rev/op for this basis are
            # already known (a bank is "known" once flagged fin). Keeps the wide window cheap.
            pat_have = (is_con and (con is not None or (existing and existing[3] is not None))) or (
                not is_con and (std is not None or (existing and existing[1] is not None))
            )
            # NB: no `er[6]` (fin-flag) shortcut here — banks/NBFCs/insurers all carry per-basis
            # rev/op since 2026-07, so "flagged fin" no longer means "nothing to extract"; the old
            # shortcut left e.g. HDFCLIFE's consolidated cell permanently None once std was stored.
            rev_have = (is_con and (rCon is not None or (er and er[1] is not None))) or (
                not is_con and (rStd is not None or (er and er[0] is not None))
            )
            if pat_have and rev_have:
                continue
            try:
                xml = B._get(
                    f["xbrl"], headers={"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"}, timeout=30
                )
            except Exception:
                continue
            s, c = B.xbrl_profit(xml, basis_hint=f.get("basis"))
            a = None if f["ann"] == "99999999" else int(f["ann"])
            if std is None and s is not None:
                std, annStd = s, a
            if con is None and c is not None:
                con, annCon = c, a
            try:  # rev/op is best-effort: never let it break the net-profit refresh
                rs2, os2, es2, rc2, oc2, ec2, fin2 = xbrl_revop(xml, basis_hint=f.get("basis"))
                if rStd is None and rs2 is not None:
                    rStd, oStd, eStd = rs2, os2, es2
                if rCon is None and rc2 is not None:
                    rCon, oCon, eCon = rc2, oc2, ec2
                if fin2:
                    rFin = 1
            except Exception:
                pass
        # --- upsert net profit (sf_fundamentals.json): only FILL missing fields (point-in-time) ---
        if std is not None or con is not None:
            if sym not in data:
                data[sym] = []
                newsyms += 1
            rec = data[sym]
            row = next((x for x in rec if x[0] == int(qe)), None)
            if row:
                upd = False
                if std is not None and row[1] is None:
                    row[1], row[2] = std, annStd
                    upd = True
                if con is not None and row[3] is None:
                    row[3], row[4] = con, annCon
                    upd = True
                if upd:
                    changed += 1
            else:
                rec.append([int(qe), std, annStd, con, annCon])
                rec.sort(key=lambda x: x[0])
                changed += 1
        # --- upsert revenue / operating profit (sf_revop.json): fill-only, parallel structure ---
        if rStd is not None or rCon is not None or rFin:
            d = revop.setdefault(sym, {})
            rr = d.get(str(qe)) or [None, None, None, None, None, None, 0, None, None]
            if len(rr) < 9:
                rr += [None] * (9 - len(rr))  # pad legacy 7-element rows -> add ebit slots
            if rr[0] is None and rStd is not None:
                rr[0] = rStd
            if rr[1] is None and rCon is not None:
                rr[1] = rCon
            if rr[2] is None and oStd is not None:
                rr[2] = oStd
            if rr[3] is None and oCon is not None:
                rr[3] = oCon
            if rr[4] is None and std is not None:
                rr[4] = std
            if rr[5] is None and con is not None:
                rr[5] = con
            if rFin:
                rr[6] = 1
            if rr[7] is None and eStd is not None:
                rr[7] = eStd
            if rr[8] is None and eCon is not None:
                rr[8] = eCon
            # Adjudicated no-ebit filers (banks + screener-layout lenders). This 15-min upsert is
            # the path that would resurrect the 2026-08-16 alignment one new quarter at a time —
            # exactly how a heal becomes a nightly rewrite.
            strip_lender_ebit(sym, rr)
            d[str(qe)] = rr
            revop_changed += 1

    # REMOVED 2026-08-18 (user decision): the no-subsidiary auto-fill that copied std into the con
    # slot when >=3 stored quarters had con==std. Its gate was a pattern in OUR OWN STORE, never a
    # check that a consolidated filing exists -- so it manufactured "consolidated" cells no filing
    # backs (TCIEXP held con back to 2016 although the company's first consolidated result, per its
    # own Q4FY23 note, was filed 27-May-2023). A con slot must hold only filing-backed values; a
    # no-subsidiary company's con coverage is handled by the N/A ledger (scripts/
    # coverage_na_ledger.json) with per-name evidence, not by fabricating cells. Do not reintroduce
    # a store-pattern copy here; historical copies are being retracted by the con-copy campaign.

    # Fill a missing result-announce date from the sibling basis: con & std are filed at the SAME
    # board meeting, so if a quarter has a profit value but a null announce-date on one basis while
    # the other basis HAS the date, copy it. Without this the engine skips that quarter (needs
    # annDate<=rebalance) and silently uses a STALE older quarter -> wrong profitYoY. Common for
    # insurers (IRDAI format) + recent IPOs, e.g. NIACL Q4FY24 npCon present, annCon null. (2026-06-23)
    for _rec in data.values():
        for _r in _rec:
            if len(_r) < 5:
                continue
            if _r[3] is not None and _r[4] is None and _r[2] is not None:
                _r[4] = _r[2]
                changed += 1
            if _r[1] is not None and _r[2] is None and _r[4] is not None:
                _r[2] = _r[4]
                changed += 1

    if not changed and not newsyms and not revop_changed:
        print("no new earnings — nothing to update")
        return
    # Normalise quarter-end order before the guard: rows MUST be sorted (the engine scans backwards
    # for the current quarter). This upsert sorts only the rec it appends to, so a symbol left out
    # of order by another writer (ci_preserve_merge appends a CI-only quarter without re-sorting)
    # would otherwise trip assert_ok's sorted-invariant. sort_rows is idempotent. (audit 2026-09-01)
    _reordered = fund_dup_guard.sort_rows(data)
    if _reordered:
        print("sorted %d symbol(s) whose rows were out of quarter-end order" % _reordered)
    fund_dup_guard.assert_ok(data, "update_fundamentals")
    json.dump(data, open(DOCS, "w"), separators=(",", ":"))
    json.dump(revop, open(REVOP, "w"), separators=(",", ":"))
    open(MARK, "w").write(today.isoformat())
    print(
        "upserted %d quarters (%d new symbols, %d rev/op cells); %d symbols total"
        % (changed, newsyms, revop_changed, len(data))
    )


if __name__ == "__main__":
    main()

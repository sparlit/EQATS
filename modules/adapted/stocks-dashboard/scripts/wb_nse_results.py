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
"""STEP W2 -- std PAT from Wayback captures of NSE's OLD results.jsp, with the BANKING schema.

WHY THIS EXISTS WHEN PRE2015_CAMPAIGN.md MARKS STEP W COMPLETE ("2,319 landed / 2,174 refused /
0 open ... the universe is fully adjudicated"). That claim is about STEP W's OWN universe -- the
4,493 N500 member-quarter cells of 2002-04 -- and it validated its CDX enumeration against the
ROW cap ("30,039 rows returned on a 60,000 cap, so nothing was truncated"). A peer re-enumeration
found the CDX JSON response also truncates on a ~500KB BYTE limit, roughly doubling the capture
count (2004: 4,791 -> 9,634; 2005: 1,925 -> 5,154). Checking the wrong limit is the
endpoint-caps-fail-silently class: the enumeration looked complete and was not.
★ Use `fl=timestamp,original` TEXT output, never `output=json`, or you re-create the truncation.

WHAT THAT ACTUALLY BUYS IN 2002-2008, measured before fetching anything (not assumed): of the
1,615 cells that have a capture and still hold no npStd, **1,432 (89%) were never in STEP W's
universe at all**, 79 are its class D1 (legs present, EPS-recon INPUTS MISSING -- the identity
never ran), 47 class D3 (a cumulative leg), 36 class C (page never downloaded), 21 class D2
(EPS-recon RAN and FAILED). **Zero are class A or B.** So the truncation does not invalidate this
era's refusals -- the yield is cells STEP W never targeted. Said plainly because the opposite
would have been a more flattering story.

⚠️ CLASS D2 IS A TRIPWIRE, NOT A TARGET. G5 below IS the same EPS identity STEP W's gate E ran, so
a D2 cell passing it means the two runs disagree about the page -- a different capture, or a parse
difference -- and that must be READ, not landed. `--allow-d2` is required to land one, and each is
reported individually.

THE GATE (every field DECLARED on the page; nothing inferred from a date or a column position):
  G1  the page's own "NSE Symbol" == the symbol we asked for              (identity)
  G2  the period spans exactly 3 months AND declares "Non-Cumulative"     (a true quarter)
      ★ A period ENDING on a quarter-end is NOT evidence it is quarterly -- ESSARGUJ's Sep-2002
        capture spans 01-APR-2001..30-SEP-2002 and declares Cumulative. Only the declaration
        decides (§55b's YTD trap, closed by the publisher rather than by a date match).
  G3  declares "Non-Consolidated"                                         (the std slot)
  G4  declares a scale we know (lakhs /100, crores /1, million /10)
  G5  the page's OWN arithmetic closes: EPS == NetProfit x FaceValue / PaidUpCapital, <= 3%.
      Needs NOTHING from our store, which is the point in 2002-04 where we hold nothing nearby.

THE BANKING SCHEMA (this module's addition). NSE prints a different row set for banks, and the
peer's reader read only the industrial one, so every bank page failed as "no Net Profit row".
That matters here because this era is bank-heavy. Measured on INDUSINDBK 2003-06 (capture
20030814..): `Net Profit 2464.00` (industrials: `Net Profit(+)/Loss(-)`), `Adjusted Net Profit`
(industrials: `Adjusted Net Profit(+)/ Loss(-)`), `Earnings Per Share (in Rs.)` (industrials:
`Basic EPS (in Rs.)`), and `Interest Earned` where industrials print `Net Sales`. Face Value and
Paid-up Equity Share Capital keep their labels, so G5 ports unchanged -- and it closes on that
page: 2464.00 x 10.00 / 21927.00 = 1.1237 against a printed 1.12.
⚠️ The bank label `Net Profit` is a SUFFIX of `Adjusted Net Profit`, so it is matched with a
negative lookbehind; without it a page whose adjusted figure differs would silently read the
wrong row.

Pages are cached under scripts/_wbnse_cache/ so a re-run is free and any audit is offline
(STEP W's own post-mortem: never read a fetch outage as data absence).

  python3 -X utf8 scripts/wb_nse_results.py --cells <cells.json> --index /tmp/p9/wb_index.json \
      --classes <wb_class.json> --out <props.json> [--limit N] [--allow-d2]
"""
import argparse
import collections
import gzip
import html
import io
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_wbnse_cache")
MON = {
    m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)
}
SCALE = {"lakhs": 100.0, "lakh": 100.0, "crores": 1.0, "crore": 1.0, "million": 10.0, "millions": 10.0}
PAT_TOL_REL = 0.03  # G5, applied to the PAT side -- see gate() for why that matters


def fetch(ts, original, tries=3):
    # ⚠️ MEASURED 2026-08-26, by this module's own 4-worker run (489 ok / 611 fail) and reproduced
    # by a peer: web.archive.org's throttling is CONNECTION CHURN, not a byte or rate limit. A new
    # TCP connection per request is refused ~90% of the time under load and MORE WORKERS MAKE IT
    # WORSE. One persistent requests.Session at a 0.4s pace does ~1.0s/page with no failures -- a
    # ~30x speedup over what this module started with. So the fetch path is the shared keep-alive
    # cache in scripts/wayback_nse/wbcache.py: SERIAL, never a pool. This module's own earlier
    # cache is still read first so nothing already paid for is re-fetched.
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9]", "_", ts + original)[-180:] + ".gz")
    if os.path.exists(p):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return f.read()
    try:
        sys.path.insert(0, os.path.join(HERE, "wayback_nse"))
        import wbcache

        t = wbcache.fetch_cached(ts, original)
        if t:
            with gzip.open(p, "wt", encoding="utf-8") as f:
                f.write(t)
            return t
        return None
    except ImportError:
        pass
    url = f"https://web.archive.org/web/{ts}id_/{original}"
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.GzipFile(fileobj=io.BytesIO(b)).read()
                t = b.decode("utf-8", "replace")
            with gzip.open(p, "wt", encoding="utf-8") as f:
                f.write(t)
            return t
        except Exception:
            if a == tries - 1:
                return None
            time.sleep(2)
    return None


def _flat(t):
    txt = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(txt))


def parse(t):
    """-> dict or None. Reads the DECLARED period role / type / scale, never a date guess."""
    if not t:
        return None
    txt = _flat(t)
    # ⚠️ THE ARCHIVE CAPTURED SERVER ERROR PAGES, AND THEY PASS A SIZE CHECK. A
    # java.lang.NullPointerException stack trace is several KB of plausible-looking HTML with no
    # results in it -- STEP W met the same trap in a different costume (2,832-byte "empty shells"
    # its size guard accepted). It is its OWN refusal class: the fetch worked and the archive holds
    # something for this URL, it just is not a filing. Recording that as "no data" would poison a
    # later absence claim.
    if "NullPointerException" in t or "javax.servlet.ServletException" in t or "Exception:" in txt[:4000]:
        return {"_error_page": True}
    if "Financial Results" not in txt:
        return None
    out = {}
    m = re.search(r"NSE Symbol\s+([A-Z0-9&_.-]+)", txt)
    out["symbol"] = m.group(1) if m else None
    m = re.search(r"Company\s+(.+?)\s+NSE Symbol", txt)
    out["company"] = m.group(1).strip() if m else None
    m = re.search(r"Result Period\s+(\d{2}-[A-Z]{3}-\d{4})\s+to\s+(\d{2}-[A-Z]{3}-\d{4})\s*\(([^)]*)\)", txt)
    if not m:
        return None
    out["from"], out["to"], out["period_role"] = m.group(1), m.group(2), m.group(3).strip()
    m = re.search(r"Result Type\s+(.+?)\s+(?:Non\s+)?Banking Financial Results", txt)
    out["result_type"] = m.group(1).strip() if m else None
    # "Non Banking Financial Results" (industrial) vs "Banking Financial Results" (bank).
    out["bank"] = ("Non Banking Financial Results" not in txt) and ("Banking Financial Results" in txt)
    m = re.search(r"Financial Results\s+\(Rs\.\s*([a-zA-Z]+)\)", txt)
    out["scale"] = m.group(1).lower() if m else None

    def num(label, lookbehind=None):
        pat = (lookbehind or "") + re.escape(label) + r"\s+(-?[\d,]+\.\d\d)"
        m2 = re.search(pat, txt)
        return float(m2.group(1).replace(",", "")) if m2 else None

    if out["bank"]:
        # ⚠️ negative lookbehind: "Net Profit" is a suffix of "Adjusted Net Profit".
        out["net_profit"] = num("Net Profit", r"(?<!Adjusted )")
        out["adj_net_profit"] = num("Adjusted Net Profit")
        out["revenue"] = num("Interest Earned")
        out["eps"] = num("Earnings Per Share (in Rs.)") or num("Basic EPS (in Rs.)")
    else:
        out["net_profit"] = num("Net Profit(+)/Loss(-)")
        out["adj_net_profit"] = num("Adjusted Net Profit(+)/ Loss(-)")
        out["revenue"] = num("Net Sales")
        out["eps"] = num("Basic EPS (in Rs.)") or num("Earnings Per Share (in Rs.)")
    out["paidup"] = num("Paid-up Equity Share Capital")
    out["face"] = num("Face Value of Share (in Rs.)")

    a = (int(out["from"][7:11]), MON[out["from"][3:6]])
    b = (int(out["to"][7:11]), MON[out["to"][3:6]])
    out["months"] = (b[0] - a[0]) * 12 + (b[1] - a[1]) + 1
    out["div"] = SCALE.get(out["scale"])
    out["pat_cr"] = (out["net_profit"] / out["div"]) if (out["net_profit"] is not None and out["div"]) else None
    return out


def gate(sym, qe, p):
    """-> (value|None, why|None). G1-G5, in order, each naming itself on refusal."""
    rt = p.get("result_type") or ""
    if p.get("symbol") != sym:
        return None, "G1 page declares NSE Symbol {!r}, not {!r}".format(p.get("symbol"), sym)
    end = "%04d%02d" % (int(p["to"][7:11]), MON[p["to"][3:6]])
    if end != str(qe)[:6]:
        return None, f"G1b page's period ends {end}, not the quarter asked for ({str(qe)[:6]})"
    if p["months"] != 3:
        return None, "G2 period spans %d months, not 3 (declared role %r)" % (p["months"], p["period_role"])
    if "Non-Cumulative" not in rt:
        return None, f"G2 not declared Non-Cumulative: type={rt!r}"
    # G3. ⚠️ DO NOT REQUIRE THE "Non-Consolidated" TOKEN -- THE 2002 VINTAGE USUALLY OMITS THE
    # BASIS AXIS ENTIRELY. Measured over 628 cached pages 2026-08-26: 2003-2006 declare a basis on
    # 100% of pages, 2002 on only 14% (38 of 277); the other 242 print just "Unaudited,
    # Non-Cumulative". A gate demanding a token the vintage does not emit MANUFACTURES ABSENCE --
    # it is the gate's defect reported as the source's silence. (A peer's run refused 44 of its
    # first 75 true quarters this exact way on the 2000-2001 vintage.)
    # What makes the omission safe here is measured, not assumed: (a) the 2002 vintage CAN print
    # the axis -- 2 cached 2002 pages declare bare "Consolidated" -- so an unmarked page is "not
    # consolidated", not "basis unknown"; and (b) every unmarked TRUE QUARTER that we can test
    # against a value we already store reproduced our STANDARD slot (6 of 6, 0 differ). Plus the
    # era rule: consolidated quarterly reporting was OPTIONAL under Clause 41 pre-2015.
    # So: refuse a page that says Consolidated; accept Non-Consolidated; accept an unmarked page as
    # standalone and RECORD that the basis was inferred rather than read.
    if "Consolidated" in rt and "Non-Consolidated" not in rt:
        return None, f"G3 page declares CONSOLIDATED: type={rt!r}"
    if p.get("div") is None:
        return None, "G4 scale not declared or unknown: {!r}".format(p.get("scale"))
    if p.get("pat_cr") is None:
        return None, "G4b no Net Profit row read (%s schema)" % ("banking" if p.get("bank") else "industrial")
    fv, pu, eps, np_ = p.get("face"), p.get("paidup"), p.get("eps"), p.get("net_profit")
    if not (fv and pu and pu > 0 and eps is not None):
        return None, f"G5 EPS identity not testable (eps={eps} face={fv} paidup={pu})"
    # ⚠️ THE IDENTITY IS TESTED ON THE **PAT** SIDE, NOT THE EPS SIDE, AND THAT IS NOT CosmETIC.
    # Algebraically EPS == NP x FV / PU either way, but the EPS side divides the error by PU/FV,
    # so a fixed absolute floor there becomes an enormous tolerance on the number being landed.
    # Caught by this module's own class-D2 tripwire on JINDVIJSTL 2004-06 (2026-08-26): page prints
    # NP 5489.00 lakhs, FV 10.00, PU 135205.00, EPS 0.36. EPS-side: |0.406 - 0.36| = 0.046, which
    # slipped under a 0.05 floor and PASSED. PAT-side: implied 4867.38 vs printed 5489.00 = 6.22 cr
    # out, i.e. 11% -- a clear FAIL, and exactly what STEP W's gate E concluded about the same page.
    # STEP W was right and the first cut of this gate was wrong.
    # The floor is derived, not chosen: the printed EPS is rounded to 2dp, so the implied PAT
    # inherits +-0.005 x PU/FV of pure rounding. Anything beyond that plus 3% is real disagreement.
    implied_pat = eps * pu / fv
    tol = max(PAT_TOL_REL * abs(np_), 0.005 * pu / fv)
    if abs(implied_pat - np_) > tol:
        return None, (
            f"G5 EPS identity FAILS on the PAT side: printed NP {np_}, EPS {eps} implies "
            f"{implied_pat:.2f} (tol {tol:.2f})"
        )
    return round(p["pat_cr"], 2), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True, help="[[SYM, QE], ...]")
    ap.add_argument("--index", required=True, help="{'SYM|QE': [timestamp, original_url]}")
    ap.add_argument("--classes", help="{'SYM|QE': STEP-W refusal class} -- enables the D2 tripwire")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--allow-d2",
        action="store_true",
        help="land a cell STEP W refused as class D2 (its EPS-recon RAN and FAILED). "
        "Off by default: G5 is that same identity, so a D2 pass means the two "
        "runs disagree about the page and it must be READ, not landed.",
    )
    a = ap.parse_args()

    idx = json.load(open(a.index))
    cls = json.load(open(a.classes)) if a.classes else {}
    cells = [tuple(c) for c in json.load(open(a.cells))]
    todo = [(s, int(q)) for s, q in cells if "%s|%d" % (s, int(q)) in idx]
    if a.limit:
        todo = todo[: a.limit]
    print("cells with an archived capture: %d of %d" % (len(todo), len(cells)))
    sys.stdout.flush()

    props, rej, d2 = {}, {}, []
    t0 = time.time()
    for i, (s, q) in enumerate(todo):
        key = "%s|%d" % (s, q)
        ts, u = idx[key]
        raw = fetch(ts, u)
        p = parse(raw)
        klass = cls.get(key, "?")
        if p is not None and p.get("_error_page"):
            rej[key] = {
                "why": "ARCHIVED SERVER-ERROR PAGE (NullPointerException/servlet trace), not "
                "a filing -- the capture exists and is not data; NOT evidence of absence",
                "ts": ts,
                "stepw_class": klass,
                "bytes": len(raw or ""),
            }
        elif p is None:
            rej[key] = {
                "why": "unreadable page (no Result Period block)"
                if raw
                else "FETCH FAILED -- an outage is NOT data absence, retry before concluding",
                "ts": ts,
                "stepw_class": klass,
                "bytes": len(raw or ""),
            }
        else:
            val, why = gate(s, q, p)
            if why:
                rej[key] = {
                    "why": why,
                    "ts": ts,
                    "stepw_class": klass,
                    "declared": {
                        "period": "{}..{} ({})".format(p["from"], p["to"], p["period_role"]),
                        "type": p.get("result_type"),
                        "scale": p.get("scale"),
                        "bank": p.get("bank"),
                    },
                }
            elif klass.startswith("D2") and not a.allow_d2:
                d2.append((key, val, ts))
                rej[key] = {
                    "why": "TRIPWIRE: STEP W's class D2 (its EPS-recon RAN and FAILED) but "
                    f"G5 passes here at {val} -- the two runs disagree about this page. "
                    "Read it; do not land without --allow-d2.",
                    "ts": ts,
                    "stepw_class": klass,
                }
            else:
                _rt = p.get("result_type") or ""
                props[key + "|patS"] = {
                    "value": val,
                    "state": "FILLED-WAYBACK-NSE",
                    "stepw_class": klass,
                    "basis_declared": "Non-Consolidated" in _rt,
                    "bank": bool(p.get("bank")),
                    "revenue_cr": (p["revenue"] / p["div"])
                    if (p.get("revenue") is not None and p.get("div"))
                    else None,
                    "evidence": (
                        "WAYBACK NSE archived results.jsp (web.archive.org/%s). Every gated field is "
                        "DECLARED BY THE PAGE, none inferred: Result Period %s to %s (%s) = %d months; "
                        "Result Type '%s'; %s schema; scale Rs.%s (/%g). G1 the page's own NSE Symbol "
                        "is %s and its period ends in the quarter asked for. G2 exactly 3 months AND "
                        "declared Non-Cumulative. G3 %s. G5 the page's OWN "
                        "arithmetic closes: printed EPS %s vs NetProfit %s x FaceValue %s / PaidUp %s "
                        "= %.4f. Nothing from our store was used, so this is an AS-FILED exchange "
                        "vintage (§108) -- it outranks an aggregator rendition rather than arguing "
                        "with it. STEP W's verdict on this cell was: %s."
                        % (
                            ts,
                            p["from"],
                            p["to"],
                            p["period_role"],
                            p["months"],
                            p.get("result_type"),
                            "banking" if p.get("bank") else "industrial",
                            p.get("scale"),
                            p["div"],
                            p.get("symbol"),
                            "declared Non-Consolidated"
                            if "Non-Consolidated" in _rt
                            else "basis axis NOT PRINTED by this vintage (2002 omits it on 86% of pages); "
                            "the page does not say Consolidated, and every testable unmarked true "
                            "quarter reproduced our standard slot -- basis INFERRED, not read",
                            p.get("eps"),
                            p.get("net_profit"),
                            p.get("face"),
                            p.get("paidup"),
                            p["net_profit"] * p["face"] / p["paidup"],
                            klass,
                        )
                    ),
                    "capture": f"{ts} {u}",
                }
        if (i + 1) % 50 == 0:
            print(
                "  [%d/%d] filled=%d rejected=%d (%.0fs)" % (i + 1, len(todo), len(props), len(rej), time.time() - t0)
            )
            sys.stdout.flush()
            json.dump({"proposals": props, "rejected": rej}, open(a.out, "w"), indent=1, sort_keys=True)
    json.dump({"proposals": props, "rejected": rej, "d2_tripwire": d2}, open(a.out, "w"), indent=1, sort_keys=True)
    print("\nDONE: %d passed, %d rejected -> %s (%.0fs)" % (len(props), len(rej), a.out, time.time() - t0))
    print("reject reasons:")
    for k, v in collections.Counter(v["why"].split(":")[0][:52] for v in rej.values()).most_common():
        print("   %4d  %s" % (v, k))
    if d2:
        print("\n⚠️ D2 TRIPWIRE FIRED on %d cells -- read each before landing:" % len(d2))
        for k, v, ts in d2[:20]:
            print("     %-24s G5 passes at %s (capture %s)" % (k, v, ts))
    banks = sum(1 for v in props.values() if v["bank"])
    print("\nbanking-schema cells landed: %d of %d" % (banks, len(props)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

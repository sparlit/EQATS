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
"""Fetch NSE INSIDER-TRADING disclosures (SEBI PIT Reg 7(2)) into a rolling window:
docs/insider.json — read by the Insider Trades page + the Discovery promoter bucket.

HOW (v2 — the XBRL-index pipeline; v1's symbol-sweep is retired, see below):
  1. /api/corporates-pit-gg?index=equities  (NO date params — they misbehave) returns the
     filing INDEX for roughly the last ~75 days: [{appId, symbol, companyName,
     broadcastDateTime, xmlFileName, typeOfSubmission, prevAppId, ...}] — metadata only,
     no transaction numbers.
  2. Every filing not yet processed (meta.seen appIds) gets its XBRL fetched from
     nsearchives (static host, no rate pain) and parsed: each Disclosure<N> context is one
     person-transaction with NameOfThePerson, CategoryOfPerson, qty/value/TransactionType,
     ModeOfAcquisitionOrDisposal, post-% holding. Equity-share rows only.
  3. Rows merge into the rolling window; a REVISED filing (prevAppId set) replaces the
     original filing's rows.

WHY NOT the obvious APIs (verified 2026-07-16 — don't re-derive):
  - Market-wide /api/corporates-pit?index=equities&from_date&to_date returns {"data":[]}
    for EVERY session/param variant. The legacy dataset behind it FROZE ~2026-04-21 (PIT
    moved to XBRL submissions, "PIT V2.0 (30-04-2026)" per the XML header comment).
  - The legacy symbol query (corporates-pit?symbol=X) returns only that company's latest
    ≤20 pre-freeze disclosures, newest-first; pageno is ignored; adding dates zeroes it.
    A one-time full-universe sweep of it seeded the pre-May sliver of the window.
  - corporates-pit-gg's own from_date/to_date filter on something else (16 rows for a week
    that visibly has more) — so we always take the full default index and dedup.

Output schema (compact arrays):
  {"updated","from","to","seen":[appId,...],
   "rows":[[bcast "YYYY-MM-DD", sym, company, person, cat, side, qty, val_rupees,
            mode, pctPost, key], ...]}
  cat  P=Promoter/Promoter Group  D=Director  K=KMP/Designated/Employee  O=Other
  side B=Buy S=Sell P=Pledge R=Revoke/Release I=Invocation O=Other
  mode MP=Market Purchase MS=Market Sale OM=Off Market ES=ESOP/Exercise PF=Preferential
       RI=Rights GF=Gift PL=Pledge RV=Revoke IV=Invoke BB=Buyback OT=Other
  key = 'g<appId>#<ctx>' (XBRL rows) or the legacy NSE did (seed rows). Value stays in
  RUPEES (page shows ₹cr = val/1e7).

Run:  python -X utf8 scripts/fetch_insider.py
"""
import datetime
import html
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "insider.json")
WINDOW_DAYS = 92
SLEEP_XBRL = 0.15
MAX_XBRL_PER_RUN = 2000  # seed run processes ~1,400; daily runs a few dozen
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


def iso_date(s):
    """'16-Jul-2026 17:04:10' / '2026-07-16' -> 'YYYY-MM-DD'."""
    s = str(s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})", s)
    if not m:
        return None
    mo = MON.get(m.group(2).lower())
    return "%s-%02d-%02d" % (m.group(3), mo, int(m.group(1))) if mo else None


def to_num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def cat_of(s):
    s = str(s or "").lower()
    if "promoter" in s:
        return "P"
    if "director" in s:
        return "D"
    if "designated" in s or "kmp" in s or "key managerial" in s or "employee" in s:
        return "K"
    return "O"


def side_of(s):
    s = str(s or "").lower()
    if s.startswith("buy") or "acquisition" in s:
        return "B"
    if s.startswith("sell") or "disposal" in s:
        return "S"
    if "revoke" in s or "release" in s:
        return "R"
    if "invocation" in s or "invoke" in s:
        return "I"
    if "pledge" in s:
        return "P"
    return "O"


def mode_of(s):
    s = str(s or "").lower()
    for pat, code in (
        ("market purchase", "MP"),
        ("market sale", "MS"),
        ("exercise", "ES"),
        ("esop", "ES"),
        ("off market", "OM"),
        ("off-market", "OM"),
        ("preferential", "PF"),
        ("rights", "RI"),
        ("gift", "GF"),
        ("revoke", "RV"),
        ("invocation", "IV"),
        ("invoke", "IV"),
        ("pledge", "PL"),
        ("buy back", "BB"),
        ("buyback", "BB"),
    ):
        if pat in s:
            return code
    return "OT"


FIELD_RE = re.compile(r'<in-bse-co:([A-Za-z0-9]+)\s+contextRef="([^"]+)"[^>]*>([^<]*)<')


def parse_xbrl(xml, bcast, sym, company, app_id):
    """One PIT XBRL -> rows. Each Disclosure<N> context = one person-transaction."""
    ctx = {}
    for tag, c, val in FIELD_RE.findall(xml):
        if c == "MainI":
            continue
        ctx.setdefault(c, {})[tag] = val.strip()
    rows = []
    for c, f in ctx.items():
        # instrument reads 'Equity' or 'Equity Shares'; 'Any other instrument' (ADRs etc.),
        # warrants and debentures are dropped
        inst = f.get("TypeOfInstrument", "").lower()
        if "equity" not in inst or "other" in inst:
            continue
        person = html.unescape(" ".join(f.get("NameOfThePerson", "").split()))
        qty = to_num(f.get("SecuritiesAcquiredOrDisposedNumberOfSecurity"))
        val = to_num(f.get("SecuritiesAcquiredOrDisposedValueOfSecurity"))
        pct = next(
            (
                to_num(v)
                for k, v in f.items()
                if k.startswith("SecuritiesHeldPost") and k.endswith("PercentageOfShareholding")
            ),
            None,
        )
        if not person:
            continue
        rows.append(
            [
                bcast,
                sym,
                html.unescape(company),
                person,
                cat_of(f.get("CategoryOfPerson")),
                side_of(f.get("SecuritiesAcquiredOrDisposedTransactionType")),
                int(qty or 0),
                round(val or 0.0),
                mode_of(f.get("ModeOfAcquisitionOrDisposal")),
                pct,
                f"g{app_id}#{c}",
            ]
        )
    return rows


def main():
    today = datetime.date.today()
    lo = (today - datetime.timedelta(days=WINDOW_DAYS - 1)).isoformat()

    old_rows, seen = [], set()
    try:
        old = json.load(open(OUT, encoding="utf-8"))
        old_rows = [r for r in old.get("rows", []) if r[0] >= lo]
        seen = {str(x) for x in old.get("seen", [])}
    except Exception:
        pass
    rows = {r[10]: r for r in old_rows}

    jar = B.nse_jar()
    hdr = {
        "User-Agent": B.UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
    }
    try:
        idx = (
            json.loads(
                B._get(
                    "https://www.nseindia.com/api/corporates-pit-gg?index=equities", headers=hdr, jar=jar, timeout=90
                )
            ).get("data")
            or []
        )
    except Exception as ex:
        print(f"index fetch FAILED ({ex}) — keeping the previous file", flush=True)
        sys.exit(1)
    print("filing index: %d filings, %d already processed" % (len(idx), len(seen)), flush=True)

    done = errs = fresh = 0
    live_ids = set()
    for f in idx:
        app_id = str(f.get("appId") or "").strip()
        xml_url = str(f.get("xmlFileName") or "").strip()
        bcast = iso_date(f.get("broadcastDateTime"))
        sym = str(f.get("symbol") or "").strip().upper()
        if not (app_id and xml_url and bcast and sym):
            continue
        live_ids.add(app_id)
        if app_id in seen or bcast < lo:
            continue
        if done >= MAX_XBRL_PER_RUN:
            break
        try:
            xml = B._get(xml_url, headers={"User-Agent": B.UA}, timeout=45)
            new = parse_xbrl(xml, bcast, sym, str(f.get("companyName") or "").strip(), app_id)
            prev = str(f.get("prevAppId") or "").strip()
            if prev:  # revised filing replaces the original's rows
                for k in [k for k in rows if k.startswith(f"g{prev}#")]:
                    del rows[k]
            for r in new:
                if r[10] not in rows:
                    fresh += 1
                rows[r[10]] = r
            seen.add(app_id)
            done += 1
        except Exception:
            errs += 1  # not marked seen — retried next run
            time.sleep(1)
        if done and done % 200 == 0:
            print("  ...%d filings parsed (%d rows fresh, %d errs)" % (done, fresh, errs), flush=True)
        time.sleep(SLEEP_XBRL)
    print("processed %d new filings (%d errors), %d fresh rows" % (done, errs, fresh), flush=True)

    if old_rows and len(rows) < 0.6 * len(old_rows):
        print("REFUSING to write: merged %d < 60%% of previous %d" % (len(rows), len(old_rows)), flush=True)
        sys.exit(1)

    seen = {s for s in seen if s in live_ids}  # trim to the index's own rolling window
    allr = sorted(rows.values(), key=lambda r: (r[0], r[1], str(r[10])), reverse=True)
    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    out = {
        "updated": ist.strftime("%Y-%m-%d %H:%M"),
        "from": lo,
        "to": today.isoformat(),
        "seen": sorted(seen),
        "rows": allr,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    days = sorted({r[0] for r in allr})
    print(
        "Wrote %s: %d rows over %d days %s..%s (%.0f KB)"
        % (
            OUT,
            len(allr),
            len(days),
            days[0] if days else "-",
            days[-1] if days else "-",
            os.path.getsize(OUT) / 1024.0,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

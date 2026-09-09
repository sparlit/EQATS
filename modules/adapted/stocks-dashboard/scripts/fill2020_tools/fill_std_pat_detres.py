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
"""FILL-2020: standalone PAT for 2015-2020 gap cells via the BSE detailed-results JSON (runbook §42).

WHY NOT THE PDF ROUTE. These cells resisted the announcement/PDF path for two reasons found
2026-08-06: (1) the stored announce dates for old quarters are unreliable -- several look like a
quarter-end+45d default rather than a real filing date (APLLTD Sep-2015 is stored 20151114, actually
filed 20151027), so a tight window finds nothing; (2) pre-2016 BSE attachments use an
underscore+timestamp name that AttachHis/AttachLive no longer serve (404), so even located filings
cannot be downloaded. The detailed-results JSON sidesteps both -- it is keyed by quarter, not by
announcement, and it is structured rather than scanned.

    https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd=<CODE>&qtr=<QID>
    QID = "NN.00", NN = 85 + (quarters since Mar-2015)     -- 85 = Mar-2015
    Values are AS-ORIGINALLY-FILED, in Rs MILLION -> /10 for crore. Standalone/primary basis only,
    which is exactly the basis these gaps need.

GATES (runbook §42 discipline -- a PAT fill needs a reconstruction, not just a printed number):
  1. Date Begin/End must span ~3 months and END on the target quarter-end. The same id space also
     holds annual and H1 rows; without this check a 12-month figure lands as a quarter.
  2. EPS reconstruction: EPS x (Equity Capital / Face Value) must reproduce Net Profit within
     EPS_TOL. This independently confirms the number is a quarterly owners-basis PAT at the
     declared scale. Cells that cannot be reconstructed are reported, never written.
  3. Fill-only: the target std cell must currently be None.

Sanity note, not a gate: for most of these companies the standalone result SHOULD differ from the
stored consolidated (they have subsidiaries -- that is why con was filed separately). An exact
con==std match is therefore worth eyeballing rather than trusting.

Run:  python -X utf8 scripts/fill2020_tools/fill_std_pat_detres.py [--apply] [--only SYM,SYM]
      (default DRY RUN.)
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs", "sf_fundamentals.json")
MIRROR = os.path.join(ROOT, "scripts", "fundamentals.json")
SCRIPS = os.path.join(ROOT, "scripts", "bse_scrips.json")
LEDGER = os.path.join(ROOT, "scripts", "std_pat_detres_fills.json")

API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_detailedResult_Transpose_ng/w?scrip_cd=%s&qtr=%s"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
EPS_TOL = 0.06  # runbook §42: EPS-recon gate is +/-6%
FY_ABS, FY_REL = 3.0, 0.03  # runbook §42 FY-consistency gate: max(3cr, 3%)
MONTHS = {
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

# Delisted/renamed companies are absent from bse_scrips.json (built from the live master).
# Resolved 2026-08-06 from ListofScripData?status=Delisted (10,797 records -- validate the count,
# a 162-byte body is BSE's rate-limit stub, runbook §0).
SCRIP_OVERRIDE = {"ADVANTA": "532840", "DISHMAN": "532526", "CAPF": "532938"}


def qid(qe):
    """'NN.00' where NN counts quarters from Mar-2015 = 85."""
    y, m = qe // 10000, (qe // 100) % 100
    n = 85 + (y - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    return "%d.00" % n


def get(scrip, q):
    req = urllib.request.Request(API % (scrip, q), headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_dt(s):
    try:
        d, mo, y = s.split("-")
        return (2000 + int(y)) * 10000 + MONTHS[mo] * 100 + int(d)
    except Exception:
        return None


def fields(js):
    out = {}
    for r in js.get("table1") or []:
        out.setdefault(r.get("fld_desc", "").strip(), r.get("Value"))
    return out


def fnum(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def ref_shares(scrip, qe, cache):
    """Share count (millions) from the NEAREST quarter that still prints Equity Capital + Face Value.

    The Ind-AS-era rows (roughly 2017+) drop both, and rename EPS to "Basic for discontinued &
    continuing operation", so the direct recon is impossible on those quarters alone. Share count is
    stable between corporate actions, so the closest quarter that does carry it is a sound reference
    -- and if a split/bonus HAS intervened the reconstruction simply fails the tolerance and the cell
    is skipped, which is the safe direction.
    """
    y, m = qe // 10000, (qe // 100) % 100
    base = (y - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    for off in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8):
        n = base + off
        if not 0 <= n <= 47:
            continue
        q = "%d.00" % (85 + n)
        if (scrip, q) not in cache:
            try:
                cache[(scrip, q)] = fields(get(scrip, q))
            except Exception:
                cache[(scrip, q)] = {}
            time.sleep(0.4)
        g = cache[(scrip, q)]
        eq, fv = fnum(g, "Equity Capital"), fnum(g, "Face Value (in Rs)")
        if eq and fv:
            return eq / fv, q
    return None, None


def fy_gate(scrip, qe, np_mn, stored, cache):
    """Fallback gate: the candidate + the fiscal year's other three quarters must reconcile to the
    audited annual row (QID NN.50 on the March quarter) within max(3cr, 3%).

    Needed where the EPS reconstruction cannot be built at all -- the Ind-AS-era rows for some
    filers print neither Equity Capital nor Face Value in ANY nearby quarter (COFORGE, VTL), so
    there is no share count to multiply by. This gate is stronger anyway when the other three
    quarters come from our OWN stored series, because agreeing with the audited annual then also
    proves the candidate is on the same basis as the series it is joining.

    stored: {qe: std_pat_cr} already in sf_fundamentals for this symbol.
    Returns (ok, note).
    """
    y, m = qe // 10000, (qe // 100) % 100
    # Try the Apr-Mar convention first, then calendar-year (runbook §42: the .50 annual sits on the
    # fiscal-year-END quarter -- March for Apr-Mar filers, DECEMBER for calendar-year filers).
    cands = []
    fy = y + 1 if m > 3 else y
    cands.append(
        (
            "Apr-Mar",
            fy * 10000 + 331,
            [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930, (fy - 1) * 10000 + 1231, fy * 10000 + 331],
        )
    )
    cands.append(("Jan-Dec", y * 10000 + 1231, [y * 10000 + 331, y * 10000 + 630, y * 10000 + 930, y * 10000 + 1231]))
    reasons = []
    for label, end_qe, qs in cands:
        ey, em = end_qe // 10000, (end_qe // 100) % 100
        n = 85 + (ey - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[em]
        if not 0 <= n - 85 <= 47:
            reasons.append(f"{label}:out-of-range")
            continue
        try:
            ann = fields(get(scrip, "%d.50" % n))
        except Exception as ex:
            reasons.append(f"{label}:fetch-{type(ex).__name__}")
            continue
        time.sleep(0.4)
        a_np = fnum(ann, "Net Profit", "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax")
        b, e = parse_dt(ann.get("Date Begin", "")), parse_dt(ann.get("Date End", ""))
        if a_np is None or not b or not e:
            reasons.append(f"{label}:no-annual-row")
            continue
        span = (e // 10000 * 12 + (e // 100) % 100) - (b // 10000 * 12 + (b // 100) % 100)
        if span != 11 or e != end_qe:
            reasons.append("%s:span=%d" % (label, span + 1))
            continue
        total, srcs, bad = 0.0, [], None
        for q in qs:
            if q == qe:
                total += np_mn / 10.0
                srcs.append("self")
            elif q in stored and stored[q] is not None:
                total += stored[q]
                srcs.append("stored")
            else:
                # sibling also missing from our data (common when two gaps share a fiscal year --
                # VTL Jun+Sep 2019). Take it from detres too; the annual then validates both at once
                # while the stored siblings still tie the sum to our own series.
                sq = qid(q)
                if (scrip, sq) not in cache:
                    try:
                        cache[(scrip, sq)] = fields(get(scrip, sq))
                    except Exception:
                        cache[(scrip, sq)] = {}
                    time.sleep(0.4)
                g = cache[(scrip, sq)]
                gnp = fnum(g, "Net Profit", "Net Profit (+)/ Loss (-) from Ordinary Activities after Tax")
                ge = parse_dt(g.get("Date End", ""))
                if gnp is None or ge != q:
                    bad = q
                    break
                total += gnp / 10.0
                srcs.append("detres")
        if bad:
            reasons.append("%s:sibling-%d-unavailable" % (label, bad))
            continue
        a_cr = a_np / 10.0
        err = abs(total - a_cr)
        if err > max(FY_ABS, abs(a_cr) * FY_REL):
            reasons.append(f"{label}:off {err:.2f} cr (sum={total:.2f} ann={a_cr:.2f})")
            continue
        return True, "fy-recon[{}] {:.2f} vs annual {:.2f} (delta {:.2f}, siblings {})".format(
            label, total, a_cr, err, "+".join(srcs)
        )
    return False, "; ".join(reasons)


def check(scrip, qe, cache=None, stored=None):
    """Return (value_cr, note) or (None, reason)."""
    cache = cache if cache is not None else {}
    js = get(scrip, qid(qe))
    f = fields(js)
    if not f:
        return None, "empty-response"
    b, e = parse_dt(f.get("Date Begin", "")), parse_dt(f.get("Date End", ""))
    if not b or not e:
        return None, "no-date-span"
    if e != qe:
        return None, f"date-end={e} != target"
    span = (e // 10000 * 12 + (e // 100) % 100) - (b // 10000 * 12 + (b // 100) % 100)
    if span != 2:  # Jul->Sep = 2 month-steps = a 3-month quarter
        return None, "span=%d months (not a quarter)" % (span + 1)
    np = fnum(f, "Net Profit", "Net Profit (+)/ Loss (-) from Ordinary Activities after Ta")
    if np is None:
        return None, "no-net-profit-row"
    eq = fnum(f, "Equity Capital")
    fv = fnum(f, "Face Value (in Rs)")
    eps = fnum(
        f,
        "Basic & Diluted EPS after Extraordinary items",
        "Basic & Diluted EPS before Extraordinary items",
        "Basic EPS after Extraordinary items",
        "Basic EPS before Extraordinary items",
        "Basic for discontinued & continuing operation",
        "Diluted for discontinued & continuing operation",
        "Basic for continuing operation",
        "Basic EPS",
        "Basic & Diluted EPS",
    )
    if abs(np) < 1e-9:
        return None, "zero-net-profit"
    # --- primary gate: EPS reconstruction
    eps_note = "no-eps-row"
    if eps is not None:
        shares, src = (eq / fv, "own") if (eq and fv) else ref_shares(scrip, qe, cache)
        if not (eq and fv):
            shares, refq = (shares, src)
            src = f"ref:{refq}" if shares else None
        if shares:
            recon = eps * shares
            err = abs(recon - np) / abs(np)
            if err <= EPS_TOL:
                return round(np / 10.0, 2), f"eps-recon {err * 100:.2f}% [{src}]"
            eps_note = "eps-recon %.1f%% off" % (err * 100)
        else:
            eps_note = "no-share-count-anywhere"
    # --- fallback gate: FY-consistency against the audited annual row
    ok, note = fy_gate(scrip, qe, np, stored or {}, cache)
    if ok:
        return round(np / 10.0, 2), f"{note} (eps gate: {eps_note})"
    return None, f"{eps_note}; {note}"


def main():
    args = sys.argv[1:]
    apply_it = "--apply" in args
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    fund = json.load(open(DOCS))
    by_id = json.load(open(SCRIPS, encoding="utf-8"))["by_id"]
    targets = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_std_targets.json")))
    ok, bad, journal, cache = [], [], {}, {}
    for sym, qes in sorted(targets.items()):
        if only and sym not in only:
            continue
        scrip = SCRIP_OVERRIDE.get(sym) or by_id.get(sym)
        if not scrip:
            bad.append((sym, "-", "no-bse-scrip"))
            continue
        rows = {r[0]: r for r in fund.get(sym, [])}
        for qe in qes:
            r = rows.get(qe)
            if not r:
                bad.append((sym, qe, "no-row"))
                continue
            if r[1] is not None:
                bad.append((sym, qe, "already-filled"))
                continue
            try:
                stored = {r[0]: r[1] for r in fund.get(sym, []) if r[1] is not None}
                val, note = check(str(scrip), qe, cache, stored)
            except Exception as ex:
                val, note = None, f"fetch-error:{type(ex).__name__}"
            time.sleep(0.5)
            con = r[3] if len(r) > 3 else None
            if val is None:
                bad.append((sym, qe, note))
                print("  SKIP %-11s %d  %s" % (sym, qe, note))
            else:
                same = con is not None and abs(val - con) <= 0.01
                ok.append((sym, qe, val, con, note, same))
                journal["%s|%d" % (sym, qe)] = {
                    "std": val,
                    "src": "bse-detres-§42",
                    "qid": qid(qe),
                    "gate": note,
                    "stored_con": con,
                    "applied": "2026-08-06 FILL-2020 std-2015-2020",
                }
                print(
                    "  OK   %-11s %d  std=%-10.2f (con=%-9s) %s%s"
                    % (sym, qe, val, con, note, "  <-- equals con, eyeball" if same else "")
                )
    print("\nPASS %d cells | SKIP %d" % (len(ok), len(bad)))
    if not apply_it:
        print("DRY RUN -- nothing written.")
        return
    for path in (DOCS, MIRROR):
        d = json.load(open(path))
        n = 0
        for sym, qe, val, con, note, same in ok:
            rows = {r[0]: r for r in d.get(sym, [])}
            r = rows.get(qe)
            if not r:
                continue
            while len(r) < 5:
                r.append(None)
            if r[1] is not None:
                continue
            r[1] = val
            n += 1
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("wrote %-28s %d cells" % (os.path.basename(path), n))
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    led.update(journal)
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))


if __name__ == "__main__":
    main()

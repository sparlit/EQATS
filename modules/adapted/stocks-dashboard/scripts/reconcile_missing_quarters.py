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
# -*- coding: utf-8 -*-
"""Nightly guard: a quarter that a company HAS FILED can never sit missing in sf_fundamentals.json.

Why this exists (2026-09-21/22, runbook §143): update_fundamentals.py reads ONLY NSE's
integrated-filing-results feed. On 2026-09-21 five Nifty-500 names (MCX, ABBOTINDIA, BAYERCROP,
NIVABUPA, STARHEALTH) were still on their Mar-2026 quarter seven weeks after filing Jun-2026:
the three non-insurers had filed on BSE (4/5/12 Aug) but NSE's feed carried ZERO rows for them
(symbol queries Jul→Sep empty, 600 rows of the August feed had none), and nothing cross-checked
BSE's announcement stream — the PRIMARY record (§58a). The two insurers' PDFs were image-only
and the nightly insurer reader left them "unanchored" with no visible residue. Both classes
were silent.

What it does, every nightly run:
  1. Scope = current Nifty 500 (union of the two latest rosters in scripts/indices_history.json).
  2. Target quarters = the last quarter-end that closed ≥ MIN_LAG_DAYS ago, and the one before it.
  3. For every (symbol, quarter) with NO standalone value stored, ask BSE's announcement index
     (AnnSubCategoryGetData, all categories, quarter-end+1 → today) for a results filing
     (fetch_insurers.is_result_filing: the "Financial Results" subcategory is decisive; board-
     meeting-outcome titles count; pre-meeting intimations do not).
  4. Filing found → the §58 standard read: bse_text.parse_pdf (text layer, labelled PAT row,
     unit-detected, std/con by declared basis) → DOUBLE ANCHOR: the filing's year-ago column
     must match our stored year-ago quarter (fetch_insurers.anchored: 3 % / ₹5 cr) and, when we
     hold the preceding quarter, the filing's preceding column must match it too. No text layer
     → Gemini vision (gemini_vision.read_corp_results on fetch_insurers.render_pl_pngs pages),
     same anchors. Insurers (IRDAI format) are never read here — they stay fetch_insurers /
     insurer-inbox work — but they ARE listed as pending so the gap is visible.
  5. Anchored → fill-only write to docs/sf_fundamentals.json (+ scripts/fundamentals.json mirror
     when present), announce date = BSE filing time through the 15:30 IST gate (after 15:30 →
     next weekday, exactly update_fundamentals.gated_ann), provenance appended to
     scripts/bse_result_fills.json, docs/.fund_updated touched so CI commits the fund file.
  6. Not anchored / unreadable / no vision key / insurer → scripts/_missing_quarter_pending.json
     (sym|qe → attachment, filing date, reason) and a LOUD summary line + GitHub step summary.
     A pending entry is cleared automatically the night the cell gets filled by any route.
  7. No filing yet → scripts/_missing_quarter_skips.json (re-asked after RECHECK_DAYS), so a
     quiet company is not hammered nightly.

Never guesses: a value lands only when the filing's own comparative columns reproduce what we
already hold. Exit code is always 0 (a pending list is information, not a red job).

Run:  python3 -X utf8 scripts/reconcile_missing_quarters.py [--dry] [--only MCX,ABBOTINDIA]
                                                          [--quarter 20260630] [--no-vision]
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import argparse
import datetime
import json
import os
import re
import sys
import time

import bse_headers as BH  # §181 BSE headers

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fund_dup_guard  # ONE row per (sym, quarter-end)

try:
    import bse_text  # §58 text-layer reader (labelled PAT row, unit-aware)
except ModuleNotFoundError as _e:  # bse_text imports bse_vision -> numpy/cv2, absent from the CI image;
    import types  # parse_pdf/rows_by_y/data_after_label/detect_unit need neither

    sys.modules["bse_vision"] = types.ModuleType("bse_vision")
    import bse_text
import fetch_insurers as FI  # is_result_filing / anchored / render_pl_pngs / INSURERS

try:
    import gemini_vision as GV  # read_corp_results (free tier; needs GEMINI_API_KEY)
except Exception:
    GV = None

DOCS_FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SRC_FUND = os.path.join(HERE, "fundamentals.json")
MARK = os.path.join(ROOT, "docs", ".fund_updated")
ROSTERS = os.path.join(HERE, "indices_history.json")
SCRIPS = os.path.join(HERE, "bse_scrips.json")
QR = os.path.join(ROOT, "docs", "quarterly_results.json")  # company names for the vision identity guard
LEDGER = os.path.join(HERE, "bse_result_fills.json")
PENDING = os.path.join(HERE, "_missing_quarter_pending.json")
SKIPS = os.path.join(HERE, "_missing_quarter_skips.json")
MANUAL = os.path.join(
    HERE, "manual_result_reads.json"
)  # human/vision reads: [{sym,qe,att,filed,std:[cur,prev,yago],con:[...]|null,by,note}] — applied ONLY if they anchor
PDFCACHE = os.path.join(HERE, "_revgap_pdfcache")  # shared with backfill_revop_gaps: each attachment downloaded once

MIN_LAG_DAYS = 10  # nobody files inside the first 10 days after a quarter-end
RECHECK_DAYS = 3  # re-ask BSE for a still-unfiled name every 3 days
MAX_FETCH = 400  # BSE calls per run (rate-limit courtesy, §55a); the rest wait a night


# ---------------------------------------------------------------- small utils
def today_ist():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).date()


def yyyymmdd(d):
    return int(d.strftime("%Y%m%d"))


def quarter_ends_before(d, n=2):
    """The last n quarter-ends (YYYYMMDD ints) that closed at least MIN_LAG_DAYS before d."""
    out = []
    y, _m = d.year, d.month
    cands = []
    for yy in (y - 1, y):
        for md in (331, 630, 930, 1231):
            cands.append(yy * 10000 + md)
    for qe in sorted(cands, reverse=True):
        qd = datetime.date(qe // 10000, qe // 100 % 100, qe % 100)
        if (d - qd).days >= MIN_LAG_DAYS:
            out.append(qe)
        if len(out) == n:
            break
    return out


def year_ago(qe):
    return qe - 10000


def prev_q(qe):
    return bse_text.prev_q(qe)


def gated_ann(dt_iso):
    """BSE DT_TM '2026-08-04T20:02:14.153' → YYYYMMDD int = the broadcast's CALENDAR DAY (20260804).
    Midnight visibility rule (user decision 2026-09-23, runbook §149): a filing counts for the day it
    was broadcast, whatever the time — the user buys at the next session's open. The §12 15:30 gate
    (after-close → next weekday) is retired; name kept, guard_visibility_rule.py asserts this."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", dt_iso or "")
    if not m:
        return None
    return yyyymmdd(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))


def load_json(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), separators=(",", ":"))
    os.replace(tmp, p)


# ---------------------------------------------------------------- BSE access (honest urllib, runbook §181)
def _http(url, binary=False):
    """One BSE GET with the one BSE header set (bse_headers.HEADERS): our own User-Agent, no browser
    impersonation (the curl_cffi impersonate="chrome" first leg was dropped 2026-09-26 -- urllib +
    BH.HEADERS measured 200 on the API, attachment and /XBRL1/ hosts)."""
    import urllib.request

    try:
        body = urllib.request.urlopen(urllib.request.Request(url, headers=BH.HEADERS), timeout=90).read()
    except Exception as e:
        msg = f"bse fetch failed: {str(e)[:120]}"
        raise RuntimeError(msg)
    return body if binary else body.decode("utf-8", "replace")


def bse_result_filings(code, lo, hi):
    """[(DT_TM iso, attachment, NEWSSUB)] result filings for scrip `code` between lo..hi (YYYYMMDD)."""
    out = []
    for page in (1, 2, 3):
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
            "&strPrevDate=%s&strScrip=%s&strSearch=P&strToDate=%s&strType=C&subcategory=-1" % (page, lo, code, hi)
        )
        rows = json.loads(_http(url)).get("Table") or []
        for r in rows:
            if FI.is_result_filing(r) and r.get("ATTACHMENTNAME"):
                out.append((r.get("DT_TM") or r.get("NEWS_DT") or "", r["ATTACHMENTNAME"], r.get("NEWSSUB") or ""))
        if len(rows) < 50:
            break
        time.sleep(0.4)
    return sorted(set(out))  # oldest first: the original filing before any revision


def fetch_pdf(att):
    os.makedirs(PDFCACHE, exist_ok=True)
    p = os.path.join(PDFCACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", att)[-120:])
    if os.path.exists(p):
        b = open(p, "rb").read()
        if b[:4] == b"%PDF":
            return b
    for base in ("AttachLive", "AttachHis"):
        try:
            b = _http(f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", binary=True)
            if b[:4] == b"%PDF":
                open(p, "wb").write(b)
                return b
        except Exception:
            continue
    try:
        b = _http(f"https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname={att}", binary=True)
        if b[:4] == b"%PDF":
            open(p, "wb").write(b)
            return b
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- reads
def stored(fund, sym, qe, basis):
    row = next((r for r in fund.get(sym, []) if r[0] == qe), None)
    if not row:
        return None
    return row[1] if basis == "std" else row[3]


def anchor_ok(read_vals, fund, sym, qe, basis):
    """read_vals = [cur, prev, yago] (crore). Year-ago MUST anchor; preceding must anchor when we hold it.
    Returns (ok, detail)."""
    if not read_vals or read_vals[0] is None:
        return False, "no current value"
    ya_s, pv_s = stored(fund, sym, year_ago(qe), basis), stored(fund, sym, prev_q(qe), basis)
    if ya_s is None:
        return False, f"no stored year-ago {basis} to anchor"
    if len(read_vals) < 3 or read_vals[2] is None or not FI.anchored(read_vals[2], ya_s):
        return (
            False,
            f"year-ago {basis} mismatch: filing {read_vals[2] if len(read_vals) > 2 else None} vs stored {ya_s}",
        )
    if pv_s is not None and read_vals[1] is not None and not FI.anchored(read_vals[1], pv_s):
        return False, f"preceding-quarter {basis} mismatch: filing {read_vals[1]} vs stored {pv_s}"
    return True, "yago {}≈{}{}".format(
        read_vals[2], ya_s, (f", prev {read_vals[1]}≈{pv_s}") if pv_s is not None else ""
    )


PAT_LABEL = re.compile(
    r"^\s*(\d+[\.\)]?\s*)?(net\s*)?profit\s*(/\s*\(?loss\)?)?\s*(\(after\s*tax\)\s*)?"
    r"(for\s*the\s*(period|quarter|year)|after\s*tax)",
    re.IGNORECASE,
)
PAT_EXCL = re.compile(
    r"before\s*tax|comprehensive|per\s*share|attributable\s*to\s*non|non[-\s]*controlling|share\s*of|"
    r"discontinu|exceptional|margin|segment|associate",
    re.IGNORECASE,
)


def tolerant_rows(pdf):
    """§58 labelled-row read for filings bse_text misses (e.g. 'Profit for the period/year' without 'net').
    Returns (std[cur,prev,yago], con[...]) in crore, or (None, None). Basis from the page's declared
    context; the FIRST three numbers after the label = current / preceding / year-ago quarter
    (SEBI column order) — the caller's double anchor rejects any other layout."""
    import fitz

    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return None, None
    full = " ".join(doc[p].get_text() for p in range(min(len(doc), 12))).lower()
    div = bse_text.detect_unit(full) or 1.0
    std_v = con_v = None
    con_ctx = False
    distinct = []
    for pi in range(min(len(doc), 24)):
        pg = doc[pi]
        low = pg.get_text().lower()
        if re.search(r"consolidated\s+(statement|financial|results|un)", low):
            con_ctx = True
        elif re.search(r"standalone\s+(statement|financial|results|un)", low):
            con_ctx = False
        for cells in bse_text.rows_by_y(pg).values():
            txt = " ".join(w for _, w in cells)
            if PAT_LABEL.search(txt) and not PAT_EXCL.search(txt):
                nums = bse_text.data_after_label(cells)
                if len(nums) < 3:
                    continue
                vals = [round(v / div, 2) for v in nums[:3]]
                if vals not in distinct:
                    distinct.append(vals)
                if con_ctx and con_v is None:
                    con_v = vals
                elif not con_ctx and std_v is None:
                    std_v = vals
    return std_v, con_v, len(distinct)


def text_read(pdf, ann_yyyymmdd):
    """(std[cur,prev,yago], con[...], qe_month) or None when no PAT row could be read from text."""
    res = None
    try:
        res = bse_text.parse_pdf(pdf, ann_yyyymmdd)  # (std, con, qe_txt) | None (scanned)
    except Exception as e:
        print(f"   bse_text error: {str(e)[:100]}")
    std_v, con_v, qe_txt = res or (None, None, None)
    n_rows = None
    if not std_v or std_v[0] is None:
        s2, c2, n_rows = tolerant_rows(pdf)
        if s2:
            std_v = s2
        if not con_v and c2:
            con_v = c2
    # Standalone-only filer: the cover/auditor page may still say "consolidated" (…"no consolidated
    # financial statements are prepared"…), which flips the sticky basis context, so the filing's
    # ONLY PAT row lands under con. Reg 33 makes the standalone statement mandatory and consolidated
    # optional, so a filing with exactly ONE distinct PAT row is standalone (the anchors still gate it).
    if (not std_v or std_v[0] is None) and con_v and n_rows == 1:
        std_v, con_v = con_v, None
    if not std_v or std_v[0] is None:
        return None
    return std_v, con_v, (qe_txt // 100 if qe_txt else None)  # month granularity: bse_text stamps day 31


def vision_read(pdf, sym, name, qe):
    if GV is None or not os.environ.get("GEMINI_API_KEY"):
        return None, "no vision key"
    if hasattr(GV, "quota_dead") and GV.quota_dead():
        return None, "vision quota exhausted"
    ident = [t for t in re.split(r"[^A-Za-z]+", (name or sym).upper()) if len(t) >= 3][:2] or [sym]
    pngs = FI.render_pl_pngs(pdf, ident)
    if not pngs:
        return None, "could not render P&L pages"

    def lab(q):
        return "quarter ended {}".format(datetime.date(q // 10000, q // 100 % 100, q % 100).strftime("%d %b %Y"))

    v = GV.read_corp_results(name or sym, lab(qe), lab(prev_q(qe)), lab(year_ago(qe)), pngs)
    if not v or not v.get("ok") or not v.get("company_matches"):
        return None, "vision: no confident read"

    def tri(b):
        return [(v.get(k) or {}).get(b) for k in ("cur", "prec", "yago")]

    return (tri("std"), tri("con")), "gemini"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--quarter", type=int, default=0)
    ap.add_argument("--no-vision", action="store_true")
    a = ap.parse_args()

    today = today_ist()
    tstr = yyyymmdd(today)
    fund = load_json(DOCS_FUND, {})
    if not fund:
        print(f"FATAL: {DOCS_FUND} unreadable")
        return 0
    src = load_json(SRC_FUND, None)
    scrips = (load_json(SCRIPS, {}) or {}).get("by_id", {})
    names = {k: (v.get("n") or "") for k, v in ((load_json(QR, {}) or {}).get("co") or {}).items()}
    hist = (load_json(ROSTERS, {}) or {}).get("Nifty 500") or []
    roster = set()
    for e in hist[-2:]:
        roster |= set(e.get("symbols") or [])
    if a.only:
        roster = {x.strip().upper() for x in a.only.split(",") if x.strip()}
    quarters = [a.quarter] if a.quarter else quarter_ends_before(today, 2)
    ledger = load_json(LEDGER, [])
    pending = load_json(PENDING, {})
    skips = load_json(SKIPS, {})
    print(
        "reconcile_missing_quarters %s: roster %d names, quarters %s%s"
        % (today, len(roster), quarters, " (DRY)" if a.dry else "")
    )

    # a pending cell that got filled by any other route is cleared here
    for k in list(pending):
        s, q = k.split("|")
        q = int(q)
        if stored(fund, s, q, "std") is not None:
            del pending[k]

    filled = []
    newly_pending = []
    unfiled = 0
    asked = 0
    # ---- insurer-inbox self-heal: apply_insurer_inbox marks an entry "applied" BEFORE the job's commit
    # step; if a later step fails, the values are lost while the inbox believes they were filed (twice
    # on 2026-09-22). Any applied entry whose cell is still EMPTY in the store gets its flag cleared so
    # the next inbox pass files it again. Read-only when nothing needs healing; skipped offline.
    if not a.dry:
        try:
            import apply_insurer_inbox as AI

            box = AI.rpc("sw_kv_get", {"k": "INSURER_INBOX"})
            healed = 0
            if isinstance(box, list):
                for e in box:
                    if (
                        isinstance(e, dict)
                        and e.get("applied")
                        and not e.get("rejected")
                        and stored(fund, e.get("sym"), int(e.get("qe") or 0), "con") is None
                        and stored(fund, e.get("sym"), int(e.get("qe") or 0), "std") is None
                    ):
                        e.pop("applied", None)
                        e["note"] = (
                            (e.get("note") or "")
                            + f" | applied-flag cleared by reconcile_missing_quarters {today}: cell still empty in the store"
                        )
                        healed += 1
                if healed:
                    ok = AI.rpc("sw_kv_set", {"secret": AI.WRITE, "k": "INSURER_INBOX", "payload": box})
                    print("insurer-inbox self-heal: %d entry(ies) re-opened (kv write %s)" % (healed, ok))
        except Exception as e:
            print(f"insurer-inbox self-heal skipped: {str(e)[:80]}")
    # ---- manual anchored reads (scripts/manual_result_reads.json): a human read of an image-only filing.
    # Same gate as an automated read: year-ago (and preceding, when held) must reproduce the store.
    manual = load_json(MANUAL, [])
    # The commit step's list union can carry two copies of one read (the run's "applied" copy and the
    # committed un-applied one, 2026-09-22 02:17: 2 -> 4). Dedupe by (sym, qe): a copy with a status wins.
    _seen = {}
    for m in manual:
        if not isinstance(m, dict):
            continue
        k = (m.get("sym"), int(m.get("qe") or 0))
        cur = _seen.get(k)
        if cur is None or (not (cur.get("applied") or cur.get("rejected")) and (m.get("applied") or m.get("rejected"))):
            _seen[k] = m
    manual = list(_seen.values())
    for m in manual:
        if not isinstance(m, dict) or m.get("applied") or m.get("rejected"):
            continue
        sym, qe = m.get("sym"), int(m.get("qe") or 0)
        if a.only and sym not in roster:
            continue
        if stored(fund, sym, qe, "std") is not None:
            m["rejected"] = "already filled"
            continue
        std_v, con_v = m.get("std"), m.get("con")
        ok_s, det_s = anchor_ok(std_v, fund, sym, qe, "std")
        if not ok_s:
            m["rejected"] = det_s
            print("  MANUAL REJECT %s %d: %s" % (sym, qe, det_s))
            continue
        ok_c, det_c = anchor_ok(con_v, fund, sym, qe, "con") if con_v else (False, "no consolidated read")
        ann = gated_ann(m.get("filed") or "")
        if not ann:
            m["rejected"] = "bad filed timestamp"
            continue
        rows = fund.setdefault(sym, [])
        row = next((r for r in rows if r[0] == qe), None)
        if row is None:
            row = [qe, None, None, None, None]
            rows.append(row)
            rows.sort(key=lambda r: r[0])
        row[1], row[2] = round(std_v[0], 2), ann
        if ok_c:
            row[3], row[4] = round(con_v[0], 2), ann
        if src is not None:
            srows = src.setdefault(sym, [])
            srow = next((r for r in srows if r[0] == qe), None)
            if srow is None:
                srow = [qe, None, None, None, None]
                srows.append(srow)
                srows.sort(key=lambda r: r[0])
            if srow[1] is None:
                srow[1], srow[2] = row[1], row[2]
            if ok_c and srow[3] is None:
                srow[3], srow[4] = row[3], row[4]
        entry = {
            "sym": sym,
            "qe": qe,
            "std": row[1],
            "con": row[3] if ok_c else None,
            "ann": ann,
            "att": m.get("att"),
            "filed": (m.get("filed") or "")[:19],
            "method": "manual-anchored:" + str(m.get("by") or "?"),
            "read": {"std": std_v, "con": con_v},
            "anchor": {"std": det_s, "con": det_c},
            "note": m.get("note"),
            "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        }
        ledger.append(entry)
        filled.append(entry)
        pending.pop("%s|%d" % (sym, qe), None)
        m["applied"] = str(today)
        print(
            "  FILLED %-11s %d std=%s con=%s ann=%s via %s [%s | %s]"
            % (sym, qe, row[1], entry["con"], ann, entry["method"], det_s, det_c)
        )
    for qe in quarters:
        lo = yyyymmdd(datetime.date(qe // 10000, qe // 100 % 100, qe % 100) + datetime.timedelta(days=1))
        for sym in sorted(roster):
            if stored(fund, sym, qe, "std") is not None:
                continue
            key = "%s|%d" % (sym, qe)
            sk = skips.get(key)
            if sk and (today - datetime.date.fromisoformat(sk["checked"])).days < RECHECK_DAYS:
                unfiled += 1
                continue
            code = scrips.get(sym)
            if not code:
                pending[key] = {"reason": "no BSE scrip code (bse_scrips.json)", "ts": str(today)}
                newly_pending.append((sym, qe, pending[key]["reason"]))
                continue
            if asked >= MAX_FETCH:
                break
            asked += 1
            try:
                filings = bse_result_filings(code, lo, tstr)
            except Exception as e:
                print("  %s %d: BSE index error %s" % (sym, qe, str(e)[:80]))
                continue
            time.sleep(0.5)
            if not filings:
                skips[key] = {"checked": str(today)}
                unfiled += 1
                continue
            skips.pop(key, None)
            if sym in FI.INSURERS:
                pending[key] = {
                    "reason": "insurer (IRDAI format) — fetch_insurers nightly / insurer inbox",
                    "att": filings[0][1],
                    "filed": filings[0][0][:16],
                    "ts": str(today),
                }
                newly_pending.append((sym, qe, pending[key]["reason"]))
                continue
            done = False
            last_reason = "no result filing parsed"
            for dt_iso, att, sub in filings:
                pdf = fetch_pdf(att)
                if not pdf:
                    last_reason = f"attachment {att} not downloadable"
                    continue
                ann = gated_ann(dt_iso)
                res = text_read(pdf, ann)
                method = "text"
                if res is None:  # no readable PAT row in the text layer
                    if a.no_vision:
                        last_reason = "no readable text PAT row (vision disabled)"
                        continue
                    vr, why = vision_read(pdf, sym, names.get(sym), qe)
                    if vr is None:
                        last_reason = f"no readable text PAT row; {why}"
                        continue
                    res = (vr[0], vr[1], qe // 100)
                    method = "gemini"
                std_v, con_v, qe_txt = res
                if qe_txt and qe_txt != qe // 100:
                    last_reason = f"filing is for {qe_txt}, not {qe // 100} ({sub[:50]})"
                    continue
                ok_s, det_s = anchor_ok(std_v, fund, sym, qe, "std")
                if not ok_s:
                    last_reason = det_s
                    continue
                ok_c, det_c = anchor_ok(con_v, fund, sym, qe, "con") if con_v else (False, "no consolidated in filing")
                rows = fund.setdefault(sym, [])
                row = next((r for r in rows if r[0] == qe), None)
                if row is None:
                    row = [qe, None, None, None, None]
                    rows.append(row)
                    rows.sort(key=lambda r: r[0])
                if row[1] is None:
                    row[1], row[2] = round(std_v[0], 2), ann
                if ok_c and row[3] is None:
                    row[3], row[4] = round(con_v[0], 2), ann
                if src is not None:
                    srows = src.setdefault(sym, [])
                    srow = next((r for r in srows if r[0] == qe), None)
                    if srow is None:
                        srow = [qe, None, None, None, None]
                        srows.append(srow)
                        srows.sort(key=lambda r: r[0])
                    if srow[1] is None:
                        srow[1], srow[2] = row[1], row[2]
                    if ok_c and srow[3] is None:
                        srow[3], srow[4] = row[3], row[4]
                entry = {
                    "sym": sym,
                    "qe": qe,
                    "std": row[1],
                    "con": row[3] if ok_c else None,
                    "ann": ann,
                    "att": att,
                    "filed": dt_iso[:19],
                    "method": method,
                    "read": {"std": std_v, "con": con_v},
                    "anchor": {"std": det_s, "con": det_c},
                    "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
                }
                ledger.append(entry)
                filled.append(entry)
                pending.pop(key, None)
                print(
                    "  FILLED %-11s %d std=%s con=%s ann=%s via %s [%s | %s]"
                    % (sym, qe, row[1], entry["con"], ann, method, det_s, det_c)
                )
                done = True
                break
            if not done:
                pending[key] = {
                    "reason": last_reason,
                    "att": filings[0][1],
                    "filed": filings[0][0][:16],
                    "ts": str(today),
                }
                newly_pending.append((sym, qe, last_reason))
                print("  PENDING %-10s %d: %s" % (sym, qe, last_reason))

    print(
        "\nsummary: %d filled, %d pending (%d new this run), %d names not yet filed, %d BSE index calls"
        % (len(filled), len(pending), len(newly_pending), unfiled, asked)
    )
    for k, v in sorted(pending.items()):
        print("   pending %-22s %s" % (k, v.get("reason")))
    if not a.dry:
        if filled:
            save_json(DOCS_FUND, fund)
            if src is not None:
                save_json(SRC_FUND, src)
            open(MARK, "w").write(today.isoformat())
            save_json(LEDGER, ledger)
        save_json(PENDING, pending)
        save_json(SKIPS, skips)
        if manual:
            save_json(MANUAL, manual)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write(
                "### Missing-quarter reconcile (BSE primary record)\n%d filled · %d pending · %d not yet filed\n"
                % (len(filled), len(pending), unfiled)
            )
            for e in filled:
                fh.write(
                    "- ✅ %s %d std %s con %s ann %s (%s)\n"
                    % (e["sym"], e["qe"], e["std"], e["con"], e["ann"], e["method"])
                )
            for k, v in sorted(pending.items()):
                fh.write("- ⏳ {} — {}\n".format(k, v.get("reason")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

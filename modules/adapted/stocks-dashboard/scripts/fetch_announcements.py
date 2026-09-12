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
"""Fetch NSE corporate announcements (equities, ALL symbols) for a rolling window and write
docs/announcements.json for the Announcements page. Reuses build_fundamentals' CI-proven NSE
session (plain urllib + Chrome UA + cookie warmup — same as the daily fundamentals cron).

- Window: last WINDOW_DAYS days, fetched in CHUNK_DAYS chunks (small chunks keep each
  response modest and let one bad chunk fail without losing the run).
- Self-healing: merges with the existing file (a failed chunk today keeps yesterday's rows),
  then trims to the window. Refuses to overwrite good data if the result looks broken (<MIN_ROWS).
- Output schema (compact arrays):
  {"updated","from","to","rows":[[symbol, company, "YYYY-MM-DD HH:MM:SS", category, caption, file], ...]}
  `file` is the attachment with the common "https://nsearchives.nseindia.com/corporate/" prefix
  stripped (the page re-adds it); other/absolute URLs are kept as-is.

Run: python -X utf8 scripts/fetch_announcements.py
"""
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "announcements.json")
WINDOW_DAYS = 31
CHUNK_DAYS = 7
INDICES = ("equities", "sme")  # mainboard + SME/Emerge — SME board carries thin-name result filings
CHUNK_SME = 3  # SME board: finer chunks — NSE errors a 7-day SME window in peak season
MIN_ROWS = 200  # a 31-day window always has thousands; fewer = broken fetch, keep old file
CAPTION_MAX = 500
PDF_PREFIX = "https://nsearchives.nseindia.com/corporate/"
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


def ddmmyyyy(d):
    return "%02d-%02d-%04d" % (d.day, d.month, d.year)


def parse_dt(rec):
    """an_dt '11-Jul-2026 18:07:44' or sort_date '2026-07-11 18:07:44' -> ISO 'YYYY-MM-DD HH:MM:SS'."""
    s = str(rec.get("sort_date") or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T]?(\d{2}:\d{2}(:\d{2})?)?", s)
    if m:
        return m.group(1) + " " + ((m.group(2) or "00:00") + ":00")[:8]
    s = str(rec.get("an_dt") or "")
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})\s*(\d{2}:\d{2}(:\d{2})?)?", s)
    if not m:
        return None
    mo = MON.get(m.group(2).lower())
    if not mo:
        return None
    return "%s-%02d-%s %s" % (m.group(3), mo, m.group(1), ((m.group(4) or "00:00") + ":00")[:8])


def key_of(r):
    return "|".join((r[0], r[2], r[3], r[5]))


def main():
    today = datetime.date.today()
    start = today - datetime.timedelta(days=WINDOW_DAYS - 1)
    hdr = {
        "User-Agent": B.UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    }
    rows, errs = {}, 0
    # NSE files mainboard (index=equities) and SME/Emerge (index=sme) announcements on SEPARATE
    # boards — query BOTH or every SME result filing (VINEETLAB, MONOPHARMA, VIGOR, …) is invisible
    # to us and the Trendlyne count reads permanently higher. See DATA_RUNBOOK §14/§31.
    # ⚠️ NSE aggressively throttles the SME endpoint when it's hit right after equities in the SAME
    # session — it returns a non-JSON body ("Expecting value…") that decodes to nothing. Alternating
    # equities↔sme per chunk starved the sme board (0 recs for the exact week SME results filed).
    # So run each board as its OWN pass with its OWN fresh cookie-warmed session, retry throttled
    # chunks, and lean on the yesterday-file merge below to preserve any board that still comes back
    # short on a given run (intermittent throttle self-heals across runs).
    for idx in INDICES:
        jar = B.nse_jar()  # fresh warmed session per board
        step = CHUNK_SME if idx == "sme" else CHUNK_DAYS  # SME 3-day (a 7-day peak-season window errors)
        d = start
        while d <= today:
            e = min(d + datetime.timedelta(days=step - 1), today)
            url = (
                f"https://www.nseindia.com/api/corporate-announcements?index={idx}"
                f"&from_date={ddmmyyyy(d)}&to_date={ddmmyyyy(e)}"
            )
            # Fail FAST on the flaky SME board (short timeout, 2 tries) so a few hanging windows can't
            # blow the workflow timeout — the preserve-all-rows merge below means whatever SME NSE
            # refuses this run is captured on a later scheduled run and kept. Equities is reliable, so
            # it gets the full timeout + tries.
            tmo, tries = (25, 2) if idx == "sme" else (90, 3)
            j = []
            for attempt in range(tries):
                if attempt:
                    time.sleep(2.5)
                try:
                    j = json.loads(B._get(url, headers=hdr, jar=jar, timeout=tmo))
                except Exception as ex:
                    print("ERR chunk %s..%s [%s] try%d: %s" % (d, e, idx, attempt + 1, ex))
                    errs += 1
                    j = []
                if isinstance(j, list) and j:
                    break  # got rows — good
            n = 0
            for rec in j if isinstance(j, list) else []:
                sym = str(rec.get("symbol") or "").strip().upper()
                dt = parse_dt(rec)
                if not sym or not dt:
                    continue
                cat = re.sub(r"\s+", " ", str(rec.get("desc") or "")).strip() or "Others"
                cap = re.sub(r"\s+", " ", str(rec.get("attchmntText") or "")).strip()
                if len(cap) > CAPTION_MAX:
                    cap = cap[: CAPTION_MAX - 1].rstrip() + "…"
                f = str(rec.get("attchmntFile") or "").strip()
                f = f.removeprefix(PDF_PREFIX)
                co = re.sub(r"\s+", " ", str(rec.get("sm_name") or "")).strip()
                r = [sym, co, dt, cat, cap, f]
                rows[key_of(r)] = r
                n += 1
            print("chunk %s..%s [%s] -> %d recs" % (d, e, idx, n))
            d = e + datetime.timedelta(days=1)
            time.sleep(0.6)  # gentle pace within a board

    fresh = len(rows)
    # merge yesterday's file so a partially-failed fetch never loses rows
    if os.path.exists(OUT):
        try:
            for r in json.load(open(OUT, encoding="utf-8")).get("rows", []):
                if isinstance(r, list) and len(r) == 6:
                    rows.setdefault(key_of(r), r)
        except Exception as ex:
            print("WARN old file unreadable:", ex)

    lo = start.isoformat()
    allrows = [r for r in rows.values() if r[2][:10] >= lo]
    allrows.sort(key=lambda r: (r[2], r[0]), reverse=True)
    if len(allrows) < MIN_ROWS:
        print("ABORT: only %d rows (fresh %d, errs %d) — keeping existing file" % (len(allrows), fresh, errs))
        sys.exit(1)

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "from": lo, "to": today.isoformat(), "rows": allrows}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    cats = {}
    for r in allrows:
        cats[r[3]] = cats.get(r[3], 0) + 1
    print(
        "WROTE %s: %d rows (%d fresh), %d categories, %.1f MB"
        % (os.path.normpath(OUT), len(allrows), fresh, len(cats), os.path.getsize(OUT) / 1e6)
    )
    for c, n in sorted(cats.items(), key=lambda kv: -kv[1])[:40]:
        print("  %5d  %s" % (n, c))

    write_results_feed(allrows)


# --- Results feed (docs/results_feed.json) — the tiny slice the Quarterly Results page polls ---
RESULT_CAP_RE = re.compile(
    r"financial\s+results?\s+for\s+the\s+(?:period|quarter|year)|"
    r"submitted.{0,40}financial\s+results?",
    re.IGNORECASE,
)
RESULT_CAT_RE = re.compile(r"^financial\s+result", re.IGNORECASE)
# ⚠️ A results filing in Jul/Aug/Sep is often a LATE March (Q4/annual) result, not the current June
# quarter — so read the reporting period per filing and ANCHOR on an "ended" clause (never assume the
# current season). Snap to a quarter-end month; 0 (no badge) when the period isn't stated.
_DAY_LAST = {3: 31, 6: 30, 9: 30, 12: 31}
# Anchors tried IN ORDER; each yields a short segment that must contain the period date. Everything
# stays anchored — a bare date in a caption is as likely the board-MEETING date as the period, and a
# June-30 meeting approving March results would mis-file as the June quarter. 2026-07-21 additions
# ("Q.E.", "as on", "for the … year", "For <Month D, YYYY>") come from the audit of real qe=0 captions;
# they only fire where the old parser returned 0, so no previously-parsed row can change quarter.
_ANCHOR_RES = [
    re.compile(r"end(?:ed|ing)\s+(?:on\s+)?(.{0,30}?\d{4})", re.IGNORECASE),  # "quarter ended March 31, 2026"
    re.compile(
        r"q\.?\s*e\.?[\s:.\-]*(.{0,20}?\d{4})", re.IGNORECASE
    ),  # "Q.E.31.03.2026" (no \b: real captions glue it — "theQ.E.31.03.2026")
    re.compile(r"\bas\s+(?:on|at)[\s:.\-]*(.{0,20}?\d{4})", re.IGNORECASE),  # "AS ON 30.06.2026"
    re.compile(
        r"for\s+the\s+(?:quarter\s+and\s+)?(?:financial\s+)?year\s+(.{0,25}?\d{4})", re.IGNORECASE
    ),  # "for the quarter and financial year March 31, 2026"
    re.compile(
        r"\bfor\s+((?:[A-Za-z]{3,9}\s+\d{1,2},?|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}[,\s.\-]*|[A-Za-z]{3,9}[,\s.\-]*)\s*\d{4})",
        re.IGNORECASE,
    ),  # "For March 31, 2026" / "for 30th June-2026" / "for September 2025" (month+year can't be a meeting date)
]
_DMY_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?[\s,]+([A-Za-z]{3,9})[,\s.\-]+(\d{4})", re.IGNORECASE)
_MDY_RE = re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)
_NUM_RE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})")
_MY_RE = re.compile(r"([A-Za-z]{3,9})[,\s]+(\d{4})", re.IGNORECASE)  # "March, 2026" (day unstated)
# "F.Y. 2025-26" / "FY 2025-2026" / "financial year 2025-26" -> March of the END year. Unambiguous
# (a fiscal-year range is never a meeting date), so this one needs no anchor.
_FY_RE = re.compile(
    r"(?:\bf\.?\s*y\.?|financial\s+year)\s*[:.\-]?\s*(20\d{2})\s*[-–—/]\s*(?:20)?(\d{2})\b", re.IGNORECASE
)


def _qe_mk(mo, y):
    return (y * 10000 + mo * 100 + _DAY_LAST[mo]) if mo in _DAY_LAST else 0


def qe_sane(qe, filed):
    """A result can't be declared on/before its own quarter-end, for ANY quarter — an impossible
    (qe, filing-date) pair means the caption (or a bad ledger entry) lied about the period. Demote
    to 0 so the row renders as period-unknown (vision resolves it) instead of under a quarter it
    predates. `filed` = 'YYYY-MM-DD'. Shared by both feed writers (fetch_bse_results imports it)."""
    if not qe:
        return 0
    return qe if str(filed) > "%04d-%02d-%02d" % (qe // 10000, qe // 100 % 100, qe % 100) else 0


def parse_qe(*texts):
    h = " ".join(str(t or "") for t in texts)
    for rx in _ANCHOR_RES:
        for mm in rx.finditer(h):
            seg = mm.group(1)
            m = _DMY_RE.search(seg)
            if m:
                qe = _qe_mk(MON.get(m.group(2).lower()[:3], 0), int(m.group(3)))
                if qe:
                    return qe
            m = _MDY_RE.search(seg)
            if m:
                qe = _qe_mk(MON.get(m.group(1).lower()[:3], 0), int(m.group(3)))
                if qe:
                    return qe
            m = _NUM_RE.search(seg)
            if m:
                qe = _qe_mk(int(m.group(2)), int(m.group(3)))
                if qe:
                    return qe
            m = _MY_RE.search(seg)  # month + year, no day: snap to that quarter-end
            if m:
                qe = _qe_mk(MON.get(m.group(1).lower()[:3], 0), int(m.group(2)))
                if qe:
                    return qe
    m = _FY_RE.search(h)
    if m and int(m.group(2)) == (int(m.group(1)) + 1) % 100:
        return (2000 + int(m.group(2))) * 10000 + 331
    return 0


def write_results_feed(allrows):
    """Slice results-filing announcements into a small standalone JSON (same schema, + parsed
    quarter-end when the caption states it). Kept tiny so the page can poll it cheaply.

    ⚠️ This rebuilds the NSE rows from scratch, so it must PRESERVE the existing feed rows — else any
    run where a fetch comes back short silently drops companies. Two flaky sources make this essential:
    the BSE fetch (added AFTERWARD by fetch_bse_results.py) and the NSE **SME** board, which NSE throttles
    to an empty reply at random (dropping SME result filers for a whole window). So we keep ALL prior rows;
    a fresh row for the same (symbol, date) OVERRIDES the preserved one below, so quarter corrections still
    win — preservation only backfills what THIS run's fetch missed. The rolling-31d trim stops accretion."""
    outp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "results_feed.json")
    try:
        prev = json.load(open(outp, encoding="utf-8")).get("rows", [])
    except Exception:
        prev = []
    kept_prev = [r for r in prev if isinstance(r, list) and len(r) >= 6]
    n_bse = sum(1 for r in kept_prev if "bseindia.com" in str(r[5]))
    # Quarter corrections: NSE sometimes captions a late Q4/annual filing as the current quarter. The
    # daily vision-prep reads the filing PDF's real period and records "SYM|YYYY-MM-DD" -> real qe here.
    try:
        qfix = json.load(open(os.path.join(os.path.dirname(outp), "feed_qe_fix.json"), encoding="utf-8"))
    except Exception:
        qfix = {}

    feed = []
    for r in allrows:
        cat, cap = r[3], r[4] or ""
        if not (RESULT_CAT_RE.search(cat) or (cat == "Outcome of Board Meeting" and RESULT_CAP_RE.search(cap))):
            continue
        qe = qe_sane(qfix.get(f"{r[0]}|{str(r[2])[:10]}") or parse_qe(cap), str(r[2])[:10])
        feed.append([r[0], r[1], r[2], qe, (cap[:220] + "…") if len(cap) > 221 else cap, r[5]])
    have = {(r[0], r[2][:10]) for r in feed}
    for r in kept_prev:  # backfill any (sym,date) THIS run's fetch missed
        if (r[0], r[2][:10]) in have:
            continue
        # apply the quarter-fix ledger to CARRIED rows too — a straggler older than the fetch window
        # (KGVL-class, filed weeks ago) otherwise rides here verbatim and its recorded fix NEVER lands
        fx = qfix.get(f"{r[0]}|{r[2][:10]}")
        if fx:
            r = [r[0], r[1], r[2], qe_sane(fx, r[2][:10]), r[4], r[5]]
        feed.append(r)
        have.add((r[0], r[2][:10]))
    # trim to a rolling 31-day window (matches fetch_bse_results) so preserved BSE rows don't accrete
    cut = (datetime.date.today() - datetime.timedelta(days=31)).isoformat()
    feed = [r for r in feed if r[2][:10] >= cut]
    feed.sort(key=lambda r: (r[2], r[0]), reverse=True)
    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    json.dump(
        {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "rows": feed},
        open(outp, "w", encoding="utf-8"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    print(
        "WROTE %s: %d results-feed rows (%d preserved: %d BSE)"
        % (os.path.normpath(outp), len(feed), len(kept_prev), n_bse)
    )


if __name__ == "__main__":
    main()

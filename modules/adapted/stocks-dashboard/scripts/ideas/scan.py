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


"""Daily signal scan over the 200-2,000 cr universe.

Usage: python3 scripts/ideas/scan.py [--date YYYY-MM-DD] [--days 65]
Writes docs/ideas/scan/<date>.json with, for every universe name: price/volume features from the last
`--days` BSE bhavcopies, and the day's classified BSE announcements. Candidates are the names whose
signal score clears the bar; the routine then researches those.

Signal families (all from public exchange data, nothing inferred):
  ORDER      order / contract / LOI / work order / tender awarded
  CAPEX      capex, expansion, new plant, commercial production, land allotment, capacity
  RATING     credit rating action (CRISIL / ICRA / CARE / India Ratings / Infomerics / Acuite / Brickwork)
  RESULT     financial results filed (Outcome of Board Meeting / Results)
  FUNDRAISE  preferential issue, QIP, rights, warrants, fund raising
  CORPACT    bonus, split, buyback, dividend
  DISCLOSE   investor presentation, concall transcript / recording, press release, analyst meet
  DEAL       acquisition, JV, MoU, subsidiary incorporation
  VOL        volume today >= 3x the 60-day median with a positive close
  BREAKOUT   close at the highest of the window with turnover above the liquidity gate
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# scripts/, for bse_names (runbook §204). Appended, so this folder's bse.py / ist.py still resolve first.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bse
import bse_names
import ist

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")
LIQ_MIN_TURNOVER = 25e5  # Rs 25 lakh median daily turnover over the window
NSE_PDF = (
    "https://nsearchives.nseindia.com/corporate/"  # the prefix docs/announcements.json rows omit
)


def nse_announcements(asof, by_scrip):
    """The day's filings from docs/announcements.json - NSE corporate announcements, ~31 rolling days, rebuilt
    four times a day from GitHub Actions by refresh-announcements.yml - shaped like BSE's rows so classify()
    needs no second path. A fallback for when BSE's announcement list (api.bseindia.com) is unreachable, which
    on 2026-09-23/24 it was from the sandbox AND from Actions (runbook 144e). Only names with an NSE symbol can
    match, so BSE-only and SME names stay unknown on such a day; the caller must say so."""
    fn = os.path.join(HERE, "..", "..", "docs", "announcements.json")
    if not os.path.exists(fn):
        return [], 0, "no docs/announcements.json"
    d = json.load(open(fn, encoding="utf-8"))
    by_nse = {u["nse"]: s for s, u in by_scrip.items() if u.get("nse")}
    day, rows, total = asof.isoformat(), [], 0
    for r in d.get("rows") or []:
        try:
            sym, name, dt, cat, desc, pdf = r[:6]
        except (TypeError, ValueError):
            continue
        if not str(dt).startswith(day):
            continue
        total += 1
        s = by_nse.get(sym)
        if not s:
            continue
        rows.append(
            {
                "SCRIP_CD": s,
                "NEWSSUB": desc or "",
                "HEADLINE": desc or "",
                "NEWS_DT": dt,
                "CATEGORYNAME": cat or "",
                "SUBCATNAME": "",
                "ATTACHMENTNAME": "",
                "_pdf": (NSE_PDF + pdf) if pdf else "",
            }
        )
    return rows, total, f"nse (docs/announcements.json, updated {d.get('updated', '?')})"


CATS = [
    (
        "ORDER",
        re.compile(
            r"\b(order|orders|contract|loi|letter of intent|work order|purchase order|tender|awarded|bagged|supply agreement|rate contract)\b",
            re.I,
        ),
    ),
    (
        "CAPEX",
        re.compile(
            r"\b(capex|capacity|expansion|new plant|commercial production|commencement of (commercial )?production|land|greenfield|brownfield|unit ii|phase ii|installed capacity|commissioning)\b",
            re.I,
        ),
    ),
    (
        "RATING",
        re.compile(
            r"\b(credit rating|crisil|icra|care ratings|india ratings|infomerics|acuite|brickwork|rating (action|reaffirm|upgrade|assigned))\b",
            re.I,
        ),
    ),
    (
        "RESULT",
        re.compile(
            r"\b(financial results?|results for the (quarter|half|year)|unaudited|audited results|outcome of board meeting)\b",
            re.I,
        ),
    ),
    (
        "FUNDRAISE",
        re.compile(
            r"\b(preferential|qip|qualified institutions?|rights issue|warrants|fund ?raising|raise (of )?funds|private placement)\b",
            re.I,
        ),
    ),
    ("CORPACT", re.compile(r"\b(bonus|stock split|sub-?division|buy ?back|dividend)\b", re.I)),
    (
        "DISCLOSE",
        re.compile(
            r"\b(investor presentation|presentation|earnings call|concall|conference call|transcript|audio recording|press release|media release|analyst|investor meet)\b",
            re.I,
        ),
    ),
    (
        "DEAL",
        re.compile(
            r"\b(acquisition|acquire|joint venture|jv|mou|memorandum of understanding|incorporation of (a )?(wholly owned )?subsidiary|stake)\b",
            re.I,
        ),
    ),
]
NOISE = re.compile(
    r"\b(closure of trading window|trading window|agm|egm|postal ballot|book closure|record date|change in directorate|resignation|appointment of|esop|espp|allotment of esop|compliance certificate|reg\.? ?74|regulation 74|newspaper (publication|advertisement)|loss of share certificate|duplicate share|investor complaints|reconciliation of share capital|scrutinizer|voting results|clarification on price|spurt in volume|change in management|cessation|kmp|senior management)\b",
    re.I,
)
WEIGHT = {
    "ORDER": 4,
    "CAPEX": 4,
    "RATING": 3,
    "RESULT": 2,
    "FUNDRAISE": 2,
    "DEAL": 2,
    "DISCLOSE": 1,
    "CORPACT": 1,
    "VOL": 2,
    "BREAKOUT": 2,
}


STRONG_SUB = re.compile(
    r"credit rating|investor presentation|press release|outcome of board meeting|financial results|earnings call|transcript",
    re.I,
)


def classify(row, company=""):
    # drop the "<Company name> - <scrip> - " prefix and the company name itself, so words in the name
    # (Land, Power, Solar, Orders...) cannot trigger a category
    subj = re.sub(r"^.*? - \d{6} - ", "", (row.get("NEWSSUB") or "").strip())
    text = f"{subj} | {row.get('HEADLINE') or ''} | {row.get('SUBCATNAME') or ''} | {row.get('CATEGORYNAME') or ''}"
    if company:
        core = re.sub(r"\b(ltd|limited|india|the)\b\.?", "", company, flags=re.I).strip()
        if len(core) >= 4:
            text = re.sub(re.escape(core), " ", text, flags=re.I)
        text = re.sub(re.escape(company), " ", text, flags=re.I)
    if NOISE.search(text) and not STRONG_SUB.search(row.get("SUBCATNAME") or ""):
        return []
    return [c for c, rx in CATS if rx.search(text)]


def features(scrip, series):
    """series: list of bhavcopy rows for this scrip, oldest first."""
    closes = [r["close"] for r in series if r["close"] > 0]
    vols = [r["volume"] for r in series]
    turns = [r["turnover"] for r in series]
    if len(closes) < 5:
        return None
    last = series[-1]
    med_vol = statistics.median(vols[:-1]) if len(vols) > 1 else 0
    med_turn = statistics.median(turns) if turns else 0
    f = {
        "close": last["close"],
        "ret_1d": round((last["close"] / series[-2]["close"] - 1) * 100, 1)
        if len(series) > 1 and series[-2]["close"]
        else None,
        "ret_5d": round((last["close"] / closes[-6] - 1) * 100, 1) if len(closes) > 6 else None,
        "ret_20d": round((last["close"] / closes[-21] - 1) * 100, 1) if len(closes) > 21 else None,
        "ret_window": round((last["close"] / closes[0] - 1) * 100, 1),
        "vol_ratio": round(last["volume"] / med_vol, 1) if med_vol else None,
        "med_turnover_lakh": round(med_turn / 1e5, 1),
        "window_high": max(closes),
        "window_low": min(closes),
        "at_window_high": last["close"] >= max(closes) * 0.995,
        "days": len(closes),
        "liquid": med_turn >= LIQ_MIN_TURNOVER,
    }
    return f


def heal_names():
    """Scan files written before runbook §204 carry BSE's "-$" name marker in a row's `name` (copied from
    universe.json) and at the head of an announcement `subject` (BSE's NEWSSUB). Clean those two fields in
    every earlier scan file that has the marker; nothing else in a file is touched."""
    healed = []
    for fn in sorted(glob.glob(os.path.join(DOCS, "scan", "*.json"))):
        if bse_names.MARKER.encode() not in open(fn, "rb").read():
            continue
        d = json.load(open(fn))
        n = 0
        for r in d.get("rows") or []:
            if isinstance(r.get("name"), str):
                v = bse_names.clean_scrip_name(r["name"])
                n += v != r["name"]
                r["name"] = v
            for a in r.get("announcements") or []:
                if isinstance(a.get("subject"), str):
                    v = bse_names.clean_ann_subject(a["subject"], r.get("scrip"))
                    n += v != a["subject"]
                    a["subject"] = v
        if n:
            json.dump(d, open(fn, "w"), separators=(",", ":"))
            healed.append(f"{os.path.basename(fn)} {n}")
    print(
        'scan: earlier scan files with BSE\'s "-$" name marker cleaned (runbook 204):',
        ", ".join(healed) or "none",
    )


def run(date, days):
    uni = json.load(open(os.path.join(DOCS, "universe.json")))["rows"]
    for u in uni:  # a universe kept from before runbook §204 can still carry BSE's "-$" name marker
        u["name"] = bse_names.clean_scrip_name(u.get("name"))
    by_scrip = {u["scrip"]: u for u in uni}
    tdays = bse.trading_days_back(days, end=date)
    if not tdays:
        raise SystemExit("no bhavcopy found")
    asof = tdays[0]
    hist = collections.defaultdict(list)
    for d in sorted(tdays):
        for r in bse.bhavcopy(d):
            if r["scrip"] in by_scrip:
                hist[r["scrip"]].append(r)
    ann = bse.announcements(asof)
    # "0 announcements" reads as a quiet day, but it is also what a blocked feed looks like. Record
    # which it was: on 2026-09-24 the feed 403'd all run and every candidate's empty filing list was
    # UNKNOWN, not empty. The page and the run log both need to be able to say so.
    ann_blocked = bse.last_announcements_partial
    # And a list that loaded fine can still be less than the day: stopped short of the count BSE itself
    # reports (the 2,000-row page guard did that on 2026-09-25: 2,000 read of 2,084, runbook 144f), or
    # read on the day itself, before the evening's filings. Record both so neither reads as the day.
    ann_capped, ann_reported, ann_read_at = (
        bse.last_announcements_capped,
        bse.last_announcements_reported,
        bse.last_announcements_read_at,
    )
    ann_source, ann_total = "bse", len(ann)
    if ann_blocked:
        nse_rows, ann_total, ann_source = nse_announcements(asof, by_scrip)
        print(
            f"announcements: BSE feed blocked -> {len(nse_rows)} universe rows of {ann_total} that day from {ann_source}"
        )
        ann = nse_rows
        ann_capped, ann_reported, ann_read_at = (
            False,
            None,
            None,
        )  # they describe BSE's list, which is not used
    ann_by = collections.defaultdict(list)
    for a in ann:
        s = str(a.get("SCRIP_CD") or "").strip()
        if s not in by_scrip:
            continue
        cats = classify(a, by_scrip[s]["name"])
        if not cats:
            continue
        ann_by[s].append(
            {
                "cats": cats,
                "subject": bse_names.clean_ann_subject(a.get("NEWSSUB"), s),
                "headline": (a.get("HEADLINE") or "").strip()[:300],
                "time": a.get("NEWS_DT"),
                "pdf": a.get("_pdf") or bse.attachment_url(a),
                "category": a.get("CATEGORYNAME"),
                "sub": a.get("SUBCATNAME"),
            }
        )
    rows = []
    for s, u in by_scrip.items():
        f = features(s, hist.get(s, []))
        sig = collections.OrderedDict()
        for a in ann_by.get(s, []):
            for c in a["cats"]:
                sig[c] = sig.get(c, 0) + 1
        if f:
            if f["vol_ratio"] and f["vol_ratio"] >= 3 and (f["ret_1d"] or 0) > 0:
                sig["VOL"] = 1
            if f["at_window_high"] and f["liquid"]:
                sig["BREAKOUT"] = 1
        score = sum(WEIGHT.get(c, 1) * min(n, 2) for c, n in sig.items())
        if f and not f["liquid"]:
            score = round(score * 0.5, 1)
        rows.append(
            {
                "scrip": s,
                "id": u["id"],
                "name": u["name"],
                "nse": u["nse"],
                "mcap": u["mcap"],
                "group": u["group"],
                "sme": u["sme"],
                "features": f,
                "signals": dict(sig),
                "score": score,
                "announcements": ann_by.get(s, []),
            }
        )
    rows.sort(key=lambda r: (-r["score"], -(r["features"] or {}).get("vol_ratio", 0) or 0))
    cands = [r for r in rows if r["score"] >= 4]
    # keep the file small enough to commit daily: only names with at least one signal are written
    kept = [r for r in rows if r["score"] > 0]
    out = {
        "date": asof.isoformat(),
        "window_days": len(tdays),
        "window_from": min(tdays).isoformat(),
        "universe": len(rows),
        "announcements_total": ann_total,
        "announcements_in_universe": sum(len(v) for v in ann_by.values()),
        "announcements_blocked": ann_blocked,
        "announcements_source": ann_source,
        "announcements_reported": ann_reported,
        "announcements_capped": ann_capped,
        "announcements_read_at": ann_read_at,
        "candidates": len(cands),
        "rows_with_signals": len(kept),
        "rows": kept,
    }
    os.makedirs(os.path.join(DOCS, "scan"), exist_ok=True)
    fn = os.path.join(DOCS, "scan", f"{asof.isoformat()}.json")
    json.dump(out, open(fn, "w"), separators=(",", ":"))
    print(
        f"scan {asof}: window {len(tdays)}d from {min(tdays)} | universe {len(rows)} | announcements {ann_total} total"
        f"{' (BSE FEED BLOCKED - ' + ann_source + '; this count is a floor, not the day)' if ann_blocked else ''}"
        f"{f' of {ann_reported} BSE reports (CAPPED - the read stopped short; this count is a floor, not the day)' if ann_capped else ''}"
        f"{f' (BSE count {ann_reported}, read {ann_read_at})' if not ann_blocked and not ann_capped else ''}, "
        f"{out['announcements_in_universe']} classified in universe | candidates {len(cands)} -> {fn}"
    )
    for r in cands[:25]:
        f = r["features"] or {}
        print(
            f"  {r['score']:5.1f} {r['id']:12s} {r['name'][:32]:32s} mcap {r['mcap']:7.0f} | {dict(r['signals'])} | 1d {f.get('ret_1d')} vol x{f.get('vol_ratio')} turn {f.get('med_turnover_lakh')}L"
        )
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--days", type=int, default=65)
    a = ap.parse_args()
    d = datetime.date.fromisoformat(a.date) if a.date else ist.today()
    heal_names()  # first, so a scan that cannot run (no bhavcopy) still leaves the earlier files clean
    run(d, a.days)

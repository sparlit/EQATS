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
"""§164k — fill single-quarter HOLES from Dec-2015 on from each company's ORIGINAL BSE SHP XBRL (Quantmac reply v3, 26-Sep).
The quarter's original filing = the list row with an XbrlFile and a filing_date_time (earliest); a quarter BSE lists only as a
revision is skipped (the original's date is unknown and a re-filing never dates a row). Values: fetch_shareholding.parse_shp,
the live pipeline's own parser; visibility = the original's calendar day (midnight rule). Transport: scripts/bse_headers.py
(honest headers: own User-Agent, no browser impersonation), one request at a time ~1 s apart.
Stages (work dir argv[2]): fetch <work> <holes.json> ; parse <work> <holes.json> ; write <work> <note...>
holes.json: [[sym, 'YYYY-MM-DD', bse_code], ...]; lists: ~/stocks-cache/shp/bse_all/<sym>.json."""
import gzip
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LISTS = os.path.expanduser(os.environ.get("SHP_LISTS", "~/stocks-cache/shp/bse_all"))
MON = {"March": 3, "June": 6, "September": 9, "December": 12}


def qe_of(qtr):
    q = (qtr or "").split()
    if len(q) != 2 or q[0] not in MON:
        return None
    m = MON[q[0]]
    return "%s-%02d-%02d" % (q[1], m, 31 if m in (3, 12) else 30)


def original(sym, qe):
    p = os.path.join(LISTS, sym + ".json")
    if not os.path.exists(p):
        return None, "no list"
    t = json.load(open(p))
    t = t.get("Table") if isinstance(t, dict) else t
    rows = [r for r in t or [] if qe_of(r.get("qtr")) == qe]
    if not rows:
        return None, "quarter not on BSE's list"
    orig = sorted(
        [
            r
            for r in rows
            if (r.get("XbrlFile") or "").strip()
            and r.get("filing_date_time")
            and not r.get("revised_date_time")
        ],
        key=lambda r: r["filing_date_time"],
    )
    if orig:
        return orig[0], "original"
    if any((r.get("XbrlFile") or "").strip() for r in rows):
        return None, "revision-only (original not listed)"
    return None, "no XBRL for the quarter"


def fetch(work, holes):
    os.makedirs(os.path.join(work, "xbrl"), exist_ok=True)
    ok = bad = skip = 0
    t0 = time.time()
    why = {}
    for i, (s, qe, _code) in enumerate(holes):
        r, how = original(s, qe)
        if not r:
            why[f"{s}|{qe}"] = how
            continue
        f = r["XbrlFile"].strip()
        p = os.path.join(work, "xbrl", f)
        if os.path.exists(p):
            skip += 1
            continue
        u = (
            ("https://www.bseindia.com" + r["xbrlurl"].strip())
            if (r.get("xbrlurl") or "").strip().lower().endswith(".xml")
            else "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + f
        )
        body = b""
        for a in range(3):
            try:
                body = urllib.request.urlopen(urllib.request.Request(u), timeout=60).read()
                break
            except Exception:
                time.sleep(4 * (a + 1))
        if len(body) > 2000:
            open(p + ".tmp", "wb").write(body)
            os.replace(p + ".tmp", p)
            ok += 1
        else:
            bad += 1
            why[f"{s}|{qe}"] = "download failed"
        time.sleep(1.0)
        if i % 50 == 0:
            print(
                "  %d/%d ok=%d bad=%d skip=%d %.0fs"
                % (i, len(holes), ok, bad, skip, time.time() - t0),
                flush=True,
            )
    json.dump(why, open(os.path.join(work, "fetch_notes.json"), "w"), indent=1)
    print("FETCH DONE ok=%d bad=%d skip=%d no-original=%d" % (ok, bad, skip, len(why)), flush=True)


def parse(work, holes):
    import collections

    import fetch_shareholding as F

    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    props = {}
    st = collections.Counter()
    notes = {}
    for s, qe, code in holes:
        if qe in (hist.get(s) or {}):
            st["already in store"] += 1
            continue
        r, how = original(s, qe)
        if not r:
            st[how] += 1
            notes[f"{s}|{qe}"] = how
            continue
        p = os.path.join(work, "xbrl", r["XbrlFile"].strip())
        if not os.path.exists(p):
            st["not downloaded"] += 1
            continue
        try:
            res = F.parse_shp(open(p, "rb").read(), qe)
        except Exception as e:
            st["parse error"] += 1
            notes[f"{s}|{qe}"] = f"parse error {e!r}"
            continue
        if not isinstance(res, dict):
            st["not anchored"] += 1
            notes[f"{s}|{qe}"] = "parse_shp: not anchored"
            continue
        sub = r["filing_date_time"][:10]
        props.setdefault(s, {})[qe] = [
            res["prom"],
            res["fii"],
            res["dii"],
            res["mf"],
            res["ins"],
            sub,
            res.get("nsh"),
            "%d:%s" % (int(code), r.get("qtrid")),
        ]
        st["ok"] += 1
    json.dump(props, open(os.path.join(work, "proposals.json"), "w"), indent=1)
    json.dump(notes, open(os.path.join(work, "notes.json"), "w"), indent=1)
    print("parse:", dict(st))


def write(work, note):
    props = json.load(open(os.path.join(work, "proposals.json")))
    p = os.path.join(HERE, "shp_fill_n500_gaps.json.gz")
    led = json.load(gzip.open(p, "rt", encoding="utf-8"))
    fills = led.setdefault("fills", {})
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    n = skip = 0
    for s, qs in props.items():
        for qe, cell in qs.items():
            if qe in (hist.get(s) or {}) or qe in (fills.get(s) or {}):
                skip += 1
                continue
            fills.setdefault(s, {})[qe] = cell
            n += 1
    led.setdefault("_meta", {})["s164k"] = note
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(led, fh, separators=(",", ":"))
    print("write: %d cells added, %d skipped" % (n, skip))


if __name__ == "__main__":
    st, work = sys.argv[1], os.path.expanduser(sys.argv[2])
    if st == "fetch":
        fetch(work, json.load(open(sys.argv[3])))
    elif st == "parse":
        parse(work, json.load(open(sys.argv[3])))
    elif st == "write":
        write(work, " ".join(sys.argv[3:]))

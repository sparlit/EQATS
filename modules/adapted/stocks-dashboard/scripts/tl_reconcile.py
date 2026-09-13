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
"""Nightly Trendlyne reconcile (DATA_RUNBOOK.md section 31).

Compares OUR declared-results coverage for the current quarter against Trendlyne's, and
self-heals when we're missing filings. Born from the 121-vs-144 gap of 2026-07-17, where
the BSE feed merge had been silently dead for 3 days — an external yardstick would have
caught it on night one.

What it does (pure stdlib, no heavy deps, safe in a light CI step):
  1. OUR declared set = companies with parsed numbers for the current quarter
     (sf_fundamentals + bse_fundamentals + vision_fills) UNION feed-declared rows
     (results_pending.classify — the shared classifier, so counts can't drift).
  2. TRENDLYNE total   = the results-dashboard tiles (positive+negative+neutral profit
     growth), season-to-date — same thing their site header shows everyone.
     TRENDLYNE names   = their free events-calendar API (result-purpose board meetings,
     quarter start → today), fetched in small windows under the 200-row curtail.
  3. Diff with three matchers (NSE symbol, BSE scrip→symbol, normalized company name),
     then bucket the unmatched: March/other-quarter filers (both sides exclude them),
     meetings ≤1 day old with no filing yet (grace — they file late evening), and the
     rest = ACTIONABLE (we likely missed a filing).
  4. If anything is actionable: re-run our own fetchers (fetch_announcements +
     fetch_bse_results — the 31-day window makes them self-healing) and re-diff.
  5. Write docs/tl_reconcile.json for status/alerting. ALWAYS exits 0; the workflow
     decides what to do (commit healed feeds, open/close the alert issue).

Trendlyne being unreachable/blocked is NOT an error: the report records tl_total=null,
actionable=[] and the night is a no-op (no false alarms on their outages).

Run: python -X utf8 scripts/tl_reconcile.py
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DOCS = os.path.join(HERE, "..", "docs")
OUT = os.path.join(DOCS, "tl_reconcile.json")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}
RESULT_PURPOSE = re.compile(r"quarterly results|audited results|financial results", re.IGNORECASE)
ACTIONABLE_ALERT_AT = 3  # workflow opens the alert issue at this many


def get(url, timeout=40):
    return (
        urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        .read()
        .decode("utf-8", "replace")
    )


def load(name, default):
    try:
        return json.load(open(os.path.join(DOCS, name), encoding="utf-8"))
    except Exception:
        return default


def nname(s):
    s = re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    return re.sub(r"(limited|ltd)$", "", s)


def rows_of(qs):
    return qs if isinstance(qs, list) else list(qs.values())


def our_declared(qe):
    """(declared_syms, declared_names, feed_qe_by_sym) for the current quarter."""
    feed = load("results_feed.json", {"rows": []})["rows"]
    feed_qe = {}
    for r in feed:
        feed_qe.setdefault(r[0].upper(), set()).add(r[3])
    names = set()

    # numbers side: NSE XBRL + BSE OCR + vision overlay
    syms = set()
    for s, qs in (load("sf_fundamentals.json", {}) or {}).items():
        if not isinstance(qs, (list, dict)):
            continue  # metadata keys ("updated", …)
        for r in rows_of(qs):
            if (
                isinstance(r, list)
                and r
                and int(r[0]) == qe
                and (r[1] is not None or (len(r) > 3 and r[3] is not None))
            ):
                syms.add(s.upper())
                break
    for s, qs in (load("bse_fundamentals.json", {}) or {}).items():
        if s == "px" or not isinstance(qs, (list, dict)):
            continue
        for r in rows_of(qs):
            if isinstance(r, list) and r and int(r[0]) == qe and any(v is not None for v in r[1:]):
                syms.add(s.upper())
                break
    for s, qmap in (load("vision_fills.json", {}) or {}).items():
        if str(qe) in qmap or qe in qmap:
            syms.add(s.upper())

    # feed side via the shared classifier (same universe the coverage page counts)
    try:
        import results_pending

        _, rows = results_pending.classify()
        for r in rows:
            syms.add(str(r.get("sym", "")).upper())
            names.add(nname(r.get("name")))
    except Exception as e:  # classifier needs quarterly_results.json
        print(f"  (results_pending.classify unavailable: {e} — feed rows direct)")
        qe_iso = "%04d-%02d-%02d" % (qe // 10000, qe // 100 % 100, qe % 100)
        for r in feed:
            # qe==0 = declared but period-unclassified (resolved by the vision prep within hours) —
            # still a declared filing, so it must cover the TL meeting or the diff re-flags it nightly.
            # Filed-after-quarter-end guard: a stale unresolved row from BEFORE the quarter ended is a
            # late prior-quarter filing, not live-quarter coverage (same rule as quarterly-results.html).
            if r[3] == qe or (r[3] == 0 and r[2][:10] > qe_iso):
                syms.add(r[0].upper())
                names.add(nname(r[1]))

    co = (load("quarterly_results.json", {}) or {}).get("co", {})
    for s in list(syms):
        if s in co:
            names.add(nname(co[s].get("n")))
    for r in feed:  # every feed name helps the name-matcher
        names.add(nname(r[1]))
    syms.discard("")
    names.discard("")
    return syms, names, feed_qe


def tl_dashboard_total():
    """Declared count from Trendlyne's public results dashboard (tiles, table fallback)."""
    try:
        h = get("https://trendlyne.com/dashboard/results/industry/")
        tiles = re.findall(r">\s*(\d+)\s*<[^>]*>(?:[^<>]*<[^>]+>)*\s*(POSITIVE|NEGATIVE|NEUTRAL)\s+PROFIT\s+GROWTH", h)
        if not tiles:
            tiles = [
                (m.group(1), m.group(2))
                for m in re.finditer(
                    r"(\d+)[^<>]{0,60}</\w+>[^<>]{0,220}(POSITIVE|NEGATIVE|NEUTRAL)\s+PROFIT\s+GROWTH", h, re.DOTALL
                )
            ]
        if len(tiles) >= 2:
            return sum(int(n) for n, _ in tiles[:3]), "tiles"
        table = re.findall(r'data-export="(\d+) • (\d+) • \d+"', h)
        if table:
            return sum(int(a) + int(b) for a, b in table), "industry-table"
    except Exception as e:
        print(f"  (TL dashboard unreachable: {e})")
    return None, None


def tl_result_meetings(start, end):
    """Result-purpose board meetings from TL's free calendar API, chunked under the curtail."""
    out, day, one = {}, start, datetime.timedelta(days=1)
    while day <= end:
        hi = min(day + 2 * one, end)
        url = (
            "https://trendlyne.com/equity/api/events/calendar-v2/?corporate_actions=BM"
            "&stock_group=All&perPageCount=200&groupType=all&groupName=all"
            "&start_date={}&end_date={}".format(day.strftime("%d%%2F%m%%2F%Y"), hi.strftime("%d%%2F%m%%2F%Y"))
        )
        try:
            for e in json.loads(get(url))["body"]["eventsData"]:
                if not RESULT_PURPOSE.search(str(e.get("purpose") or e.get("event-details") or "")):
                    continue
                s = e["stock"]
                key = (s.get("NSEcode") or "BSE:{}".format(s.get("BSEcode")) or s["get_full_name"]).upper()
                d = out.setdefault(
                    key, {"name": s.get("get_full_name") or key, "bse": str(s.get("BSEcode") or ""), "dates": []}
                )
                d["dates"].append(e["date"])
        except Exception as ex:
            print(f"  (TL calendar window {day} failed: {ex})")
        day = hi + one
        time.sleep(0.5)
    return out


def diff(meets, syms, names, feed_qe, qe, today):
    rev = {}
    try:
        by_id = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"]
        rev = {str(v): k.upper() for k, v in by_id.items()}
    except Exception:
        pass
    grace = (today - datetime.timedelta(days=1)).isoformat()
    actionable, other_quarter, too_fresh = [], [], []
    for key, m in sorted(meets.items()):
        sym = key.split(":")[-1]
        mapped = rev.get(m["bse"], sym)
        if sym in syms or mapped in syms or nname(m["name"]) in names:
            continue
        qes = feed_qe.get(sym, set()) | feed_qe.get(mapped, set())
        rec = {"sym": mapped if mapped in feed_qe else sym, "name": m["name"], "dates": sorted(m["dates"])}
        if qes and qe not in qes:
            other_quarter.append(rec)  # March/annual filer — both sides exclude
        elif max(m["dates"]) >= grace:
            too_fresh.append(rec)  # met yesterday/today, filing likely tonight
        else:
            actionable.append(rec)
    return actionable, other_quarter, too_fresh


def main():
    qr = load("quarterly_results.json", None)
    if not qr:
        print("no quarterly_results.json — nothing to reconcile")
        return
    qe = qr["quarters"][0]
    qdate = datetime.date(qe // 10000, qe // 100 % 100, qe % 100)
    today = datetime.date.today()
    start = qdate + datetime.timedelta(days=1)
    print("Reconciling quarter %d, window %s -> %s" % (qe, start, today))

    syms, names, feed_qe = our_declared(qe)
    print("OUR declared (numbers + feed):", len(syms))

    tl_total, tl_src = tl_dashboard_total()
    print("TL dashboard declared:", tl_total, f"(via {tl_src})" if tl_src else "")

    meets = tl_result_meetings(start, today)
    print("TL result-purpose meetings in window:", len(meets))

    actionable, other_q, fresh = diff(meets, syms, names, feed_qe, qe, today)
    healed = 0
    if actionable:
        print("MISSING %d — self-healing via own fetchers:" % len(actionable))
        for a in actionable:
            print("   ", a["sym"], a["name"], a["dates"][-1])
        for script in ("fetch_announcements.py", "fetch_bse_results.py"):
            try:
                subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, script)], timeout=1200, check=False)
            except Exception as ex:
                print(f"  (heal step {script} failed: {ex})")
        before = len(actionable)
        syms, names, feed_qe = our_declared(qe)
        actionable, other_q, fresh = diff(meets, syms, names, feed_qe, qe, today)
        healed = before - len(actionable)
        print("after heal: %d actionable (healed %d)" % (len(actionable), healed))

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    json.dump(
        {
            "updated": ist.strftime("%Y-%m-%d %H:%M IST"),
            "quarter": qe,
            "ours_declared": len(syms),
            "tl_dashboard": tl_total,
            "tl_meetings": len(meets),
            "healed": healed,
            "actionable": actionable,
            "other_quarter": other_q,
            "awaiting_filing": fresh,
            "alert_at": ACTIONABLE_ALERT_AT,
        },
        open(OUT, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=1,
    )
    print("wrote docs/tl_reconcile.json — ours %d vs TL %s, %d actionable" % (len(syms), tl_total, len(actionable)))


if __name__ == "__main__":
    main()

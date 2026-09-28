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
"""Gather INDEPENDENT evidence for every event in scripts/ca_inferred_review.json (DATA_RUNBOOK §161g).

Each review event is a split/bonus factor baked into the published price bins with no record in our
official ledger. This script decides nothing — it fetches, per event, what each source actually says,
and writes scripts/ca_review_evidence.json. Runs in CI (.github/workflows/verify-ca-review.yml)
because NSE/Yahoo are reachable from GitHub runners (the dev sandbox gets Akamai "Access Denied").

Sources, each recorded with an explicit reach/coverage status so absence is never inferred from a
failed fetch (§0):
  nse   NSE corporates-corporateActions, PER SYMBOL, both boards (equities + sme), every alias the
        symbol ever traded under (_rename_map.json). `covered` = the feed returned >= 1 row of ANY
        purpose for that symbol, i.e. it knows the company; only then can "no split row" mean absence.
  bhav  NSE's own bhavcopy for the two boundary sessions: raw close, open, prev close (the raw move).
  yahoo Yahoo chart API split EVENTS (a corporate-action record, not the adjusted closes) for
        SYM.NS and the BSE code .BO. `covered` = Yahoo returned price bars spanning both dates.
  bse   BSE per-scrip corporate-action API for the window (by BSE code from bse_scrips.json).

Run (CI): python3 scripts/verify_ca_review.py
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import bse_headers as BH  # §181 BSE headers
import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_argv = sys.argv
sys.argv = _argv[:1]
import build_corp_actions as BCA  # official_factor / is_demerger — the SAME parser the ledger uses
import build_fundamentals as F  # NSE cookie jar + _get + iso
import build_sf_data as B  # fetch_day (bhavcopy rows)

sys.argv = _argv

OUT = os.path.join(HERE, "ca_review_evidence.json")
VERSION = 2  # v2: all_ex (era coverage) + Yahoo errors retried
UA = F.UA


def od(y):
    return datetime.date(y // 10000, y // 100 % 100, y % 100)


def nse_rows(jar, sym, board):
    url = (
        "https://www.nseindia.com/api/corporates-corporateActions?index={}&symbol={}"
        "&from_date=01-01-1995&to_date={}".format(
            board, urllib.parse.quote(sym), datetime.date.today().strftime("%d-%m-%Y")
        )
    )
    h = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
    last = None
    for attempt in range(3):
        try:
            d = json.loads(F._get(url, headers=h, jar=jar, timeout=40))
            return ("ok", d if isinstance(d, list) else d.get("data", []))
        except Exception as e:
            last = str(e)[:80]
            time.sleep(1.5 * (attempt + 1))
    return ("error: " + (last or "?"), [])


def yahoo(ticker, a, b):
    p1 = int(datetime.datetime.combine(od(a) - datetime.timedelta(days=40), datetime.time()).timestamp())
    p2 = int(datetime.datetime.combine(od(b) + datetime.timedelta(days=40), datetime.time()).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d&events=split%%7Cdiv"
        % (urllib.parse.quote(ticker), p1, p2)
    )
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read()
            r = (json.loads(raw).get("chart", {}).get("result") or [None])[0]
            if not r:
                return {"status": "no-result"}
            ts = r.get("timestamp") or []
            days = [int(datetime.datetime.utcfromtimestamp(t + 19800).strftime("%Y%m%d")) for t in ts]
            ev = r.get("events") or {}
            splits = [
                {
                    "date": int(datetime.datetime.utcfromtimestamp(int(s["date"]) + 19800).strftime("%Y%m%d")),
                    "num": s.get("numerator"),
                    "den": s.get("denominator"),
                    "ratio": s.get("splitRatio"),
                }
                for s in (ev.get("splits") or {}).values()
            ]
            divs = [
                {
                    "date": int(datetime.datetime.utcfromtimestamp(int(s["date"]) + 19800).strftime("%Y%m%d")),
                    "amount": s.get("amount"),
                }
                for s in (ev.get("dividends") or {}).values()
            ]
            return {
                "status": "ok",
                "covered": bool(days) and min(days) <= a and max(days) >= b,
                "first": min(days) if days else None,
                "last": max(days) if days else None,
                "splits": sorted(splits, key=lambda x: x["date"]),
                "divs": sorted(divs, key=lambda x: x["date"]),
            }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"status": "404"}
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return {"status": "error"}


BSE_DEAD = {"n": 0}


def bse(code, a, b):
    if BSE_DEAD["n"] >= 8:
        return {"status": "skipped: api.bseindia.com refused 8 in a row"}
    f = (od(a) - datetime.timedelta(days=15)).strftime("%Y%m%d")
    t = (od(b) + datetime.timedelta(days=15)).strftime("%Y%m%d")
    url = (
        f"https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w?Fdate={f}&Purposecode=&ScripCode={code}"
        f"&segment=0&strSearch=S&TDate={t}"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"},
        )
        rows = json.loads(urllib.request.urlopen(req, timeout=30).read() or b"[]")
        BSE_DEAD["n"] = 0
        return {
            "status": "ok",
            "rows": [
                {"purpose": r.get("Purpose"), "ex": r.get("Ex_date") or r.get("BCRD_from")}
                for r in (rows if isinstance(rows, list) else [])
            ],
        }
    except Exception as e:
        BSE_DEAD["n"] += 1
        return {"status": "error: " + str(e)[:60]}


def main():
    R = json.load(open(os.path.join(HERE, "ca_inferred_review.json")))["events"]
    try:
        ren = json.load(open(os.path.join(HERE, "_rename_map.json")))
    except Exception:
        ren = {}
    alias = {}
    for o, n in ren.items():
        alias.setdefault(n, set()).add(o)
        alias.setdefault(o, set()).add(n)
    bse_ids = json.load(open(os.path.join(HERE, "bse_scrips.json"))).get("by_id", {})
    prev = {}
    if os.path.exists(OUT):  # resumable: keep completed events
        try:
            prev = {(e["sym"], e["b"]): e for e in json.load(open(OUT)).get("events", [])}
        except Exception:
            prev = {}
    jar = F.nse_jar()
    bjar = B.jar()
    nse_cache, day_cache = {}, {}
    out = []
    t0 = time.time()
    for n, r in enumerate(R):
        key = (r["sym"], r["b"])
        if (
            key in prev
            and prev[key].get("done")
            and prev[key].get("v") == VERSION
            and all((prev[key]["yahoo_events"].get(k) or {}).get("status") != "error" for k in ("ns", "bo"))
        ):
            out.append(prev[key])
            continue
        s, a, b = r["sym"], r["a"], r["b"]
        ev = dict(r)
        # --- NSE official feed, every alias, both boards
        nse = {"covered": False, "status": {}, "rows": []}
        for sym in sorted({s} | alias.get(s, set())):
            for board in ("equities", "sme"):
                k = (sym, board)
                if k not in nse_cache:
                    nse_cache[k] = nse_rows(jar, sym, board)
                    time.sleep(0.35)
                st, rows = nse_cache[k]
                nse["status"][f"{sym}/{board}"] = "%s (%d rows)" % (st, len(rows))
                # every ex-date the feed holds for this company (any purpose): proves whether the
                # exchange was recording this company's actions in the event's era (§161g)
                nse.setdefault("all_ex", []).extend(
                    sorted({int(F.iso(x.get("exDate"))) for x in rows if F.iso(x.get("exDate"))})
                )
                if st == "ok" and rows:
                    nse["covered"] = True
                for x in rows:
                    ex = F.iso(x.get("exDate"))
                    if not ex:
                        continue
                    ex = int(ex)
                    if od(a) - datetime.timedelta(days=15) <= od(ex) <= od(b) + datetime.timedelta(days=15):
                        subj = x.get("subject") or x.get("purpose") or ""
                        f, _lab = BCA.official_factor(subj)
                        nse["rows"].append(
                            {
                                "sym": sym,
                                "board": board,
                                "ex": ex,
                                "subject": subj,
                                "factor": f,
                                "demerger": BCA.is_demerger(subj),
                            }
                        )
        ev["nse"] = nse
        # --- bhavcopy raw closes on both boundary sessions
        bh = {}
        for d in (a, b):
            if d not in day_cache:
                try:
                    rows = B.fetch_day(od(d), bjar) or []
                    day_cache[d] = {x[0]: x for x in rows}
                except Exception as e:
                    day_cache[d] = {"__error__": str(e)[:60]}
            row = None
            for sym in [s, *sorted(alias.get(s, set()))]:
                row = day_cache[d].get(sym)
                if row:
                    break
            bh[str(d)] = (
                {"close": row[1], "prev": row[2], "open": row[6] if len(row) > 6 else None}
                if row
                else (
                    "fetch-error"
                    if "__error__" in day_cache[d]
                    else ("no-file" if not day_cache[d] else "symbol-absent")
                )
            )
        ev["bhav"] = bh
        ca, cb = bh.get(str(a)), bh.get(str(b))
        if isinstance(ca, dict) and isinstance(cb, dict) and ca["close"]:
            ev["raw_ratio_bhav"] = round(cb["close"] / ca["close"], 4)
            ev["open_over_prev_bhav"] = round(cb["open"] / ca["close"], 4) if cb.get("open") else None
        # --- Yahoo split events (NSE ticker, then the BSE code)
        time.sleep(0.6)
        yh = {"ns": yahoo(s + ".NS", a, b)}
        code = bse_ids.get(s)
        if code:
            yh["bo"] = yahoo(f"{code}.BO", a, b)
        ev["yahoo_events"] = yh
        # --- BSE per-scrip corporate actions
        ev["bse"] = bse(code, a, b) if code else {"status": "no BSE code"}
        ev["done"] = True
        ev["v"] = VERSION
        out.append(ev)
        if n % 25 == 0:
            json.dump({"generated": datetime.datetime.utcnow().isoformat() + "Z", "events": out}, open(OUT, "w"))
            print("%d/%d  %.0fs" % (n + 1, len(R), time.time() - t0), flush=True)
    json.dump({"generated": datetime.datetime.utcnow().isoformat() + "Z", "events": out}, open(OUT, "w"), indent=0)
    print("done %d events in %.0fs -> %s" % (len(out), time.time() - t0, OUT))


if __name__ == "__main__":
    main()

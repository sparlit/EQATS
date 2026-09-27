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
"""§164i — fill single-quarter HOLES in the page era (<= Mar-2016) from BSE's own ShareholdingPattern.aspx pages
(Quantmac reply v3, 26-Sep: RELIANCE / WIPRO / BRITANNIA / LICHSGFIN … had no Mar-2016 row; the page downloads of §160/§164g
only fetched quarters that already had a store row, so a missing row never got its page).
Stages (work dir = argv[2], durable, e.g. ~/stocks-cache/shp/holes):
  fetch <work> <holes.json> [--alt]  plain, honestly identified GET of www.bseindia.com pages, one at a time, ~1 s apart.
                                     This stage NEVER imports fetch_shp_bse_aspx (it imports bse_headers, which would add
                                     browser-imitating headers to every urllib request in the process).
  parse <work> <holes.json>          fetch_shp_bse_aspx.cell_of on the cached pages only (CACHE_ONLY, bse_headers/curl_cffi
                                     stubbed: no network), neighbours from the store; writes <work>/proposals.json + rejects.
  write <work>                       merges proposals into scripts/shp_fill_bse_aspx.json.gz (fill-only: never replaces a cell).
holes.json: [[sym_in_store, qe 'YYYY-MM-DD', bse_code], ...]"""
import gzip
import json
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
UA = "stocks-dashboard-data-fetch/1.0 (+personal research; contact via github dhruvan246)"


def qtrid(qe):
    y = int(qe[:4])
    m = int(qe[5:7])
    return (y - 2001) * 4 + {3: 29, 6: 30, 9: 31, 12: 32}[m]


def page_path(work, code, q, flag):
    return os.path.join(work, "cache", "%d_%d_%s.html.gz" % (code, q, flag))


def fetch(work, holes, alt=False):
    import urllib.error
    import urllib.request

    os.makedirs(os.path.join(work, "cache"), exist_ok=True)
    ok = bad = skip = 0
    t0 = time.time()
    rej = (
        json.load(open(os.path.join(work, "rejects.json")))
        if alt and os.path.exists(os.path.join(work, "rejects.json"))
        else {}
    )
    for i, (s, qe, code) in enumerate(holes):
        q = qtrid(qe)
        first = "New" if q >= 50 else "Old"
        flags = [("Old" if first == "New" else "New")] if alt else [first]
        if alt and (f"{s}|{qe}") not in rej:
            continue
        for flag in flags:
            p = page_path(work, code, q, flag)
            if os.path.exists(p):
                skip += 1
                continue
            u = (
                "https://www.bseindia.com/corporates/ShareholdingPattern.aspx?scripcd=%d&flag_qtr=1&qtrid=%d.00&Flag=%s"
                % (code, q, flag)
            )
            body = b""
            for a in range(3):
                try:
                    r = urllib.request.urlopen(
                        urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}),
                        timeout=60,
                    )
                    body = r.read()
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (403, 404, 406, 410):
                        break
                except Exception:
                    pass
                time.sleep(3 + 3 * a)
            txt = body.decode("utf-8", "ignore")
            if len(txt) > 3000:
                with gzip.open(p + ".tmp", "wt", encoding="utf-8") as fh:
                    fh.write(txt)
                os.replace(p + ".tmp", p)
                ok += 1
            else:
                bad += 1
            time.sleep(1.0)
        if i % 100 == 0:
            print("  %d/%d ok=%d bad=%d skip=%d %.0fs" % (i, len(holes), ok, bad, skip, time.time() - t0), flush=True)
    print("FETCH DONE ok=%d bad=%d skip=%d" % (ok, bad, skip), flush=True)


def parse(work, holes):
    stub = types.ModuleType("bse_headers")
    stub.UA = UA
    stub.HEADERS = {}
    stub.CURL_ARGS = []
    stub.is_bse = lambda u: False
    stub.complete = lambda r: r
    sys.modules["bse_headers"] = stub
    cc = types.ModuleType("curl_cffi")
    cc.requests = types.SimpleNamespace(get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in parse")))
    sys.modules["curl_cffi"] = cc
    sys.modules["curl_cffi.requests"] = cc.requests
    sys.path.insert(0, HERE)
    import fetch_shp_bse_aspx as A

    A.CACHE_ONLY = True
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    neigh = {
        (s, qe): v[1]
        for s, qs in hist.items()
        if not s.startswith("_") and isinstance(qs, dict)
        for qe, v in qs.items()
        if isinstance(v, list) and len(v) > 1 and v[1] is not None
    }
    props = {}
    rej = {}
    import collections

    st = collections.Counter()
    for s, qe, code in holes:
        if qe in (hist.get(s) or {}):
            st["already in store"] += 1
            continue
        fr = {"sym": s, "qe": qe, "code": int(code), "qtrid": qtrid(qe), "bname": "", "lname": ""}
        status, cell, det = A.cell_of(fr, work, neigh)
        st[status] += 1
        if status == "ok":
            props.setdefault(s, {})[qe] = cell
        else:
            rej[f"{s}|{qe}"] = f"{status}: {det}"
    json.dump(props, open(os.path.join(work, "proposals.json"), "w"), indent=1)
    json.dump(rej, open(os.path.join(work, "rejects.json"), "w"), indent=1)
    print("parse:", dict(st), "| cells ok:", sum(len(v) for v in props.values()))


def write(work, note):
    props = json.load(open(os.path.join(work, "proposals.json")))
    p = os.path.join(HERE, "shp_fill_bse_aspx.json.gz")
    led = json.load(gzip.open(p, "rt", encoding="utf-8"))
    fills = led.setdefault("fills", {})
    n = skip = 0
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    for s, qs in props.items():
        for qe, cell in qs.items():
            if qe in (hist.get(s) or {}) or qe in (fills.get(s) or {}):
                skip += 1
                continue
            fills.setdefault(s, {})[qe] = cell
            n += 1
    led.setdefault("_meta", {})["s164i"] = note
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(led, fh, separators=(",", ":"))
    print("write: %d cells added, %d skipped (store or ledger already has the quarter)" % (n, skip))


if __name__ == "__main__":
    st, work = sys.argv[1], os.path.expanduser(sys.argv[2])
    if st == "fetch":
        fetch(work, json.load(open(sys.argv[3])), alt="--alt" in sys.argv)
    elif st == "parse":
        parse(work, json.load(open(sys.argv[3])))
    elif st == "write":
        write(work, " ".join(sys.argv[3:]))

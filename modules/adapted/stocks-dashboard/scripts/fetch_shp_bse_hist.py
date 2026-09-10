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
"""Fill FII/DII (SHP) holes for point-in-time Nifty-500 members from BSE's XBRL, NEWEST QUARTER FIRST.

Rebuilt 2026-08-07 (the 2026-08-02 original was never committed — only its ledger was).
Route: api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode=<code> lists every quarter;
rows with a REAL `XbrlFile` (Jun-2016 onward) carry an `xbrlurl` that parse_shp() reads unmodified.

⚠️ `xbrlurl` IS TRUTHY WHEN THERE IS NO FILE — pre-2016 rows return the bare prefix "/XBRL1/" with
an empty XbrlFile. Gate on XbrlFile, never on xbrlurl (runbook §22f).

Writes a LEDGER (never shp_history directly — one writer rule, §22): scripts/shp_fill_n500_gaps.json.gz
{"_meta": {...}, "fills": {SYM: {QE: [prom,fii,dii,mf,ins,sub,nsh|None,"scripcode:qtrid"]}}}
applied fill-only by fetch_shareholding.apply_bse_hist_ledger().

  python3 -X utf8 scripts/fetch_shp_bse_hist.py                # every gap, 2026 -> backwards
  python3 -X utf8 scripts/fetch_shp_bse_hist.py --years 2026   # one year
  python3 -X utf8 scripts/fetch_shp_bse_hist.py --from-qe 2020-03-31
Resumable: re-running skips everything already in the ledger and every (sym,qe) proven absent.
"""
import argparse
import collections
import gzip
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fetch_shareholding as FS  # parse_shp / parse_shares — the SAME parser the live pipeline uses

LEDGER = os.path.join(HERE, "shp_fill_n500_gaps.json.gz")
MISSES = os.path.join(HERE, "_shp_bse_absent.json")  # (sym,qe) proven to have no BSE filing — skip on resume
CACHE = os.path.join(HERE, "_shp_bse_cache")  # per-scripcode quarter lists (gitignored)
MEMB = os.path.join(HERE, "indices_history.json")
RMAPP = os.path.join(HERE, "_rename_map.json")
SCRIPS = os.path.join(HERE, "bse_scrips.json")
FULLSCRIP = os.path.join(CACHE, "_all_scrips.json")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
HDRS = {"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Accept": "application/json"}
THREADS = 5
FLUSH_EVERY = 60
QMON = {"March": "-03-31", "June": "-06-30", "September": "-09-30", "December": "-12-31"}
FIRST_QE = "2016-06-30"  # BSE's earliest real XBRL (measured: 40/40 at Jun-16, 3/40 Mar-16, 0/40 Dec-15)


try:
    from curl_cffi import requests as _cr
except Exception:
    _cr = None


def get(url, tries=4, timeout=45):
    """⚠️ Akamai fingerprints the client on /XBRL1/: plain urllib gets a 404 on the very file curl
    serves 200. curl_cffi impersonate=chrome is the only reliable transport (same lesson as the
    Wayback harvest) — urllib stays as a fallback for the API host, which is not fussy."""
    last = None
    for i in range(tries):
        try:
            if _cr is not None:
                r = _cr.get(
                    url, headers={"Referer": "https://www.bseindia.com/"}, impersonate="chrome", timeout=timeout
                )
                if r.status_code == 200:
                    return r.content
                last = Exception("HTTP %d" % r.status_code)
                if r.status_code == 404 and i >= 1:
                    raise last
            else:
                return urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=timeout).read()
        except Exception as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def xbrl_url(r):
    """The row's XML. `xbrlurl` points at a rendered _SP.html for recent quarters and at the raw
    .xml for older ones — always prefer the file name, which is the XML either way."""
    f = (r.get("XbrlFile") or "").strip()
    u = (r.get("xbrlurl") or "").strip()
    if u.lower().endswith(".xml"):
        return "https://www.bseindia.com" + u
    return "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + f


# ---------------------------------------------------------------- membership + current holdings
def load_json(p):
    return json.load(open(p, encoding="utf-8"))


RMAP = load_json(RMAPP)


def norm(s):
    s = str(s).strip().upper()
    seen = set()
    while s in RMAP and s not in seen and RMAP[s] != s:
        seen.add(s)
        s = RMAP[s]
    return s


def member_snaps():
    ih = load_json(MEMB)
    return sorted(
        (s["effectiveDate"], [norm(x) for x in s["symbols"] if not str(x).upper().startswith("DUMMY")])
        for s in ih["Nifty 500"]
    )


def members_asof(snaps, qe):
    best = []
    for ed, syms in snaps:
        if ed <= qe:
            best = syms
        else:
            break
    return best


def quarter_ends(first, last):
    out = []
    for y in range(int(first[:4]), int(last[:4]) + 1):
        for suf in ("-03-31", "-06-30", "-09-30", "-12-31"):
            q = "%d%s" % (y, suf)
            if first <= q <= last:
                out.append(q)
    return out


# ---------------------------------------------------------------- scripcode resolution
def clean_name(n):
    n = str(n or "").upper()
    for junk in (
        "LIMITED",
        "LTD.",
        "LTD",
        "(INDIA)",
        "INDIA",
        "CORPORATION",
        "CORP",
        "COMPANY",
        "CO.",
        "&",
        ".",
        ",",
        "-$",
        "PVT",
        "PRIVATE",
    ):
        n = n.replace(junk, " ")
    return " ".join(n.split())


def build_codemap(hist_names):
    """symbol -> scripcode. Live master FIRST, then the FULL list (status= blank, which is the only
    way delisted/suspended names appear at all — our own builder hardcodes status=Active), then name."""
    cmap = {}
    try:
        for k, v in load_json(SCRIPS)["by_id"].items():
            cmap.setdefault(norm(k), int(v))
            cmap.setdefault(str(k).upper(), int(v))
    except Exception as e:
        print(f"WARN bse_scrips.json unusable: {e}")

    ovr = os.path.join(HERE, "_shp_scripcode_override.json")
    if os.path.exists(ovr):
        try:
            for k, v in load_json(ovr).items():
                if not k.startswith("_"):
                    cmap[norm(k)] = int(v)
                    cmap[str(k).upper()] = int(v)
        except Exception as e:
            print(f"WARN scripcode override unusable: {e}")

    if os.path.exists(FULLSCRIP):
        full = load_json(FULLSCRIP)
    else:
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
            "?Group=&Scripcode=&industry=&segment=Equity&status="
        )
        full = json.loads(get(url, timeout=90))
        os.makedirs(CACHE, exist_ok=True)
        json.dump(full, open(FULLSCRIP, "w"))
    print("BSE scrip master: %d rows (%s)" % (len(full), dict(collections.Counter(r.get("Status") for r in full))))

    by_name = {}
    for r in full:
        try:
            cd = int(r["SCRIP_CD"])
        except Exception:
            continue
        sid = str(r.get("scrip_id") or "").strip().upper()
        if sid:
            cmap.setdefault(sid, cd)
            cmap.setdefault(norm(sid), cd)
        by_name.setdefault(clean_name(r.get("Scrip_Name")), cd)
    return cmap, by_name


def resolve(sym, cmap, by_name, hist_names):
    for k in (sym, norm(sym)):
        if k in cmap:
            return cmap[k]
    nm = clean_name(hist_names.get(sym) or hist_names.get(norm(sym)) or "")
    if nm and nm in by_name:
        return by_name[nm]
    if nm:
        hits = [c for n, c in by_name.items() if n.startswith(nm + " ") or n == nm]
        if len(hits) == 1:
            return hits[0]
    return None


# ---------------------------------------------------------------- BSE quarter list
_locks = collections.defaultdict(threading.Lock)


def quarter_list(code):
    os.makedirs(CACHE, exist_ok=True)
    cf = os.path.join(CACHE, "q_%d.json" % code)
    with _locks[code]:
        if os.path.exists(cf) and os.path.getsize(cf) > 120:
            try:
                return json.load(open(cf))["Table"]
            except Exception:
                pass
        raw = get("https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode=%d" % code)
        open(cf, "wb").write(raw)
        return json.loads(raw).get("Table", [])


def qe_of(qtr):
    p = str(qtr or "").split()
    if len(p) == 2 and p[0] in QMON and p[1].isdigit():
        return p[1] + QMON[p[0]]
    return None


def row_for(rows, qe):
    """Newest real filing for that quarter-end. ⚠ XbrlFile, not xbrlurl (§22f)."""
    cand = [r for r in rows if qe_of(r.get("qtr")) == qe and (r.get("XbrlFile") or "").strip()]
    if not cand:
        return None
    cand.sort(key=lambda r: r.get("revised_date_time") or r.get("filing_date_time") or "")
    return cand[-1]


def iso_day(s):
    s = str(s or "")
    return s[:10] if len(s) >= 10 and s[4] == "-" else ""


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="", help="comma list, e.g. 2026,2025 (default: all, newest first)")
    ap.add_argument("--from-qe", default=FIRST_QE)
    ap.add_argument("--limit", type=int, default=0, help="stop after N cells (smoke test)")
    ap.add_argument("--threads", type=int, default=THREADS)
    # §22j PRECISION REFRESH: the opposite selection to a gap fill — target cells that ALREADY
    # EXIST but were parsed off the filer's 2dp percentage, and re-read them from the same BSE
    # XBRL so parse_shp recomputes them from share counts. Its own ledger + absent list so a
    # refine run can never be mistaken for, or pollute, the gap-fill ledger.
    ap.add_argument(
        "--refine", action="store_true", help="re-read cells that exist but are 2dp-only, into shp_refine_4dp.json.gz"
    )
    a = ap.parse_args()

    global LEDGER, MISSES
    if a.refine:
        LEDGER = os.path.join(HERE, "shp_refine_4dp.json.gz")
        MISSES = os.path.join(HERE, "_shp_refine_absent.json")

    hist = FS.load_hist()
    FS.apply_bse_hist_ledger(hist)  # what we'd have after the existing ledgers merge
    names = hist.get("_names", {})
    have = collections.defaultdict(dict)
    keyfor = {}  # normed symbol -> the shp_history key to write under
    for k, v in hist.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        n = norm(k)
        have[n].update(v)
        if n not in keyfor or len(v) > len(hist.get(keyfor[n], {})):
            keyfor[n] = k

    ledger = {"_meta": {}, "fills": {}}
    if os.path.exists(LEDGER):
        with gzip.open(LEDGER, "rt", encoding="utf-8") as fh:
            ledger = json.load(fh)
    fills = ledger.setdefault("fills", {})
    absent = {tuple(x) for x in (load_json(MISSES) if os.path.exists(MISSES) else [])}

    snaps = member_snaps()
    last_q = max(q for q in quarter_ends("2016-06-30", "2027-12-31") if q < time.strftime("%Y-%m-%d"))
    qes = quarter_ends(a.from_qe, last_q)
    if a.years:
        keep = set(a.years.split(","))
        qes = [q for q in qes if q[:4] in keep]
    qes.sort(reverse=True)  # NEWEST FIRST — 2026, then 2025, ...

    cmap, by_name = build_codemap(names)

    todo = []
    if a.refine:
        # EVERY symbol we hold, not just point-in-time N500 members: a 2dp cell is wrong whoever
        # holds it, and the members_asof filter exists to bound a GAP hunt, not a re-read.
        def two_dp(c):
            return all(isinstance(v, (int, float)) and round(v, 2) == v for v in (c[1], c[2]))

        for qe in qes:
            for sym, qs in have.items():
                c = qs.get(qe)
                if not c or len(c) < 3 or not two_dp(c):
                    continue
                if qe in fills.get(keyfor.get(sym, sym), {}):
                    continue
                if (sym, qe) in absent:
                    continue
                todo.append((sym, qe))
        print(
            "2dp cells to re-read: %d over %d quarters (%s .. %s)"
            % (len(todo), len(qes), qes[-1] if qes else "-", qes[0] if qes else "-")
        )
    else:
        for qe in qes:
            for sym in sorted(set(members_asof(snaps, qe))):
                if qe in have.get(sym, {}):
                    continue
                if qe in fills.get(keyfor.get(sym, sym), {}):
                    continue
                if (sym, qe) in absent:
                    continue
                todo.append((sym, qe))
        print(
            "gaps to fetch: %d over %d quarters (%s .. %s)"
            % (len(todo), len(qes), qes[-1] if qes else "-", qes[0] if qes else "-")
        )
    if a.limit:
        todo = todo[: a.limit]

    unresolved = collections.Counter()
    for sym, qe in todo:
        if resolve(sym, cmap, by_name, names) is None:
            unresolved[sym] += 1
    if unresolved:
        print(
            "no BSE scripcode for %d symbols / %d cells: %s"
            % (len(unresolved), sum(unresolved.values()), ", ".join("%s(%d)" % t for t in unresolved.most_common(20)))
        )
    todo = [(s, q) for s, q in todo if resolve(s, cmap, by_name, names) is not None]

    got = skipped = errs = 0
    new_absent = []
    lock = threading.Lock()

    def work(item):
        sym, qe = item
        code = resolve(sym, cmap, by_name, names)
        try:
            rows = quarter_list(code)
        except Exception as e:
            return sym, qe, code, ("ERR", f"qlist {e!r}")
        r = row_for(rows, qe)
        if r is None:
            return sym, qe, code, ("ABSENT", "no filing on BSE")
        try:
            root = ET.fromstring(get(xbrl_url(r)))
            res = FS.parse_shp(root, qe)
        except Exception as e:
            # A listed row whose file 404s is a BSE stub, not a transport failure — it 404s on every
            # path and every retry (KARURVYSYA/SUNDARMFIN 2016-18, the whole 590xxx series). Bank it
            # as absent so resume stops re-fetching it.
            if "404" in repr(e):
                return sym, qe, code, ("ABSENT", "row listed but file 404s")
            return sym, qe, code, ("ERR", repr(e)[:120])
        if not isinstance(res, dict):
            return sym, qe, code, ("SKIP", "no-anchor/old-format")
        sub = iso_day(r.get("revised_date_time") or r.get("filing_date_time"))
        cell = [
            res["prom"],
            res["fii"],
            res["dii"],
            res["mf"],
            res["ins"],
            sub or (qe[:8] + "21"),
            res.get("nsh"),
            "%d:%s" % (code, r.get("qtrid")),
        ]
        return sym, qe, code, cell

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for fut in as_completed(futs):
            sym, qe, code, res = fut.result()
            with lock:
                if isinstance(res, list):
                    fills.setdefault(keyfor.get(sym, sym), {})[qe] = res
                    got += 1
                    if got % FLUSH_EVERY == 0:
                        flush(ledger, fills, new_absent, absent)
                        print("  ... %d/%d filled (%.0fs)" % (got, len(todo), time.time() - t0))
                elif res[0] == "ABSENT":
                    new_absent.append((sym, qe))
                    skipped += 1
                    if skipped <= 15:
                        print(f"  ABSENT {sym} {qe} (sc {code})")
                else:
                    errs += 1
                    if errs <= 15:
                        print(f"  {res[0]} {sym} {qe}: {res[1]}")

    flush(ledger, fills, new_absent, absent)
    print(
        "\nDONE in %.0f min: +%d cells, %d absent at BSE, %d errors/skips"
        % ((time.time() - t0) / 60.0, got, skipped, errs)
    )
    print(
        "ledger: %s (%d symbols, %d cells)"
        % (os.path.basename(LEDGER), len(fills), sum(len(v) for v in fills.values()))
    )


def flush(ledger, fills, new_absent, absent):
    ledger["_meta"] = {
        "source": "BSE SHPQNewFormat XBRL",
        "built": time.strftime("%Y-%m-%d %H:%M IST"),
        "symbols": len(fills),
        "cells": sum(len(v) for v in fills.values()),
        "note": "point-in-time N500 gap fill, newest quarter first; provenance = scripcode:qtrid",
    }
    tmp = LEDGER + ".tmp%d" % os.getpid()
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(ledger, fh, separators=(",", ":"))
    os.replace(tmp, LEDGER)
    if new_absent:
        absent.update(new_absent)
        del new_absent[:]
        json.dump(sorted(absent), open(MISSES, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()

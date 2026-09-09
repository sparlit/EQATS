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
"""FII/DII backfill from NSE's OWN archived full category-wise shareholding page (Wayback, 2002-2006):
  http://www.nseindia.com/marketinfo/companyinfo/eod/shareholdingdetails.jsp?seg_num=<n>&symbol=<ERA SYMBOL>
Found 2026-09-05 (runbook §127g). The page prints Promoter's Holding / Institutional Investors (MF&UTI, Banks-FIs-
Insurance-Govt lump, FIIs) / Others with SHARES and %, plus GRAND TOTAL and "As on dd-Mon-yyyy" — the 1997 SEBI format,
from the exchange that listed the NSE-only era companies BSE never carried (LAKSHVILAS, the 590xxx cohort, KTKBANK...).
The URL carries no date (seg_num only), so every capture must be fetched and the as-on read from the page.

Stages (all write ONLY under --dir; read-only on the repo):
  python3 fetch_shp_nse_shpdetails.py plan  --dir D      # missing N500 member-quarters 2001-03..2006-12 x captures -> D/plan.json
  python3 fetch_shp_nse_shpdetails.py fetch --dir D [--workers 4]   # Wayback id_ fetch, resumable (skips files on disk)
  python3 fetch_shp_nse_shpdetails.py apply --dir D      # parse -> cells; OVERLAP GATE vs stored (<=0.11pp fii/dii)
                                                          # -> D/nse_result.json (+ D/shp_fill_nse_shpdetails.json.gz of MISSING cells only)
Derivation = fetch_shp_bse_aspx Flag=Old: dii = mf + lump; ins None (inside the lump); inst recon <= 0.15; absent FIIs row
-> 0 only when the Sub Total proves it; 4dp from share counts (base = GRAND TOTAL shares); fii 0.00 beside a stored
neighbour > 1% refused (seam class). Provenance nsewb:<ts>:<seg_num>; sub = QE+21d convention -> served UN-DATED (§120).
Wayback refuses connections intermittently (2026-09-05: 12/12 "Couldn't connect" for an hour) — the fetcher retries
briefly and leaves failed captures for the next run; never conclude absence from a failed fetch.
"""

import contextlib
import datetime
import html as H
import json
import os
import re
import subprocess
import sys
import time

MON = {
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


def cells(html):
    t = re.sub(r"<[^>]+>", "\x01", html)
    cs = [re.sub(r"[\s\xa0]+", " ", H.unescape(c)).strip() for c in t.split("\x01")]
    return [c for c in cs if c]


def parse(html):
    cs = cells(html)
    out = {"name": None, "sym": None, "asOn": None, "rows": []}
    for i, c in enumerate(cs):
        if c == "Company" and i + 1 < len(cs):
            out["name"] = cs[i + 1]
        if c == "NSE Symbol" and i + 1 < len(cs):
            out["sym"] = cs[i + 1]
        m = re.match(r"As on (\d{2})-([A-Za-z]{3})-(\d{4})", c)
        if m:
            out["asOn"] = "%s-%02d-%s" % (m.group(3), MON[m.group(2)], m.group(1))

    def nums_at(i):
        n = []
        for c2 in cs[i + 1 : i + 4]:
            c3 = c2.replace(",", "").strip()
            if re.fullmatch(r"-?\d+(?:\.\d+)?", c3):
                n.append(float(c3))
            else:
                break
        return n

    sec = None
    grand = None
    subs = {}
    for i, c in enumerate(cs):
        if re.search(r"Promoter'?s Holding", c, re.IGNORECASE):
            sec = "prom"
            continue
        if re.search(r"Institutional Investors", c, re.IGNORECASE):
            sec = "inst"
            continue
        if re.fullmatch(r"Others", c, re.IGNORECASE):
            sec = "oth"
            continue
        n = nums_at(i)
        if len(n) >= 2:
            lab = c
            if re.fullmatch(r"Sub Total", c, re.IGNORECASE) and sec:
                subs[sec] = (n[0], n[1])
                continue
            if re.search(r"GRAND TOTAL", c, re.IGNORECASE):
                grand = (n[0], n[1])
                continue
            out["rows"].append((sec, lab, n[0], n[1]))
    out["subs"] = subs
    out["grand"] = grand
    return out


def cell_of(p, neigh=None, sym=None):
    """-> (status, cell, detail). Same gates as fetch_shp_bse_aspx Flag=Old: dii = mf + lump; ins None;
    inst recon <=0.15; fii absent -> 0 only if proven by the subtotal; 4dp from share counts (base = grand total)."""
    if not p["asOn"]:
        return ("absent", None, "no as-on date")
    r = {}
    for sec, lab, sh, pc in p["rows"]:
        L = lab.lower()
        if sec == "inst":
            if "mutual" in L:
                r["mf"] = (sh, pc)
            elif L.startswith("fii"):
                r["fii"] = (sh, pc)
            elif "banks" in L or "financial inst" in L or "insurance" in L:
                r["lump"] = (sh, pc)
    base = p["grand"][0] if p["grand"] and p["grand"][0] > 0 else None

    def pct(k):
        if k not in r:
            return None
        sh, pc = r[k]
        if base and sh is not None:
            return sh / base * 100.0
        return pc

    prom = None
    if "prom" in p["subs"]:
        sh, pc = p["subs"]["prom"]
        prom = (sh / base * 100.0) if base else pc
    else:
        # promoter-less filer: the two non-promoter subtotals close to 100
        s = [p["subs"].get("inst"), p["subs"].get("oth")]
        if all(s) and 99.5 <= s[0][1] + s[1][1] <= 100.5:
            prom = 0.0
    if prom is None:
        return ("no-prom", None, "promoter subtotal absent")
    mf = pct("mf") or 0.0
    lump = pct("lump") or 0.0
    fii = pct("fii")
    inst = p["subs"].get("inst")
    inst_p = inst[0] / base * 100.0 if (inst and base) else (inst[1] if inst else None)
    if fii is None:
        if inst_p is not None and abs(inst_p - (mf + lump)) <= 0.15:
            fii = 0.0
        else:
            return ("no-fii", None, "FIIs row absent, residual unproven")
    dii = mf + lump
    if inst_p is not None and abs((mf + lump + fii) - inst_p) > 0.15:
        return ("recon", None, f"inst recon {mf + lump + fii:.2f} vs {inst_p:.2f}")
    if not (0 <= prom <= 100 and 0 <= fii <= 100 and 0 <= dii <= 100):
        return ("range", None, "out of range")
    # self-check: pct from shares must reproduce the printed pct within 0.05pp on every inst row
    if base:
        for k, (sh, pc) in r.items():
            if abs(sh / base * 100.0 - pc) > 0.05:
                return (
                    "base",
                    None,
                    f"share/base does not reproduce printed {k} ({sh / base * 100.0:.3f} vs {pc:.2f})",
                )
    qe = p["asOn"]
    if qe[5:7] not in ("03", "06", "09", "12") or qe[8:] not in ("30", "31"):
        return ("offcycle", None, f"as-on {qe} is not a quarter-end")
    if fii == 0.0 and neigh and sym:
        y, m = int(qe[:4]), int(qe[5:7])
        nb = []
        for step in (-1, 1):
            mm = m + 3 * step
            yy = y + (mm - 1) // 12
            mm = (mm - 1) % 12 + 1
            k = (sym, "%04d-%02d-%s" % (yy, mm, {3: "31", 6: "30", 9: "30", 12: "31"}[mm]))
            if k in neigh:
                nb.append(neigh[k])
        if any(v > 1.0 for v in nb):
            return ("zero-vs-neighbour", None, f"fii 0.00 beside stored {max(nb):.2f}")
    sub = (datetime.date(int(qe[:4]), int(qe[5:7]), int(qe[8:])) + datetime.timedelta(days=21)).isoformat()
    return ("ok", [round(prom, 4), round(fii, 4), round(dii, 4), round(mf, 4), None, sub, None, "nsewb"], qe)


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _norm_fn():
    rmap = json.load(open(os.path.join(HERE, "_rename_map.json")))

    def norm(s):
        seen = set()
        while s in rmap and s not in seen and rmap[s] != s:
            seen.add(s)
            s = rmap[s]
        return s

    return norm


def cmd_plan(D):
    import collections

    norm = _norm_fn()
    ih = json.load(open(os.path.join(HERE, "indices_history.json")))
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    have = collections.defaultdict(dict)
    for k, v in hist.items():
        if not k.startswith("_") and isinstance(v, dict):
            have[norm(k)].update(v)
    snaps = sorted(
        (x["effectiveDate"], [norm(y) for y in x["symbols"] if not y.startswith("DUMMY")]) for x in ih["Nifty 500"]
    )

    def members(qe):
        best = []
        for ed, syms in snaps:
            if ed <= qe:
                best = syms
            else:
                break
        return best

    qes = ["%d%s" % (y, s) for y in range(2001, 2007) for s in ("-03-31", "-06-30", "-09-30", "-12-31")]
    missing = [(s, q) for q in qes for s in members(q) if q not in have.get(s, {})]
    cdx = json.load(open(os.path.join(HERE, "nse_shpdetails_cdx.json")))["rows"]
    caps = collections.defaultdict(list)
    for ts, url, sym in cdx:
        caps[norm(sym)].append((ts, url))
    ms = {s for s, q in missing}
    fetch = {s: caps[s] for s in ms if s in caps}
    json.dump({"missing": missing, "fetch": fetch}, open(os.path.join(D, "plan.json"), "w"))
    print(
        "missing member-quarters 2001-03..2006-12:",
        len(missing),
        "symbols",
        len(ms),
        "| with captures",
        len(fetch),
        "captures",
        sum(len(v) for v in fetch.values()),
    )


def cmd_fetch(D, workers):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    plan = json.load(open(os.path.join(D, "plan.json")))["fetch"]
    jobs = [(s, ts, url) for s, caps in plan.items() for ts, url in caps]
    od = os.path.join(D, "pages")
    os.makedirs(od, exist_ok=True)
    lk = threading.Lock()
    done = [0, 0, 0]

    def one(j):
        s, ts, url = j
        m = re.search(r"seg_num=(\d+)", url)
        seg = m.group(1) if m else "x"
        fn = os.path.join(od, "{}_{}_{}.html".format(ts, s.replace("&", "_"), seg))
        if os.path.exists(fn) and os.path.getsize(fn) > 800:
            with lk:
                done[2] += 1
            return
        for a in range(8):
            subprocess.run(
                ["curl", "-s", "-m", "90", "-A", "Mozilla/5.0", f"https://web.archive.org/web/{ts}id_/{url}", "-o", fn]
            )
            try:
                t = open(fn, errors="replace").read()
            except Exception:
                t = ""
            if len(t) > 800 and "Temporarily Offline" not in t and "Shareholding" in t:
                with lk:
                    done[0] += 1
                break
            time.sleep(2 if a < 3 else 20)
        else:
            with lk:
                done[1] += 1
            with contextlib.suppress(Exception):
                os.remove(fn)
        with lk:
            n = sum(done)
            if n % 50 == 0:
                print("progress", n, "ok", done[0], "fail", done[1], "cached", done[2], flush=True)
        time.sleep(0.3)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    print("fetch done: ok", done[0], "fail", done[1], "cached", done[2])


def cmd_apply(D):
    import collections
    import glob
    import gzip

    norm = _norm_fn()
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    have = collections.defaultdict(dict)
    neigh = {}
    for k, v in hist.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        have[norm(k)].update(v)
        for qe, c in v.items():
            if isinstance(c, list) and len(c) > 1 and c[1] is not None:
                neigh[(norm(k), qe)] = c[1]
    cells = {}
    stats = collections.Counter()
    rej = {}
    for fn in sorted(glob.glob(os.path.join(D, "pages", "*.html"))):
        ts, sym, seg = os.path.basename(fn)[:-5].split("_", 2)
        p = parse(open(fn, errors="replace").read())
        s = norm(sym.replace("_", "&"))
        # the page prints the ERA symbol (MIRCELECTR); the file key is the normed modern key (ONIDA) — compare in norm space
        if p["sym"] and norm(p["sym"].upper()) != s:
            stats["sym-mismatch"] += 1
            continue
        st, cell, det = cell_of(p, neigh, s)
        stats[st] += 1
        if st != "ok":
            rej["{}|{}|{}".format(s, p.get("asOn"), ts)] = f"{st}: {det}"
            continue
        qe = det
        cell[7] = f"nsewb:{ts}:{seg}"
        prev = cells.get((s, qe))
        if prev and prev[:4] != cell[:4]:
            stats["dup-disagree"] += 1
        cells[(s, qe)] = cell
    print("parsed", dict(stats), "| cells", len(cells))
    ov = []
    for (s, qe), c in cells.items():
        o = have.get(s, {}).get(qe)
        if o:
            ov.append((abs(c[1] - o[1]), abs(c[2] - o[2]), s, qe, c[1], o[1], c[2], o[2]))
    ov.sort(reverse=True)
    bad = [d for d in ov if d[0] > 0.11 or d[1] > 0.11]
    print("OVERLAP GATE: %d stored too, %d disagree beyond 0.11pp" % (len(ov), len(bad)))
    for d in (bad or ov[:5])[:12]:
        print("   dFII={:.2f} dDII={:.2f} {} {} nse={:.2f} stored={:.2f} | dii {:.2f} vs {:.2f}".format(*d))
    # SCOPE (user instruction 2026-09-05 ~13:30 IST, relayed to every session: "work only on nifty 500 stocks"):
    # fill ONLY point-in-time Nifty 500 member-quarters — the engine's membersAsOf rule (last snapshot at or
    # before the quarter-end). A parsed cell on a non-member quarter is kept in nse_result.json for the record
    # but never written to the ledger.
    ih = json.load(open(os.path.join(HERE, "indices_history.json")))
    snaps = sorted(
        (x["effectiveDate"], {norm(y) for y in x["symbols"] if not y.startswith("DUMMY")}) for x in ih["Nifty 500"]
    )

    def members(qe):
        best = set()
        for ed, syms in snaps:
            if ed <= qe:
                best = syms
            else:
                break
        return best

    fills = {}
    skipped_nonmember = 0
    for (s, qe), c in cells.items():
        if qe in have.get(s, {}):
            continue
        if s not in members(qe):
            skipped_nonmember += 1
            continue
        fills.setdefault(s, {})[qe] = c
    n = sum(len(v) for v in fills.values())
    print(
        "FILLS (missing in store, N500 member at the quarter-end):",
        n,
        "syms",
        len(fills),
        "| parsed-but-non-member skipped",
        skipped_nonmember,
    )
    json.dump({"overlap": ov, "rejects": rej}, open(os.path.join(D, "nse_result.json"), "w"), indent=0, default=str)
    with gzip.open(os.path.join(D, "shp_fill_nse_shpdetails.json.gz"), "wt", encoding="utf-8") as fh:
        json.dump(
            {
                "_built": "fetch_shp_nse_shpdetails apply (NSE Wayback shareholdingdetails.jsp, runbook §127g)",
                "fills": fills,
            },
            fh,
        )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "fetch", "apply"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)
    {"plan": lambda: cmd_plan(a.dir), "fetch": lambda: cmd_fetch(a.dir, a.workers), "apply": lambda: cmd_apply(a.dir)}[
        a.cmd
    ]()

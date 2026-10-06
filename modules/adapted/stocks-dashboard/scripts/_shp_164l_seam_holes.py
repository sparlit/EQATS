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
"""§164l — Dec-2015 / Mar-2016 quarter HOLES whose BSE page prints the FII row inside an unlabelled lump (§164i refused them:
fii 0 beside the neighbours). Cell = fetch_shp_bse_aspx.cell_of's own reading of the page (promoter, dii, mf, ins, holders)
with fii replaced by the §160 seam reconstruction (_shp_aspx_rowfix.reconstruct: the page's standard foreign rows + the
>1% holders table's FII/FPI lump or its FII/FPI-prefixed / documented-foreign named holders). Accepted only inside the
neighbouring stored quarters' range +- 3 pp; everything else is held, never estimated. §164p (2026-09-27): the shares moved
to fii are taken out of dii (_shp_164p_seam_base.seam_correct) — the first run left them in both (13 cells repaired by cell_fix).
Transport: scripts/bse_headers.py (honest headers). Stages (work dir argv[2]):
  fetch <work> <holes.json>   the >1% holders tables (shpperent.aspx) for qtrid 88 AND 89 of each hole's company, cached
  parse <work> <holes.json>   offline: cell_of (CACHE_ONLY, no neighbour gate) + reconstruct -> proposals.json / held.json;
                              accepted only when the FII total is READ (no lump on the page, the table's FII category row, or the
                              whole-block rule) AND inside the neighbours' range +- 3 pp
  write <work> <note...>      fill-only into scripts/shp_fill_seam_aspx.json.gz
holes.json: [[sym, 'YYYY-MM-DD', bse_code], ...]; the main pages come from ~/stocks-cache/shp/holes/cache (§164i)."""
import gzip
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PAGES = os.path.expanduser(
    "~/stocks-cache/shp/holes"
)  # fetch_shp_bse_aspx cache dir (cache/<code>_<q>_<flag>.html.gz)
LISTS = os.path.expanduser("~/stocks-cache/shp/bse_all")


def qtrid(qe):
    y = int(qe[:4])
    m = int(qe[5:7])
    return (y - 2001) * 4 + {3: 29, 6: 30, 9: 31, 12: 32}[m]


def fetch(work, holes):
    os.makedirs(os.path.join(work, "shpperent"), exist_ok=True)
    ok = bad = skip = 0
    for code in sorted({int(c) for s, q, c in holes}):
        for q in (88, 89):
            p = os.path.join(work, "shpperent", "%d_%d.html.gz" % (code, q))
            if os.path.exists(p):
                skip += 1
                continue
            u = (
                "https://www.bseindia.com/corporates/shpperent.aspx?scripcd=%d&qtrid=%d&CompName=X&QtrName=X"
                % (code, q)
            )
            body = b""
            for a in range(3):
                try:
                    body = urllib.request.urlopen(urllib.request.Request(u), timeout=60).read()
                    break
                except Exception:
                    time.sleep(4 * (a + 1))
            if len(body) > 2000:
                with gzip.open(p + ".tmp", "wt", encoding="utf-8") as fh:
                    fh.write(body.decode("utf-8", "ignore"))
                os.replace(p + ".tmp", p)
                ok += 1
            else:
                bad += 1
            time.sleep(1.0)
    print("FETCH DONE ok=%d bad=%d skip=%d" % (ok, bad, skip), flush=True)


def parse(work, holes):
    import types

    cc = types.ModuleType("curl_cffi")
    cc.requests = types.SimpleNamespace(
        get=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in parse"))
    )
    sys.modules["curl_cffi"] = cc
    sys.modules["curl_cffi.requests"] = cc.requests
    os.makedirs(os.path.join(work, "aspx_pages"), exist_ok=True)
    if not os.path.exists(os.path.join(work, "generic_rows.json")):
        json.dump([], open(os.path.join(work, "generic_rows.json"), "w"))
    for s, qe, code in holes:
        src = os.path.join(PAGES, "cache", "%d_%d_New.html.gz" % (int(code), qtrid(qe)))
        dst = os.path.join(work, "aspx_pages", "%d_%d.html.gz" % (int(code), qtrid(qe)))
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    os.environ["DII_ROWFIX_WORK"] = work
    os.environ.setdefault("DII_ROWFIX_LISTS", LISTS)
    import _shp_aspx_rowfix as A
    import _shp_dii_rowfix as D
    import fetch_shp_bse_aspx as FA

    FA.CACHE_ONLY = True
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    verdicts = D.load_verdicts()
    props = {}
    held = {}
    for s, qe, code in holes:
        code = int(code)
        q = qtrid(qe)
        if qe in (hist.get(s) or {}):
            held[f"{s}|{qe}"] = "already in store"
            continue
        st, cell, det = FA.cell_of(
            {"sym": s, "qe": qe, "code": code, "qtrid": q, "bname": "", "lname": ""}, PAGES, None
        )
        if st != "ok":
            held[f"{s}|{qe}"] = f"page parse: {st} {det}"
            continue
        lp = os.path.join(LISTS, s + ".json")
        rows = []
        if os.path.exists(lp):
            t = json.load(open(lp))
            rows = t.get("Table") if isinstance(t, dict) else t
        ctx = D.SymCtx(s, rows, verdicts)
        try:
            r, why = A.reconstruct(
                s, code, q, ctx, verdicts, known_foreign=A.sibling_foreign_names(code)
            )
        except Exception as e:
            r, why = None, f"reconstruct error {e!r}"
        if r is None:
            held[f"{s}|{qe}"] = f"no reconstruction: {why}"
            continue
        qs = sorted(hist.get(s) or {})
        prv = [x for x in qs if x < qe][-1:]
        nxt = [x for x in qs if x > qe][:1]
        nb = [hist[s][x][1] for x in prv + nxt if hist[s][x][1] is not None]
        if len(nb) < 2:
            held[f"{s}|{qe}"] = "fewer than two neighbours to bound it (t_fii {:.2f})".format(
                r["t_fii"]
            )
            continue
        lo, hi = min(nb) - 3.0, max(nb) + 3.0
        if not (lo <= r["t_fii"] <= hi):
            held[f"{s}|{qe}"] = (
                "reconstructed fii {:.2f} outside neighbours {:.2f}..{:.2f} +-3".format(
                    r["t_fii"], min(nb), max(nb)
                )
            )
            continue
        # completeness: the >1% table lists only large holders, so FII hidden in the page's Any-Others lump is readable only
        # when that table prints the FII/FPI CATEGORY row (lump-fii) or the whole-block rule holds; with no lump on the page
        # the standard rows are the whole FII. Named >1% holders alone under-count (VRLLOG / SOMANYCERA / KWALITY Mar-16).
        kinds = {e[0] for e in r["ev"]}
        if not (r["lumps"] < 0.05 or "lump-fii" in kinds or r.get("whole_block")):
            held[f"{s}|{qe}"] = (
                "incomplete: page lump {:.2f} with no FII category row in the >1% table (named holders only would under-count; t_fii {:.2f})".format(
                    r["lumps"], r["t_fii"]
                )
            )
            continue
        # §164p: take the shares moved to fii OUT of dii (cell_of's dii already holds the institutional Any-Others block)
        from _shp_164p_seam_base import seam_correct

        new, why = seam_correct(
            list(cell),
            r,
            gzip.open(
                os.path.join(work, "aspx_pages", "%d_%d.html.gz" % (code, q)),
                "rt",
                encoding="utf-8",
            ).read(),
        )
        if new is None:
            held[f"{s}|{qe}"] = f"seam_correct: {why}"
            continue
        new[7] = str(new[7]) + "+seam164l"
        props.setdefault(s, {})[qe] = new
        props[s][qe + "#ev"] = [str(e) for e in r["ev"]][:12]
    json.dump(props, open(os.path.join(work, "proposals.json"), "w"), indent=1)
    json.dump(held, open(os.path.join(work, "held.json"), "w"), indent=1)
    import collections

    print(
        "parse: %d cells ok, %d held"
        % (sum(1 for s in props for q in props[s] if "#" not in q), len(held)),
        collections.Counter(v.split(":")[0].split(" (")[0] for v in held.values()),
    )


def write(work, note):
    props = json.load(open(os.path.join(work, "proposals.json")))
    p = os.path.join(HERE, "shp_fill_seam_aspx.json.gz")
    raw = gzip.open(p, "rt", encoding="utf-8").read()
    led = json.loads(raw)
    fills = led.setdefault("fills", {})
    hist = json.load(open(os.path.join(HERE, "shp_history.json")))
    n = skip = 0
    for s, qs in props.items():
        for qe, cell in qs.items():
            if "#" in qe:
                continue
            if qe in (hist.get(s) or {}) or qe in (fills.get(s) or {}):
                skip += 1
                continue
            fills.setdefault(s, {})[qe] = cell
            n += 1
    led["_built"] = str(led.get("_built", "")) + " | §164l " + note
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(led))  # the ledger's own layout: json.dumps defaults
    print("write: %d cells added, %d skipped" % (n, skip))


if __name__ == "__main__":
    st, work = sys.argv[1], os.path.expanduser(sys.argv[2])
    if st == "fetch":
        fetch(work, json.load(open(sys.argv[3])))
    elif st == "parse":
        parse(work, json.load(open(sys.argv[3])))
    elif st == "write":
        write(work, " ".join(sys.argv[3:]))

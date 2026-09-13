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
"""Fill the remaining Dec-2015 / Mar-2016 seam cells from Trendlyne's per-quarter pages.

Why this source, and why only these two quarters: Trendlyne's shareholding archive bottoms out at
Dec-2015 (verify-campaign site card, SHP_VERIFY_P1_FINDINGS §site-cards) — so it covers exactly the
seam and nothing deeper. Unlike the Wayback-MC pages, its seam pages carry a POPULATED FPI row
(KARURVYSYA Mar-2016 = 15.03 where MC prints dashes), so this both fills companies Wayback never
captured and independently corroborates the derived cells.

Method = the proven scrape-and-aggregate from the 2016-19 fill (same two hard-won rules):
  - only the FIRST "Any Other" after the institutions run is institutional; the next one ENDS it;
  - a missing FPI row means HOLD the cell, never fii=0.
Promoter = the pre-institution block sum (no BSE Table-I exists pre-2016 to anchor against — that
endpoint is measured-empty at qtrid<=89, runbook §22f).

VALIDATION before anything is written: cells where BOTH this route and the Wayback-derived ledger
have a value are compared; if the median |fii diff| on that overlap exceeds GATE_PP the whole batch
is dropped. The overlap is genuinely independent — different site, different derivation.

PACING: robots.txt on trendlyne.com sets a 10s crawl delay for ClaudeBot BY NAME; the repo honours
the site's own number (verify campaign decision). Sequential, PACE_S between requests.

  python3 -X utf8 scripts/fetch_shp_seam_trendlyne.py            # fetch + validate + write ledger
  python3 -X utf8 scripts/fetch_shp_seam_trendlyne.py --dry      # fetch + validate, write nothing
"""
import argparse
import collections
import gzip
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from curl_cffi import requests as cr

CACHE = os.path.join(HERE, "_shp_tl_cache")
os.makedirs(CACHE, exist_ok=True)
IDMAP = os.path.join(CACHE, "tl_ids.json")
LEDGER = os.path.join(HERE, "shp_fill_thirdparty.json.gz")
WAYBACK_LEDGER = os.path.join(HERE, "shp_fill_hist_2010_2016.json.gz")
SEAM_QES = ("2015-12-31", "2016-03-31")
PACE_S = 10.0  # trendlyne robots.txt crawl-delay for ClaudeBot — the site's number, honour it
GATE_PP = 1.5  # median |fii diff| vs the Wayback-derived overlap; worse -> drop the batch
H = {"Accept-Language": "en-US,en;q=0.9"}

INST_START = ("mutual fund", "foreign portfolio", "foreign institutional", "financial institutions", "insurance compan")
INST_MORE = (
    "nbfc",
    "alternate investment",
    "alternative investment",
    "venture capital",
    "provident fund",
    "pension",
    "sovereign wealth",
    "banks",
    "central government",
    "state government",
    "qualified foreign",
)
PUBLIC_MARK = (
    "individual share",
    "individuals -",
    "bodies corporate",
    "non resident",
    "non-resident",
    "trusts",
    "clearing",
    "iepf",
    "investor education",
    "key managerial",
    "relatives of",
    "overseas depositories",
    "custodian",
)


def rows_of(page):
    out = []
    for tr in re.findall(r'<tr class="\s*fw500\s*"\s*>(.*?)</tr>', page, re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
        if len(tds) < 2:
            continue
        lab = re.sub(r"\s+", " ", re.sub("<[^>]+>", "", tds[0])).strip()
        raw = re.sub(r"\s+", " ", re.sub("<[^>]+>", "", tds[1])).replace("*", "").strip()
        tag = "belonging to" in tds[1]  # trendlyne's own FII/FPI category marker
        try:
            out.append((lab, float(raw), tag))
        except ValueError:
            continue
    return out


def assemble(rs):
    labs = [r[0].lower() for r in rs]
    start = next((i for i, l in enumerate(labs) if l.startswith(INST_START)), None)
    if start is None:
        return None
    fii = dii = mf = ins = 0.0
    used_other = False
    for i in range(start, len(rs)):
        l, v, tag = rs[i]
        ll = l.lower()
        if ll.startswith(PUBLIC_MARK):
            break
        if ll.startswith("any other"):
            if used_other:
                break  # the SECOND Any Other is the public one — stop
            used_other = True
            dii += v
            continue
        if tag or ll.startswith(("foreign portfolio", "foreign institutional")):
            fii += v
        elif ll.startswith("mutual fund"):
            mf += v
            dii += v
        elif ll.startswith("insurance compan"):
            ins += v
            dii += v
        elif ll.startswith(INST_START) or ll.startswith(INST_MORE):
            dii += v
    return {
        "fii": round(fii, 2),
        "dii": round(dii, 2),
        "mf": round(mf, 2),
        "ins": round(ins, 2),
        "prom": round(sum(v for l, v, _ in rs[:start]), 2),
    }


def fetch(tid, sym, qe):
    d = f"{qe[8:10]}-{qe[5:7]}-{qe[0:4]}"
    cf = os.path.join(CACHE, f"{sym}_{qe}.html.gz")
    if os.path.exists(cf):
        with gzip.open(cf, "rt", encoding="utf-8") as fh:
            return fh.read(), True
    r = cr.get(
        "https://trendlyne.com/equity/share-holding/%d/%s/%s/x/" % (tid, sym, d),
        headers=H,
        impersonate="chrome",
        timeout=45,
    )
    if r.status_code != 200:
        return None, False
    with gzip.open(cf, "wt", encoding="utf-8") as fh:
        fh.write(r.text)
    return r.text, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    ids = json.load(open(IDMAP))["ids"]
    hist = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))
    rmap = json.load(open(os.path.join(HERE, "_rename_map.json"), encoding="utf-8"))
    ih = json.load(open(os.path.join(HERE, "indices_history.json"), encoding="utf-8"))

    def norm(s):
        s = str(s).strip().upper()
        seen = set()
        while s in rmap and s not in seen and rmap[s] != s:
            seen.add(s)
            s = rmap[s]
        return s

    snaps = sorted(
        (s["effectiveDate"], [norm(x) for x in s["symbols"] if not str(x).upper().startswith("DUMMY")])
        for s in ih["Nifty 500"]
    )

    def members(qe):
        best = []
        for ed, sy in snaps:
            if ed <= qe:
                best = sy
            else:
                break
        return best

    have = collections.defaultdict(dict)
    for k, v in hist.items():
        if not k.startswith("_") and isinstance(v, dict):
            have[norm(k)].update(v)

    wb = {}
    if os.path.exists(WAYBACK_LEDGER):
        for s, qs in json.load(gzip.open(WAYBACK_LEDGER, "rt", encoding="utf-8"))["fills"].items():
            for q, c in qs.items():
                if q in SEAM_QES:
                    wb[(norm(s), q)] = c

    todo, unmapped = [], collections.Counter()
    overlap_check = []
    for qe in SEAM_QES:
        for s in sorted(set(members(qe))):
            if qe in have.get(s, {}):
                # already covered — sample some for the overlap validation anyway
                if (s, qe) in wb and s in ids and len(overlap_check) < 60:
                    overlap_check.append((s, qe))
                continue
            if s not in ids:
                unmapped[s] += 1
                continue
            todo.append((s, qe))
    print(
        "seam gaps to try: %d ; unmapped (mostly delisted): %d symbols / %d cells ; overlap sample: %d"
        % (len(todo), len(unmapped), sum(unmapped.values()), len(overlap_check)),
        flush=True,
    )
    if unmapped:
        print("   unmapped: {}".format(", ".join(list(unmapped)[:15])), flush=True)

    results, agree = {}, []
    n = held = miss = 0
    t0 = time.time()
    for s, qe in overlap_check + todo:
        page, cached = fetch(ids[s], s, qe)
        if not cached:
            time.sleep(PACE_S)
        n += 1
        if n % 25 == 0:
            print("  ...%d/%d (%.0f min)" % (n, len(todo) + len(overlap_check), (time.time() - t0) / 60), flush=True)
        if not page:
            miss += 1
            continue
        rs = rows_of(page)
        if not rs:
            miss += 1
            continue
        agg = assemble(rs)
        if not agg or agg["fii"] == 0:
            held += 1
            continue  # no FPI row -> hold, never write a zero
        if (s, qe) in wb:
            agree.append((abs(agg["fii"] - wb[(s, qe)][1]), abs(agg["dii"] - wb[(s, qe)][2]), s, qe))
        else:
            results[(s, qe)] = agg

    if agree:
        agree.sort()
        med_f = agree[len(agree) // 2][0]
        med_d = sorted(x[1] for x in agree)[len(agree) // 2]
        print(
            "\nOVERLAP vs Wayback-derived: n=%d  median |fii diff|=%.2fpp  |dii diff|=%.2fpp"
            % (len(agree), med_f, med_d),
            flush=True,
        )
        worst = agree[-3:]
        for w in worst:
            print(f"   worst: {w[2]} {w[3]} fii diff {w[0]:.2f}", flush=True)
        if med_f > GATE_PP:
            msg = f"STOP: overlap median {med_f:.2f}pp > {GATE_PP:.1f}pp — routes disagree, writing NOTHING"
            raise SystemExit(msg)
    else:
        print("\n⚠ no overlap sample obtained — refusing to write without validation", flush=True)
        if results:
            msg = "STOP: unvalidated"
            raise SystemExit(msg)

    print("assembled %d new cells (%d held for fii=0/no-rows, %d fetch-miss)" % (len(results), held, miss), flush=True)
    if a.dry or not results:
        print("(dry run or nothing to write)")
        return

    led = json.load(gzip.open(LEDGER, "rt", encoding="utf-8"))
    fills = led["fills"]
    import datetime

    added = 0
    for (s, qe), agg in results.items():
        d = (datetime.date(*map(int, qe.split("-"))) + datetime.timedelta(days=21)).isoformat()
        cell = [
            agg["prom"],
            agg["fii"],
            agg["dii"],
            agg["mf"],
            agg["ins"],
            d,
            None,
            "trendlyne_rows+our_old_format_formula;seam;overlap-validated %.2fpp n=%d;subdate=QE+21d"
            % (med_f, len(agree)),
        ]
        if qe not in fills.setdefault(s, {}):
            fills[s][qe] = cell
            added += 1
    led["_meta"]["cells"] = sum(len(v) for v in fills.values())
    with gzip.open(LEDGER, "wt", encoding="utf-8") as fh:
        json.dump(led, fh, separators=(",", ":"))
    print("LEDGER +%d cells -> %s" % (added, os.path.basename(LEDGER)), flush=True)


if __name__ == "__main__":
    main()

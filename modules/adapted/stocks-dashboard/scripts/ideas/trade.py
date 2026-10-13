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


"""India monthly trade panel by 8-digit HS code from the Ministry of Commerce MEIDB
(https://tradestat.commerce.gov.in/meidb/): export + import VALUE (US$ million) and QUANTITY per month for
every 8-digit code (about 12,000), and the derived unit price (US$ per unit). This is the public source behind
the "product prices by HS code" pages sold elsewhere. Data on the portal starts Jan 2018; a month is published
roughly 45 days after it ends ("Data available: Jan 2018 to <month>").

Usage:
  python3 scripts/ideas/trade.py --months 12     # ensure the last 12 published months are cached, then build
  python3 scripts/ideas/trade.py --latest        # the daily routine's mode: fetch only a newly published month (4 POSTs), rebuild
  python3 scripts/ideas/trade.py --build         # rebuild from whatever is cached (no network)
Cache: scripts/ideas/_cache/trade/<kind>_<yyyymm>_<val>.json.gz (git-ignored; each response also carries the year-ago month).
Writes:
  docs/ideas/trade/index.json.gz one row per HS code: latest value/quantity/unit price both sides + % changes + score (page table + search)
  docs/ideas/trade/ch/<NN>.json.gz per HS chapter: the full monthly series per code (page chart, loaded on demand)
  docs/ideas/trade/meta.json    months covered, build stamp, chapter names
"""
import argparse
import datetime
import glob
import gzip
import html as htmlmod
import http.cookiejar
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ist

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "docs", "ideas", "trade")
CACHE = os.path.join(HERE, "_cache", "trade")
os.makedirs(os.path.join(OUT, "ch"), exist_ok=True)
os.makedirs(CACHE, exist_ok=True)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
BASE = "https://tradestat.commerce.gov.in/meidb/"
FORM = {"export": "commoditywise_export", "import": "commoditywise_import"}
MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# units that behave like a commodity price (mass / volume / length); NOS-type units make unit "prices" lumpy
COMMODITY_UNITS = {
    "KGS",
    "TON",
    "LTR",
    "GMS",
    "MTR",
    "SQM",
    "CUM",
    "CCM",
    "MTS",
    "KLR",
    "TNE",
    "CTM",
}
CHAPTERS = {
    "01": "Live animals",
    "02": "Meat",
    "03": "Fish & seafood",
    "04": "Dairy, eggs, honey",
    "05": "Other animal products",
    "06": "Live plants",
    "07": "Vegetables",
    "08": "Fruits & nuts",
    "09": "Coffee, tea, spices",
    "10": "Cereals",
    "11": "Milling products, starch, malt",
    "12": "Oil seeds, fodder",
    "13": "Lac, gums, resins",
    "14": "Vegetable plaiting materials",
    "15": "Fats & oils",
    "16": "Meat/fish preparations",
    "17": "Sugar & confectionery",
    "18": "Cocoa",
    "19": "Cereal & flour preparations",
    "20": "Fruit & vegetable preparations",
    "21": "Misc edible preparations",
    "22": "Beverages & spirits",
    "23": "Food residues, animal feed",
    "24": "Tobacco",
    "25": "Salt, sulphur, stone, cement",
    "26": "Ores, slag, ash",
    "27": "Mineral fuels & oils",
    "28": "Inorganic chemicals",
    "29": "Organic chemicals",
    "30": "Pharmaceuticals",
    "31": "Fertilisers",
    "32": "Dyes, pigments, paints",
    "33": "Essential oils, cosmetics",
    "34": "Soaps, waxes, lubricants",
    "35": "Albuminoids, glues, enzymes",
    "36": "Explosives, matches",
    "37": "Photographic goods",
    "38": "Misc chemical products",
    "39": "Plastics",
    "40": "Rubber",
    "41": "Raw hides & leather",
    "42": "Leather articles",
    "43": "Furskins",
    "44": "Wood",
    "45": "Cork",
    "46": "Straw & basketware",
    "47": "Pulp & waste paper",
    "48": "Paper & paperboard",
    "49": "Printed matter",
    "50": "Silk",
    "51": "Wool",
    "52": "Cotton",
    "53": "Jute & other fibres",
    "54": "Man-made filaments",
    "55": "Man-made staple fibres",
    "56": "Wadding, felt, nonwovens",
    "57": "Carpets",
    "58": "Special woven fabrics",
    "59": "Coated textiles",
    "60": "Knitted fabrics",
    "61": "Knitted apparel",
    "62": "Woven apparel",
    "63": "Other textile articles",
    "64": "Footwear",
    "65": "Headgear",
    "66": "Umbrellas",
    "67": "Feathers, artificial flowers",
    "68": "Stone, cement, asbestos articles",
    "69": "Ceramics",
    "70": "Glass",
    "71": "Gems, precious metals, jewellery",
    "72": "Iron & steel",
    "73": "Iron & steel articles",
    "74": "Copper",
    "75": "Nickel",
    "76": "Aluminium",
    "78": "Lead",
    "79": "Zinc",
    "80": "Tin",
    "81": "Other base metals",
    "82": "Tools & cutlery",
    "83": "Misc base-metal articles",
    "84": "Machinery",
    "85": "Electrical machinery & electronics",
    "86": "Railway",
    "87": "Vehicles",
    "88": "Aircraft",
    "89": "Ships",
    "90": "Optical, medical instruments",
    "91": "Clocks & watches",
    "92": "Musical instruments",
    "93": "Arms",
    "94": "Furniture, lighting",
    "95": "Toys, sports goods",
    "96": "Misc manufactured",
    "97": "Art & antiques",
    "98": "Project goods, special",
    "99": "Misc",
}

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(url, data=None, referer=None):
    hdr = {"User-Agent": UA, "Accept": "text/html,*/*"}
    if referer:
        hdr["Referer"] = referer
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=hdr)
    with opener.open(req, timeout=300) as f:
        return f.read().decode("utf-8", "ignore")


def form_state(kind):
    page = get(BASE + FORM[kind])
    tok = re.search(r'name="_token" value="([^"]+)"', page)
    avail = re.search(r"Data available:\s*(\w+)\s+(\d{4})\s+to\s+(\w+)\s+(\d{4})", page)
    latest = None
    if avail:
        latest = (int(avail.group(4)), MON.index(avail.group(3)[:3].lower()) + 1)
    return tok.group(1) if tok else None, latest, page


def fetch_month(kind, year, month, val):
    """val: '1' = US$ million, '2' = quantity. Returns {'header', 'rows': [(hs, desc, unit, month_prev_year, month_this_year)]}."""
    fn = os.path.join(CACHE, f"{kind}_{year}{month:02d}_{val}.json.gz")
    if os.path.exists(fn):
        return json.load(gzip.open(fn, "rt"))
    tok, latest, _ = form_state(kind)
    pre = "im" if kind == "import" else ""  # the import form prefixes its select names with "im"
    data = {
        "_token": tok,
        pre + "ddMonth": str(month),
        pre + "ddYear": str(year),
        "comlev": "all",
        pre + "ddCommodityLevel": "8",
        pre + "ddReportVal": val,
        pre + "ddReportYear": "2",
    }
    h = get(BASE + FORM[kind], data, referer=BASE + FORM[kind])
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S)
    out = []
    hdr = None
    for r in rows:
        cells = [
            htmlmod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
        ]
        if not cells:
            continue
        if cells[0] in ("S.", "S.No.", "S.No", "Sr.") or cells[1:2] == ["HS Code"]:
            hdr = cells
            continue
        if len(cells) < 5 or not re.fullmatch(r"\d{8}", cells[1]):
            continue

        def num(x):
            x = x.replace(",", "")
            try:
                return float(x)
            except Exception:
                return None

        # value report: [S, HS, Commodity, M-1y, M, %, YTD-1y, YTD, %]; quantity report adds a Unit column after Commodity
        if val == "2" and len(cells) >= 10:
            out.append((cells[1], cells[2], cells[3], num(cells[4]), num(cells[5])))
        else:
            out.append((cells[1], cells[2], "", num(cells[3]), num(cells[4])))
    res = {"header": hdr, "rows": out}
    if len(out) < 5000:
        raise RuntimeError(
            f"{kind} {year}-{month:02d} val={val}: only {len(out)} rows parsed (header {hdr})"
        )
    json.dump(res, gzip.open(fn, "wt"))
    time.sleep(1.5)
    return res


def month_list(latest, n):
    y, m = latest
    out = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def cached_months():
    ms = set()
    for fn in glob.glob(os.path.join(CACHE, "*_1.json.gz")):
        m = re.search(r"_(\d{4})(\d{2})_1\.json\.gz$", fn)
        if m:
            ms.add((int(m.group(1)), int(m.group(2))))
    return sorted(ms)


def ensure(months):
    for y, m in months:
        for kind in ("export", "import"):
            for val in ("1", "2"):
                for _attempt in range(3):
                    try:
                        r = fetch_month(kind, y, m, val)
                        print(f"{kind} {y}-{m:02d} v{val}: {len(r['rows'])} codes", flush=True)
                        break
                    except Exception as e:
                        print(f"{kind} {y}-{m:02d} v{val}: FAIL {e}", flush=True)
                        time.sleep(15)


def load_panel():
    """Assemble {hs: {d,u,e,q,i,p}}: seed from the PUBLISHED chapter files (docs/ideas/trade/ch/*.json.gz, the full history),
    then overlay every cached month (year-ago columns fill months we never fetched). A fresh clone with an empty cache
    therefore keeps the history and only adds what it fetched."""
    panel = {}
    for fn in sorted(glob.glob(os.path.join(OUT, "ch", "*.json.gz"))):
        try:
            obj = json.load(gzip.open(fn, "rt"))
        except Exception as e:
            print("skip unreadable", fn, e)
            continue
        ms = obj["months"]
        for hs, r in obj["codes"].items():
            rec = panel.setdefault(
                hs, {"d": r["d"], "u": r["u"], "e": {}, "q": {}, "i": {}, "p": {}}
            )
            for f in ("e", "q", "i", "p"):
                for m, v in zip(ms, r.get(f) or [], strict=False):
                    if v is not None:
                        rec[f][m] = v
    for y, m in cached_months():
        for kind in ("export", "import"):
            for val in ("1", "2"):
                fn = os.path.join(CACHE, f"{kind}_{y}{m:02d}_{val}.json.gz")
                if not os.path.exists(fn):
                    continue
                res = json.load(gzip.open(fn, "rt"))
                key_this = f"{y}-{m:02d}"
                key_prev = f"{y - 1}-{m:02d}"
                tgt = {"export1": "e", "export2": "q", "import1": "i", "import2": "p"}[kind + val]
                for hs, desc, unit, prev, cur in res["rows"]:
                    rec = panel.setdefault(
                        hs, {"d": desc, "u": "", "e": {}, "q": {}, "i": {}, "p": {}}
                    )
                    if unit and not rec["u"]:
                        rec["u"] = unit
                    if desc and (not rec["d"] or len(desc) > len(rec["d"])):
                        rec["d"] = desc
                    if cur is not None:
                        rec[tgt][key_this] = cur
                    if prev is not None and key_prev not in rec[tgt]:
                        rec[tgt][key_prev] = prev
    return panel


def dump_gz(obj, path):
    """Deterministic gzip (mtime=0) so an unchanged rebuild is byte-identical and git sees no churn."""
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(obj, separators=(",", ":")).encode())


def pct(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b not in (None, 0) and b > 0 else None


def build():
    panel = load_panel()
    months = sorted({k for r in panel.values() for f in ("e", "q", "i", "p") for k in r[f]})
    if not months:
        raise SystemExit("nothing cached: run with --months N first")
    latest = months[-1]
    mi = {m: i for i, m in enumerate(months)}

    def back(n):
        i = mi[latest] - n
        return months[i] if i >= 0 else None

    m1, m3, m12 = back(1), back(3), back(12)
    stamp = ist.stamp()

    rows = []
    chapters = {}
    for hs in sorted(panel):
        r = panel[hs]
        unit = r["u"]
        commodity_unit = unit in COMMODITY_UNITS

        def up(v, q, k):
            # unit price = US$ mn * 1e6 / quantity; ignore months under US$50k (rounding noise: values are printed to 2 dp of a million)
            if not k or v.get(k) is None or not q.get(k) or v.get(k) < 0.05:
                return None
            return v[k] * 1e6 / q[k]

        rec = [hs, r["d"], unit]
        for vf, qf in (("i", "p"), ("e", "q")):
            v, q = r[vf], r[qf]
            p0 = up(v, q, latest)

            # smoothed year-on-year: last 3 months vs same 3 months a year earlier (value-weighted), damps single-month lumps
            def avg(ks):
                ks = [k for k in ks if k and v.get(k) is not None and q.get(k)]
                sv = sum(v[k] for k in ks)
                sq = sum(q[k] for k in ks)
                return sv * 1e6 / sq if ks and sq > 0 and sv >= 0.05 else None

            last3 = [back(i) for i in range(3)]
            prev3 = [back(i + 12) for i in range(3)]
            sy = pct(avg(last3), avg(prev3))
            qs = [q[k] for k in months[-13:-1] if q.get(k)]
            thin = (
                1
                if (q.get(latest) is not None and qs and q[latest] < 0.3 * statistics.median(qs))
                else 0
            )
            rec += [
                v.get(latest),
                q.get(latest),
                round(p0, 4) if p0 else None,
                pct(p0, up(v, q, m1)),
                pct(p0, up(v, q, m3)),
                pct(p0, up(v, q, m12)),
                sy,
                pct(q.get(latest), q.get(m12)),
                pct(v.get(latest), v.get(m12)),
                thin,
            ]
        # score: unit-price momentum, only commodity-like units, only if the side moved >= US$1 mn in the latest month and quantity is not thin
        s = 0.0
        if commodity_unit:
            for base in (3, 13):  # import block starts at 3, export at 13
                val, thin = rec[base], rec[base + 9]
                if (val or 0) < 1 or thin:
                    continue
                for off, w in ((3, 0.5), (4, 1.0), (5, 1.5), (6, 1.5)):  # 1m, 3m, 12m, smoothed yoy
                    x = rec[base + off]
                    if x is not None:
                        s += w * max(min(x, 200), -200) / 100
        rec.append(round(s, 2))
        rows.append(rec)
        ch = hs[:2]
        chapters.setdefault(ch, {"months": months, "codes": {}})["codes"][hs] = {
            "d": r["d"],
            "u": unit,
            "i": [r["i"].get(m) for m in months],
            "p": [r["p"].get(m) for m in months],
            "e": [r["e"].get(m) for m in months],
            "q": [r["q"].get(m) for m in months],
        }
    cols = [
        "hs",
        "d",
        "u",
        "iv",
        "iq",
        "ip",
        "ip1",
        "ip3",
        "ip12",
        "isy",
        "iq12",
        "iv12",
        "ithin",
        "ev",
        "eq",
        "ep",
        "ep1",
        "ep3",
        "ep12",
        "esy",
        "eq12",
        "ev12",
        "ethin",
        "s",
    ]
    index = {
        "source": "Ministry of Commerce MEIDB (tradestat.commerce.gov.in), commodity-wise monthly, 8-digit HS",
        "built": stamp,
        "latest": latest,
        "months_from": months[0],
        "months_to": latest,
        "n": len(rows),
        "value_unit": "US$ million",
        "price_unit": "US$ per quantity unit",
        "notes": "ip/ep = unit price in the latest month (value*1e6/quantity); ip1/ip3/ip12 = % change vs 1/3/12 months earlier; isy/esy = last-3-months vs year-ago-3-months; iq12/ev12 = quantity/value % vs year-ago month; thin = latest quantity < 30% of the trailing 12-month median (unit price unreliable); s = momentum score (commodity units only)",
        "cols": cols,
        "rows": rows,
    }
    dump_gz(index, os.path.join(OUT, "index.json.gz"))
    for ch, obj in chapters.items():
        obj["chapter"] = ch
        obj["name"] = CHAPTERS.get(ch, "")
        dump_gz(obj, os.path.join(OUT, "ch", f"{ch}.json.gz"))
    json.dump(
        {
            "built": stamp,
            "latest": latest,
            "months": months,
            "n_codes": len(rows),
            "chapters": {c: CHAPTERS.get(c, "") for c in sorted(chapters)},
        },
        open(os.path.join(OUT, "meta.json"), "w"),
        separators=(",", ":"),
    )
    print(
        f"index: {len(rows)} codes, months {months[0]}..{latest} ({len(months)}), {len(chapters)} chapter files",
        flush=True,
    )
    top = sorted([r for r in rows if r[-1] > 0], key=lambda r: -r[-1])[:12]
    for r in top:
        print(
            f"  {r[0]} {r[1][:40]:40s} {r[2]:4s} imp ${r[3]} up {r[5]} 1m {r[6]} 3m {r[7]} 12m {r[8]} sy {r[9]} | exp ${r[13]} 12m {r[18]} | s {r[-1]}"
        )
    return index


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--months",
        type=int,
        default=0,
        help="ensure the last N published months are cached before building",
    )
    ap.add_argument(
        "--latest",
        action="store_true",
        help="fetch the newest published month if not cached, then build",
    )
    ap.add_argument("--build", action="store_true", help="build from cache only")
    a = ap.parse_args()
    if a.months or a.latest:
        try:
            tok, latest, _ = form_state("export")
        except urllib.error.URLError as e:
            # A blocked or down MEIDB is a reported failure, not a stack trace: leave every
            # published file exactly as it is rather than rebuilding from a half-fetched cache.
            raise SystemExit(
                f"trade: MEIDB (tradestat.commerce.gov.in) unreachable ({e.reason}); "
                "docs/ideas/trade/** LEFT UNCHANGED"
            )
        if not latest:
            raise SystemExit('could not read the "Data available" line from MEIDB')
        if a.latest and not a.months:
            meta_fn = os.path.join(OUT, "meta.json")
            have = json.load(open(meta_fn))["latest"] if os.path.exists(meta_fn) else ""
            if f"{latest[0]}-{latest[1]:02d}" <= have:
                print(
                    f"MEIDB latest {latest[0]}-{latest[1]:02d} already built ({have}); nothing to fetch"
                )
                raise SystemExit(0)
        ensure(month_list(latest, a.months or 1))
    build()

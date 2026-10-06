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


"""Older Indian prices, recovered once from where they are archived, into docs/ideas/india_backfill.csv.

The daily run only knows today's print. This fills the history behind the click-to-chart panel from routes the
2026-09-23 research measured (runbook 144a-v), each point labelled with where it was read (`via`). Kept apart from
india_spot_history.csv so a recorded print and a recovered one never blur; a recorded print wins a tie.
Idempotent: a (date, source, series) already in the file is never written twice.

  python3 scripts/ideas/india_backfill.py metalbook   MetalBook's own price records inside Wayback captures of its
                                                      home page (2025-06 -> 2026-02, ~3-4 captures a month). The
                                                      ticker markup is NOT in the captures; the records are, and
                                                      they carry MetalBook's own price date.
  python3 scripts/ideas/india_backfill.py ppac        PPAC's daily metro petrol/diesel PDF - the same file the daily
                                                      run reads - holds every day since 16-Jun-2017 (IOC RSP).
  python3 scripts/ideas/india_backfill.py rubber      Rubber Board's own daily price search, back to 2001, per grade
                                                      and market (markets read from their labelled sections).
  python3 scripts/ideas/india_backfill.py ibja        IBJA's chart data on its home page: ~85 trading days of the PM
                                                      fix (gold 999, gold 916, silver 999) - what the daily row records.
  python3 scripts/ideas/india_backfill.py sugar       Chinimandi's daily market post (one per trading day, address
                                                      .../daily-sugar-market-update-by-vizzie-DD-MM-YYYY/) carries
                                                      the city M/30 spot table from 2023-03-06.
Then run india_spot.py (or just its build_history) so the page picks the points up.
"""
import csv
import datetime
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import india_spot as I

OUT = I.BACKFILL
COLS = ["date", "source", "series", "price", "unit", "via"]
CACHE = os.path.join(HERE, "_cache", "backfill")


def read_all():
    """Every row of the (gzipped) backfill file, as dicts."""
    if not os.path.exists(OUT):
        return []
    import gzip

    with gzip.open(OUT, "rt", newline="") as f:
        return list(csv.DictReader(f))


def existing():
    return {(r["date"], r["source"], r["series"]) for r in read_all()}


def append(rows):
    """Add rows not already on file and rewrite the gzip deterministically (sorted, mtime 0), so the same data
    always gives the same bytes and git only sees a change when a point really changed."""
    import gzip
    import io

    old = read_all()
    have = {(r["date"], r["source"], r["series"]) for r in old}
    new = [r for r in rows if (r["date"], r["source"], r["series"]) not in have]
    if new or not os.path.exists(OUT):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        for r in sorted(old + new, key=lambda r: (r["source"], r["series"], r["date"])):
            w.writerow({k: r[k] for k in COLS})
        with open(OUT, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
            gz.write(buf.getvalue().encode())
    slips({r["source"] for r in rows})
    return len(new), len(rows) - len(new)


def slips(sources):
    """A value that breaks by more than 50% from BOTH its neighbours while they agree within 25% is a data-entry
    slip in the source (the Rubber Board has 48.25 between 4,825 and 4,850, and 156,000 between 15,400 and 15,600).
    It is never corrected - a guess at the missing decimal is still a guess - only listed in
    india_backfill_retracted.csv with its neighbours, which build_history honours. Returns how many were new."""
    path = I.BACKFILL_RETRACTED
    have = (
        {(r["date"], r["source"], r["series"], r["price"]) for r in csv.DictReader(open(path))}
        if os.path.exists(path)
        else set()
    )
    by = {}
    for r in read_all():
        if r["source"] in sources:
            by.setdefault((r["source"], r["series"]), []).append(r)
    new = []
    for v in by.values():
        v.sort(key=lambda r: r["date"])
        p = [float(r["price"]) for r in v]
        for i in range(1, len(v) - 1):
            a, b = p[i - 1], p[i + 1]
            if (
                a > 0
                and b > 0
                and abs(a / b - 1) <= 0.25
                and abs(p[i] / a - 1) > 0.5
                and abs(p[i] / b - 1) > 0.5
            ):
                k = (v[i]["date"], v[i]["source"], v[i]["series"], v[i]["price"])
                if k not in have:
                    new.append(
                        [
                            *k,
                            v[i]["unit"],
                            f"one-day value in the source's own data that breaks from both neighbours "
                            f"({a:g} before, {b:g} after) - a data-entry slip; left out, not corrected",
                        ]
                    )
    if new:
        first = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if first:
                w.writerow(["date", "source", "series", "price", "unit", "reason"])
            w.writerows(new)
        print(f"  slips: {len(new)} one-day source errors listed in {os.path.basename(path)}")
    return len(new)


# ---------------------------------------------------------------- MetalBook via the Wayback Machine
def metalbook_records(html_text):
    """(city | product grade, price date, Rs/kg) from the price records a MetalBook page embeds."""
    t = html_text.replace('\\\\"', "\x00").replace('\\"', '"')
    for m in re.findall(r'\{"_id":\{"product_name".*?"created_by":"[^"]*"\}', t):
        try:
            o = json.loads(m.replace("\x00", '\\"'))
            pid = o["_id"]
            city = (o.get("location") or pid.get("location") or "").strip()
            name = re.sub(
                r"\s+", " ", f"{pid.get('product_name', '')} {pid.get('grade') or ''}"
            ).strip()
            d = (
                datetime.datetime.utcfromtimestamp(o["price_date"] / 1000)
                + datetime.timedelta(hours=5, minutes=30)
            ).strftime("%Y-%m-%d")
            yield (
                I.series_key({"city": city, "name": name}),
                d,
                round(float(o["price_per_ton"]) / 1000, 2),
            )
        except (ValueError, KeyError, TypeError):
            continue


def metalbook():
    cache = os.path.join(CACHE, "metalbook_wayback")
    os.makedirs(cache, exist_ok=True)
    stamps = []
    for q in ("metalbook.com/", "www.metalbook.com/"):
        try:
            cdx = json.loads(
                I.get(
                    "http://web.archive.org/cdx/search/cdx?url="
                    + q
                    + "&output=json&fl=timestamp,statuscode&filter=statuscode:200&collapse=timestamp:10",
                    timeout=120,
                    retries=3,
                )
            )
            stamps += [r[0] for r in cdx[1:]]
        except Exception as e:
            print(
                f"metalbook: CDX for {q} failed ({str(e)[:70]}); using the captures already cached"
            )
    stamps = sorted(
        set(stamps) | {os.path.basename(p)[:14] for p in glob.glob(os.path.join(cache, "*.html"))}
    )
    rows, conflicts, per = {}, [], []
    for ts in stamps:
        fn = os.path.join(cache, ts + ".html")
        if not os.path.exists(fn):
            try:
                open(fn, "w").write(
                    I.get(
                        f"http://web.archive.org/web/{ts}id_/https://www.metalbook.com/",
                        timeout=90,
                        retries=2,
                    )
                )
                time.sleep(1.0)
            except Exception as e:
                per.append((ts, f"fetch failed: {str(e)[:50]}"))
                continue
        n = 0
        for key, d, p in metalbook_records(open(fn, errors="ignore").read()):
            k = (d, key)
            if k in rows and rows[k]["price"] != p:
                conflicts.append((key, d, rows[k]["price"], p, ts))
                continue  # first capture that stated it stands
            rows.setdefault(
                k,
                {
                    "date": d,
                    "source": "metalbook",
                    "series": key,
                    "price": p,
                    "unit": "Rs/kg",
                    "via": f"wayback {ts}",
                },
            )
            n += 1
        per.append((ts, n))
    added, dup = append(list(rows.values()))
    print(
        f"metalbook: {len(stamps)} captures, {sum(1 for _, n in per if isinstance(n, int) and n)} with price records; "
        f"{len(rows)} dated prints, {added} new, {dup} already on file; {len(conflicts)} conflicts {conflicts[:3]}"
    )


# ---------------------------------------------------------------- PPAC: every day since 16-Jun-2017
def ppac():
    """Each day is a petrol row then a diesel row carrying the SAME date: 'DD-Mon-YY p1 p2 p3 p4 DD-Mon-YY d1..d4'
    for Delhi, Mumbai, Chennai, Kolkata. The pair is only taken when both rows name one date."""
    import fitz

    h = I.get("https://ppac.gov.in/")
    links = re.findall(
        r'href="(https://ppac\.gov\.in/download\.php\?file=importantnews/\d+_PP_9_a_DailyPriceMSHSD_Metro_[\d.]+\.pdf)"',
        h,
    )
    if not links:
        sys.exit("ppac: no daily price PDF link on the home page")
    doc = fitz.open(stream=I.get(links[0], binary=True, timeout=120), filetype="pdf")
    t = re.sub(r"\s+", " ", " ".join(pg.get_text() for pg in doc))
    num = r"(\d{2,3}\.\d{2})"
    pat = re.compile(
        r"(?<![\d-])(\d{1,2}-[A-Za-z]{3}-\d{2})\s+"
        + r"\s+".join([num] * 4)
        + r"\s+\1\s+"
        + r"\s+".join([num] * 4)
    )
    rows, bad, days = [], [], set()
    for m in pat.finditer(t):
        d = I.iso_date(m.group(1))
        if not d or d in days:
            continue
        vals = [float(x) for x in m.groups()[1:]]
        petrol, diesel = vals[:4], vals[4:]
        if not all(40 <= v <= 150 for v in vals):
            bad.append((d, vals))
            continue
        days.add(d)
        for fuel, vs in (("petrol", petrol), ("diesel", diesel)):
            for city, v in zip(("Delhi", "Mumbai", "Chennai", "Kolkata"), vs, strict=False):
                rows.append(
                    {
                        "date": d,
                        "source": "fuel",
                        "series": I.series_key({"city": city, "name": fuel}),
                        "price": v,
                        "unit": "Rs/litre",
                        "via": "PPAC daily price table",
                    }
                )
    ds = sorted(days)
    span = (
        (datetime.date.fromisoformat(ds[-1]) - datetime.date.fromisoformat(ds[0])).days + 1
        if ds
        else 0
    )
    added, dup = append(rows)
    print(
        f"ppac: {len(ds)} days {ds[0] if ds else '-'} -> {ds[-1] if ds else '-'} ({span} calendar days in the span), "
        f"{len(bad)} rejected as implausible {bad[:2]}; {added} new points, {dup} already on file"
    )


# ---------------------------------------------------------------- Rubber Board: daily since 2001
RUBBER_GRADES = {"7": "RSS4", "9": "RSS5", "10": "ISNR20", "11": "Latex(60%)"}


def rubber(start_year=2001):
    """POST /indianPrices (searchFlag=day) a year at a time per grade, after GET /public for the session cookie.
    Each market's table sits in its own <div id="Kottayam|Kochi|Agartala">, so markets are read by NAME, never by
    table order (Agartala is empty in 2010; order would shift). '*' not available, '#' holiday, '~' no trade: skipped.
    Only market/grade pairs the page publishes today are kept, so every point lands on a series the page shows."""
    import html as H
    import http.cookiejar
    import urllib.parse
    import urllib.request

    cur = {r["key"] for r in json.load(open(I.OUT))["sources"]["rubber"]["rows"]}
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj), urllib.request.HTTPSHandler(context=I.LAX)
    )
    op.addheaders = [("User-Agent", I.UA)]
    op.open("https://rubberboard.gov.in/public?lang=E", timeout=60).read()
    rows, fails, wrong_grade = {}, [], []
    today = datetime.date.today()
    for code, grade in RUBBER_GRADES.items():
        for y in range(start_year, today.year + 1):
            a, b = datetime.date(y, 1, 1), min(datetime.date(y, 12, 31), today)
            body = urllib.parse.urlencode(
                {
                    "searchFlag": "day",
                    "type": "indian",
                    "txtFromDate": a.strftime("%d-%m-%Y"),
                    "txtToDate": b.strftime("%d-%m-%Y"),
                    "grade": code,
                }
            ).encode()
            try:
                h = (
                    op.open(
                        urllib.request.Request(
                            "https://rubberboard.gov.in/indianPrices",
                            data=body,
                            headers={"Referer": "https://rubberboard.gov.in/public?lang=E"},
                        ),
                        timeout=120,
                    )
                    .read()
                    .decode("utf-8", "ignore")
                )
            except Exception as e:
                fails.append((grade, y, str(e)[:60]))
                time.sleep(3)
                continue
            said = re.search(r"Daily Market Price of\s*(?:<[^>]+>\s*)*([A-Za-z0-9()%]+)", h)
            if (
                said
                and said.group(1).upper().replace("(60%)", "")[:4]
                != grade.upper().replace("(60%)", "")[:4]
            ):
                wrong_grade.append((code, grade, said.group(1)))
                continue
            for mkt in ("Kottayam", "Kochi", "Agartala"):
                i = h.find(f'<div id="{mkt}"')
                if i < 0:
                    continue
                j = min(
                    [
                        k
                        for k in (
                            h.find('<div id="Kochi"', i + 5),
                            h.find('<div id="Agartala"', i + 5),
                        )
                        if k > 0
                    ]
                    or [len(h)]
                )
                key = I.series_key({"market": mkt, "name": grade})
                if key not in cur:
                    continue
                for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h[i:j], re.S):
                    cells = [
                        re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                        for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
                    ]
                    if len(cells) < 2 or not re.match(r"\d{2}-\d{2}-\d{4}$", cells[0]):
                        continue
                    try:
                        v = float(cells[1].replace(",", ""))
                    except ValueError:
                        continue  # *, #, ~ : no price that day
                    d = I.iso_date(cells[0])
                    if d and v > 0:
                        rows[(d, key)] = {
                            "date": d,
                            "source": "rubber",
                            "series": key,
                            "price": v,
                            "unit": "Rs/100kg",
                            "via": "Rubber Board daily price search",
                        }
            time.sleep(1.0)
    added, dup = append(list(rows.values()))
    per = {}
    for d, k in rows:
        per.setdefault(k, []).append(d)
    for k in sorted(per):
        print(f"  {k:22s} {len(per[k]):5d} days  {min(per[k])} -> {max(per[k])}")
    print(
        f"rubber: {len(rows)} dated prices, {added} new, {dup} already on file; {len(fails)} failed requests {fails[:3]}; "
        f"{len(wrong_grade)} responses naming another grade {wrong_grade[:2]}"
    )


# ---------------------------------------------------------------- IBJA: the PM fix in its own chart data
def ibja():
    ch = I.ibja_chart(I.get("https://ibjarates.com/", ctx=I.LAX))
    unit = {"gold 999": "Rs/10g", "gold 916 (22k)": "Rs/10g", "silver 999": "Rs/kg"}
    rows = [
        {
            "date": d,
            "source": "ibja",
            "series": name,
            "price": v,
            "unit": unit[name],
            "via": "IBJA chart data (PM fix)",
        }
        for name, pts in ch.items()
        for d, v in pts
    ]
    added, dup = append(rows)
    for name, pts in ch.items():
        print(f"  {name:16s} {len(pts):4d} days {pts[0][0]} -> {pts[-1][0]}")
    print(f"ibja: {len(rows)} dated PM fixes, {added} new, {dup} already on file")


# ---------------------------------------------------------------- Chinimandi: city spot M/30 from 2023-03-06
SUGAR_CITY = {"bangaluru": "Bengaluru", "bangalore": "Bengaluru", "bengaluru": "Bengaluru"}


def sugar(start="2023-03-06"):
    """Fetch each weekday's post by its address (the WordPress listing API takes ~60 s a call); a day with no post
    answers an error and is skipped. The table reads 'Destination-wise Spot Prices as on Sept, 22 2026 : City
    Grade Rate Delhi M/30 ₹4,809.00 ...'. The post's own date is used, and only series the page shows today."""
    cur = {r["key"] for r in json.load(open(I.OUT))["sources"]["sugar"]["rows"]}
    cities = sorted(
        {k.split(" | ")[0] for k in cur} | {"Bangaluru", "Bangalore"}, key=len, reverse=True
    )
    cache = os.path.join(CACHE, "chinimandi")
    os.makedirs(cache, exist_ok=True)
    rows, missing, unparsed = {}, 0, []
    d = datetime.date.fromisoformat(start)
    while d <= datetime.date.today():
        if d.weekday() < 6:  # Saturdays sometimes carry a post; Sundays never
            slug = f"daily-sugar-market-update-by-vizzie-{d:%d-%m-%Y}"
            fn = os.path.join(cache, slug + ".html")
            if not os.path.exists(fn):
                try:
                    open(fn, "w").write(
                        I.get(f"https://www.chinimandi.com/{slug}/", timeout=60, retries=1)
                    )
                    time.sleep(1.0)
                except Exception:
                    open(fn + ".none", "w").close() if not os.path.exists(fn + ".none") else None
                    missing += 1
                    d += datetime.timedelta(days=1)
                    continue
            t = I.plain(open(fn, errors="ignore").read())
            m = re.search(
                r"Destination-wise Spot Prices as on\s*([A-Za-z]+)\.?,?\s*(\d{1,2}),?\s*(\d{4})(.{0,700})",
                t,
            )
            pd = I.iso_date(f"{m.group(1)} {m.group(2)}, {m.group(3)}") if m else None
            if not m or not pd:
                unparsed.append(d.isoformat())
            else:
                for cm in re.finditer(
                    r"("
                    + "|".join(map(re.escape, cities))
                    + r")\s+([SM]/\d+)\s*₹\s?([\d,]+(?:\.\d+)?)",
                    m.group(4),
                ):
                    city = SUGAR_CITY.get(cm.group(1).lower(), cm.group(1))
                    key = I.series_key({"city": city, "grade": cm.group(2)})
                    if key in cur:
                        rows[(pd, key)] = {
                            "date": pd,
                            "source": "sugar",
                            "series": key,
                            "price": float(cm.group(3).replace(",", "")),
                            "unit": "Rs/quintal",
                            "via": "Chinimandi daily market post",
                        }
        d += datetime.timedelta(days=1)
    added, dup = append(list(rows.values()))
    days = sorted({k[0] for k in rows})
    print(
        f"sugar: {len(days)} days with a city table {days[0] if days else '-'} -> {days[-1] if days else '-'}, "
        f"{len(rows)} prices, {added} new, {dup} already on file; {missing} weekdays without a post; "
        f"{len(unparsed)} posts without a readable table {unparsed[:3]}"
    )


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    {"metalbook": metalbook, "ppac": ppac, "rubber": rubber, "ibja": ibja, "sugar": sugar}.get(
        what, lambda: sys.exit(__doc__)
    )()

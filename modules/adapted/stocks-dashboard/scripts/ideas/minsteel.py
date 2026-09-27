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


"""Mumbai retail prices of TMT, HRC and CRC (Rs per tonne, incl. GST), month by month, from the Ministry of
Steel's own monthly reports (steel.gov.in/monthly-summary). The one free, official, DATED Indian finished-steel
price series: each report states the Mumbai retail price as on its month-end.

The reports word it differently in every era, so the text around each 'Mumbai' is tokenised into product names,
rupee values and dates, and each run of values binds to the names of THE SAME SENTENCE. Every rule below comes
from a defect seen in these PDFs (runbook 144a-vi):
  - a sentence break clears the names: the preamble 'prices of TMT, CRC and HRC decreased' lists them in another
    order and once bound June-2024's TMT price to HRC;
  - a name glued to a word still counts ('andCRC');
  - 'f.o.b.' is not a sentence end (a chart label printed inside the April-2026 sentence);
  - values bind only when the sentence named exactly as many products - otherwise the sentence is skipped;
  - a value outside Rs 30,000-150,000 is not a finished-steel price (iron ore sits near 5,000);
  - the date is the one the sentence states, never the comparison date ('over their prices as on 31st May');
    it may be written 30thDecember, 2021 / 31st May '26 / 28.02.2023 / December 29, 2023; when the PDF text cut
    it ('as on 31st <chart numbers>') the day is kept and month and year come from the report's own title.
Validated 2026-09-23: 48 month-ends Nov-2021 -> Jun-2026, no date with two values, CRC never below HRC, and all
33 months also read by an independent extract agree exactly.

Usage: python3 scripts/ideas/minsteel.py [--pages 14]
Writes docs/ideas/minsteel_mumbai.json. A failed listing keeps the committed file untouched.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ist  # IST stamps: a naive now() on a UTC runner was labelled IST (runbook 144e)

DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")
OUT = os.path.join(DOCS, "minsteel_mumbai.json")
CACHE = os.path.join(HERE, "_cache", "minsteel")
BASE = "https://steel.gov.in"
LIST = BASE + "/monthly-summary?page=%d"
MON = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}
PROD = {"tmt": "TMT", "rebar": "TMT", "hrc": "HRC", "crc": "CRC"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TOK = re.compile(
    r"(?P<brk>(?<!Rs)(?<!No)(?<!o\.b)\.\s+(?=[A-Z0-9]))"
    r"|(?P<name>(?<![A-Za-z])(?:and)?(?P<n>TMT|Rebar|HRC|CRC)\b)"
    r"|(?P<val>Rs\.?\s*(?P<v>[\d,]{5,8})\s*(?:/\s*-?\s*|per\s+)(?:tonne|ton|t)\b)"
    r"|(?P<date>\b(?:as\s+)?on\s*(?:"
    r"(?P<nd>\d{1,2})\.(?P<nm>\d{1,2})\.(?P<ny>\d{4})"
    r"|(?P<m2>(?:" + MONTHS + r"))\s+(?P<d2>\d{1,2}),?\s+(?P<y2>\d{4})"
    r"|(?P<d>\d{1,2})\s*(?:st|nd|rd|th)?\s*(?P<m>[A-Za-z]{3,9})?\.?[,\s’'‘]*(?P<y>(?:20)?\d{2}(?!\d))?"
    r"))",
    re.IGNORECASE,
)
TITLE = re.compile(
    r"Monthly\s+(?:Economic\s+Report|Summary)\s+(?:for\s+(?:the\s+month\s+of\s+)?)?(" + MONTHS + r")[,\s-]*(\d{4})",
    re.IGNORECASE,
)
TITLE2 = re.compile(r"(?:during|for) the month of (" + MONTHS + r")[,\s]*(\d{4})", re.IGNORECASE)


def mkdate(y, mo, d):
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse(text):
    """[(date, product, price)] stated in one report's text."""
    t = re.sub(r"\s+", " ", text)
    tt = TITLE.search(t) or TITLE2.search(t)
    title = (int(tt.group(2)), MON[tt.group(1)[:3].lower()]) if tt else None
    out = set()
    for mm in re.finditer(r"Mumbai", t):
        win = t[max(0, mm.start() - 760) : mm.start() + 560]
        if "retail" not in win.lower():
            continue
        st = {"names": [], "run": [], "date": None, "cut": None}

        def flush():
            if st["run"] and len(st["names"]) == len(st["run"]):
                d = st["date"] or (mkdate(title[0], title[1], st["cut"]) if st["cut"] and title else None)
                if d:
                    for n, v in zip(st["names"], st["run"], strict=False):
                        out.add((d, n, v))

        for x in TOK.finditer(win):
            if x.group("brk"):
                flush()
                st = {"names": [], "run": [], "date": None, "cut": None}
            elif x.group("name"):
                if st["run"]:
                    flush()
                    st = {"names": [], "run": [], "date": st["date"], "cut": st["cut"]}
                st["names"].append(PROD[x.group("n").lower()])
            elif x.group("val"):
                v = int(x.group("v").replace(",", ""))
                if 30000 <= v <= 150000:
                    st["run"].append(v)
            elif x.group("date"):
                if re.search(
                    r"(?:over|than)\s+(?:their|its)\s+(?:respective\s+)?prices?\s*(?:as\s*)?$",
                    win[max(0, x.start() - 50) : x.start()],
                    re.IGNORECASE,
                ):
                    continue  # the comparison date, not the stated one
                if x.group("nd"):
                    st["date"] = st["date"] or mkdate(int(x.group("ny")), int(x.group("nm")), int(x.group("nd")))
                elif x.group("m2"):
                    st["date"] = st["date"] or mkdate(
                        int(x.group("y2")), MON[x.group("m2")[:3].lower()], int(x.group("d2"))
                    )
                else:
                    mo = (x.group("m") or "")[:3].lower()
                    if x.group("y") and mo in MON:
                        y = int(x.group("y"))
                        y = y + 2000 if y < 100 else y
                        st["date"] = st["date"] or mkdate(y, MON[mo], int(x.group("d")))
                    elif (not mo or (title and mo in MON and MON[mo] == title[1])) and st["cut"] is None:
                        st["cut"] = int(x.group("d"))
        flush()
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=14)
    a = ap.parse_args()
    import fitz
    import india_spot as I  # its polite get() with retries

    os.makedirs(CACHE, exist_ok=True)
    urls = []
    for pg in range(a.pages):
        try:
            # steel.gov.in's chain does not verify on a GitHub runner (2026-09-24: every listing page
            # 'CERTIFICATE_VERIFY_FAILED' while curl -k saw 200) - same treatment as IBJA and the Rubber Board.
            h = I.get(LIST % pg, timeout=45, ctx=I.LAX)
        except Exception as e:
            print(f"minsteel: listing page {pg} failed ({str(e)[:80]}); keeping what was listed so far")
            break
        found = [u for u in re.findall(r'href="(/sites/default/files/[^"]+\.pdf)"', h) if "Citizen" not in u]
        new = [u for u in found if u not in urls]
        if not new:
            break
        urls += new
    if not urls:
        msg = "minsteel: no report listed; committed file left as it was"
        raise SystemExit(msg)
    vals, per_report, unread = {}, {}, []
    for u in urls:
        fn = os.path.join(CACHE, hashlib.md5(u.encode()).hexdigest()[:10] + ".pdf")
        if not os.path.exists(fn):
            try:
                b = I.get(BASE + u, timeout=90, binary=True, ctx=I.LAX)
                if b[:4] != b"%PDF":
                    unread.append((u, "not a PDF"))
                    continue
                open(fn, "wb").write(b)
                time.sleep(1.0)
            except Exception as e:
                unread.append((u, str(e)[:80]))
                continue
        try:
            text = " ".join(p.get_text() for p in fitz.open(fn))
        except Exception as e:
            unread.append((u, "unreadable: " + str(e)[:60]))
            continue
        got = parse(text)
        per_report[u] = len(got)
        for d, n, v in got:
            vals.setdefault((d, n), {}).setdefault(v, []).append(urllib.parse.unquote(u.split("/")[-1]))
    # one date and product must carry one price across every edition that states it
    conflicts = {f"{d} {n}": sorted(v) for (d, n), v in vals.items() if len(v) > 1}
    series = {n: [] for n in ("TMT", "HRC", "CRC")}
    for (d, n), v in sorted(vals.items()):
        if len(v) == 1:
            price, reps = next(iter(v.items()))
            series[n].append([d, price, reps[0]])
    inverted = sorted({d for d, _, _ in series["CRC"]} & {d for d, _, _ in series["HRC"]})
    inverted = [d for d in inverted if {x[0]: x[1] for x in series["CRC"]}[d] < {x[0]: x[1] for x in series["HRC"]}[d]]
    out = {
        "built": ist.stamp(),
        "source": "Ministry of Steel monthly reports (steel.gov.in/monthly-summary): retail price in the Mumbai market",
        "unit": "Rs/tonne incl. GST",
        "specs": {"TMT": "TMT 10 mm (rebar)", "HRC": "HR coil 2.50 mm", "CRC": "CR coil 0.63 mm"},
        "reports_listed": len(urls),
        "reports_with_prices": sum(1 for v in per_report.values() if v),
        "unread": unread,
        "conflicts": conflicts,
        "crc_below_hrc": inverted,
        "series": series,
    }
    if conflicts or inverted:
        print("minsteel: CHECK - conflicts", conflicts, "CRC below HRC on", inverted)
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
    n = {k: len(v) for k, v in series.items()}
    print(
        f"minsteel: {len(urls)} reports listed, {out['reports_with_prices']} state Mumbai prices; points {n}; "
        f"{series['HRC'][0][0] if series['HRC'] else '-'} -> {series['HRC'][-1][0] if series['HRC'] else '-'}"
    )


if __name__ == "__main__":
    main()

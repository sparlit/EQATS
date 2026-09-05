# -*- coding: utf-8 -*-
"""Fetch PRE-IPO quarterly net profit for recent IPOs from Screener — BOTH standalone AND
consolidated (the DRHP/restated history NSE/BSE filing APIs don't carry). Writes staging file
screener_pre.json; merged into sf_fundamentals.json later (pre-IPO quarters = YoY bases, dated
null so they're only ever the year-ago reference, never a 'current' quarter -> point-in-time-safe).

Sales-based OUTLIER GUARD: drop any quarter whose |net profit| is implausible vs its sales
(Screener occasionally has a bad pre-IPO figure, e.g. EMMVEE standalone Sep-2024 = -1692cr on
457cr sales). Per-basis cross-validation against NSE happens at merge time.

Run: python -X utf8 screener_prefund.py @file.txt   (resumable; gentle, backs off on 429)
"""
import urllib.request, json, gzip, re, html, os, time, sys

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
HERE = os.path.dirname(os.path.abspath(__file__))
OUTF = os.path.join(HERE, "screener_pre.json")
MON = {"Mar": "0331", "Jun": "0630", "Sep": "0930", "Dec": "1231"}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=25); raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 429: return "429"
        raise
    if r.headers.get("Content-Encoding") == "gzip": raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")

def qe_of(label):
    mon, yr = label.split(); mm = MON.get(mon)
    return int(yr + mm) if mm else None

def _row(sec, label):
    m = re.search(r'<td[^>]*class="text"[^>]*>\s*(?:<button[^>]*>)?\s*' + re.escape(label) + r'.*?</td>(.*?)</tr>', sec, re.S)
    if not m: return []
    return [html.unescape(re.sub(r'<[^>]+>', '', c)).strip().replace(',', '') for c in re.findall(r'<td[^>]*>(.*?)</td>', m.group(1), re.S)]

def _num(v):
    try: return float(v)
    except Exception: return None

def fetch(sym, basis):
    """{qe: np} for a basis, with implausible (|np| >> sales) quarters dropped. '429' if rate-limited."""
    t = get("https://www.screener.in/company/%s/%s" % (sym, "consolidated/" if basis == "con" else ""))
    if t == "429": return "429"
    m = re.search(r'id="quarters".*?</section>', t, re.S)
    if not m: return None
    sec = m.group(0)
    heads = [qe_of(h) for h in re.findall(r'<th[^>]*>\s*([A-Za-z]{3} \d{4})\s*</th>', sec)]
    nps = _row(sec, "Net Profit"); sales = _row(sec, "Sales")
    out = {}
    for i, qe in enumerate(heads):
        if qe is None or i >= len(nps): continue
        np = _num(nps[i]); s = _num(sales[i]) if i < len(sales) else None
        if np is None: continue
        if s is not None and abs(np) > max(3 * abs(s), 50):   # outlier guard -> drop bad value
            continue
        out[qe] = np
    return out or None

def main():
    a = sys.argv[1:]
    syms = [l.strip() for l in open(a[0][1:]) if l.strip()] if (a and a[0].startswith("@")) else a
    store = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    consec = 0
    for sym in syms:
        if sym in store: continue                              # resumable
        res = {}
        for basis in ("std", "con"):
            r = fetch(sym, basis)
            if r == "429":
                print("%-12s 429 — backoff 90s" % sym); time.sleep(90); r = fetch(sym, basis)
                if r == "429":
                    consec += 1
                    if consec >= 4: print("repeated 429 — stop; rerun to resume"); json.dump(store, open(OUTF, "w"), indent=0); return
                    r = None
            else:
                consec = 0
            if isinstance(r, dict): res[basis] = {str(k): v for k, v in r.items()}
            time.sleep(4)                                      # gentle per request
        if not res:
            print("%-12s no data" % sym); continue
        store[sym] = res
        json.dump(store, open(OUTF, "w"), indent=0)
        print("%-12s std:%d con:%d quarters" % (sym, len(res.get("std", {})), len(res.get("con", {}))))
    print("staged %d symbols -> screener_pre.json (std + con)" % len(store))

if __name__ == "__main__":
    main()

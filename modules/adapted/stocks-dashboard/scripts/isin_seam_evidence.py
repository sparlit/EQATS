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
"""EVIDENCE for every seam the issuer sweep found — read off NSE's own dated files, not inferred.

`isin_issuer_sweep.py` is a SCREEN: an issuer prefix shared by two bin keys says the two
securities belong to one legal entity, nothing more. This collects, per seam, what actually
decides it:

  symbolchange.csv   NSE's own rename register (the pairs 93d fixed are NOT in it, so absence
                     here proves nothing — presence is decisive)
  EQUITY_L rows      name, DATE OF LISTING and FACE VALUE for both symbols, from whichever
                     staged list holds them; a face-value change is the whole reason the ISIN
                     series moved and the merge missed
  bhavcopy           the OLD key's last session and the NEW key's first session, RAW: close,
                     prevclose, the ISIN column (2011+) and the series

The PREVCLOSE handoff (NSE carries the previous close across a symbol change, x the corporate
-action factor when the face value changed with it) is a CONFIRMATION test ONLY — 93c measured
its false-positive rate on a 513-day discovery run and it is useless for discovery. It is
reported here beside the other legs, never on its own.

⚠️ Bin keys are POST-MERGE canonical names while the bhavcopy carries the ERA name (93c's blind
spot: TVSHLTD's first bar was traded as SUNCLAYLTD). So the new key's first session is searched
by SYMBOL first and, failing that, by ISIN ISSUER over every row in that day's file.

Run:  python3 scripts/isin_seam_evidence.py            # all unbridged seams
      python3 scripts/isin_seam_evidence.py INE105A    # one issuer
Writes scripts/_isin_seam_evidence.json.
"""
import csv
import datetime
import glob
import gzip
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "_live")
CACHE = os.path.join(HERE, "_bhav_seam")
SWEEP = os.path.join(HERE, "_isin_issuer_sweep.json")
OUT = os.path.join(HERE, "_isin_seam_evidence.json")
os.makedirs(CACHE, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
# The factors a face-value change can put between the two tapes. Tested exact to the paise;
# a fitted or approximate match is not evidence (93c).
FACTORS = [1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 2, 5, 10, 20, 50, 100, 0.4, 2.5, 0.25, 4]
JAR = http.cookiejar.CookieJar()
BIN = json.loads(gzip.decompress(open(os.path.join(LIVE, "p1_new.bin"), "rb").read()))


def ymd_to_date(n):
    s = str(int(n))
    return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def fetch_day(ymd):
    """-> [ [sym, series, close, prevclose, isin, volume, turnover], ... ] for a trading day.

    Cached. A cached row shorter than 7 columns predates the volume/turnover columns and is
    refetched — volume is what identifies the ERA symbol on a seam day whose file carries no
    ISIN column (88b's rule: assign by volume identity, never by symbol preference)."""
    cf = os.path.join(CACHE, "%d.json" % ymd)
    if os.path.exists(cf):
        try:
            rows = json.load(open(cf))
            if not rows or len(rows[0]) >= 7:
                return rows
        except Exception:
            pass
    d = ymd_to_date(ymd)
    new = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv".format(d.strftime("%d%m%Y"))
    old = "https://nsearchives.nseindia.com/content/historical/EQUITIES/%d/%s/cm%02d%s%dbhav.csv.zip" % (
        d.year,
        MON[d.month - 1],
        d.day,
        MON[d.month - 1],
        d.year,
    )
    # sec_bhavdata_full has no ISIN column; the older cm*bhav.csv.zip carries one from 2011 until
    # NSE stopped publishing it in mid-2020. Inside that window prefer the ISIN-bearing file.
    order = [old, new] if d.year < 2020 or (d.year == 2020 and d.month <= 7) else [new, old]
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
    for url in order:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
            blob = op.open(req, timeout=40).read()
            if url.endswith(".zip"):
                z = zipfile.ZipFile(io.BytesIO(blob))
                text = z.read(z.namelist()[0]).decode("utf-8", "replace")
            else:
                text = blob.decode("utf-8", "replace")
            if "SYMBOL" not in text[:200].upper():
                continue
            rows = list(csv.reader(io.StringIO(text)))
            hdr = [h.strip().upper() for h in rows[0]]

            def ix(*names):
                for n in names:
                    if n in hdr:
                        return hdr.index(n)
                return -1

            iS, iSer = ix("SYMBOL"), ix("SERIES")
            iC, iP, iI = ix("CLOSE_PRICE", "CLOSE"), ix("PREV_CLOSE", "PREVCLOSE"), ix("ISIN")
            iV, iT = ix("TTL_TRD_QNTY", "TOTTRDQTY"), ix("TURNOVER_LACS", "TOTTRDVAL")
            out = []
            for r in rows[1:]:
                if len(r) <= max(iS, iC):
                    continue

                def num(i):
                    if i < 0 or i >= len(r):
                        return None
                    s = r[i].strip()
                    try:
                        return float(s)
                    except ValueError:
                        return None

                out.append(
                    [
                        r[iS].strip(),
                        (r[iSer].strip() if iSer >= 0 else ""),
                        num(iC),
                        num(iP),
                        (r[iI].strip() if 0 <= iI < len(r) else ""),
                        num(iV),
                        num(iT),
                    ]
                )
            json.dump(out, open(cf, "w"))
            return out
        except Exception:
            time.sleep(0.4)
            continue
    json.dump([], open(cf, "w"))
    return []


def load_symchg():
    rows = []
    p = os.path.join(HERE, "symchg.csv")
    for r in csv.reader(open(p, encoding="utf-8", errors="replace")):
        if len(r) >= 4 and r[1].strip() and r[2].strip():
            rows.append(
                {
                    "company": r[0].strip(),
                    "old": r[1].strip().upper(),
                    "new": r[2].strip().upper(),
                    "date": r[3].strip(),
                }
            )
    return rows


def load_lists():
    """-> {tag: {SYMBOL: {name, listed, paidup, face}}} for every staged security list."""
    out = {}
    for p in sorted(glob.glob(os.path.join(LIVE, "equity_l_*.csv"))):
        tag = os.path.basename(p)[:-4].replace("equity_l_", "")
        d = {}
        with open(p, encoding="utf-8", errors="replace") as fh:
            rd = csv.reader(fh)
            hdr = [h.strip().upper() for h in next(rd)]

            def ix(pred):
                return next((i for i, h in enumerate(hdr) if pred(h)), -1)

            iS = ix(lambda h: h == "SYMBOL")
            iN = ix(lambda h: "NAME" in h)
            iL = ix(lambda h: "LISTING" in h)
            iP = ix(lambda h: "PAID" in h)
            iF = ix(lambda h: "FACE" in h)
            for r in rd:
                if len(r) <= iS:
                    continue

                def g(i):
                    return r[i].strip() if 0 <= i < len(r) else ""

                d[g(iS).upper()] = {"name": g(iN), "listed": g(iL), "paidup": g(iP), "face": g(iF)}
        out[tag] = d
    return out


def factor_hits(close_old, prevclose_new):
    """Factors that reproduce the handoff EXACT to the paise. Empty is not a refutation."""
    if not close_old or not prevclose_new:
        return []
    return [f for f in FACTORS if abs(close_old * f - prevclose_new) < 0.005]


def main():
    only = sys.argv[1].upper() if len(sys.argv) > 1 else None
    S = json.load(open(SWEEP))
    rmap = json.load(open(os.path.join(HERE, "_rename_map.json")))
    symchg, lists = load_symchg(), load_lists()

    seams = []
    for g in S["groups"]:
        if only and g["issuer"] != only:
            continue
        if g["kind"] == "cotrade":
            continue
        ka = {k["key"]: k for k in g["keys"]}
        for s in g["seams"]:
            seams.append((g, ka, s))
    print("%d seam(s) to gather evidence for" % len(seams), flush=True)

    res = []
    for n, (g, ka, s) in enumerate(seams, 1):
        old, new = s["old"], s["new"]
        a, b = ka[old], ka[new]
        rows_old = fetch_day(s["oldLast"])
        rows_new = fetch_day(s["newFirst"])
        r_old = next((r for r in rows_old if r[0].upper() == old), None)
        r_new = next((r for r in rows_new if r[0].upper() == new), None)
        # The new key's first session may have been traded under an ERA symbol (93c: bin keys are
        # post-merge canonical names). Identify that row from the FILE, two ways:
        #   ISIN prefix  — decisive, but the column only exists 2011..mid-2020;
        #   VOLUME       — 88b's identity rule. The bin stores the session's raw traded quantity,
        #                  so the row carrying that exact quantity IS the bar the key absorbed.
        era, era_how = [], None
        if not r_new:
            era = [r for r in rows_new if r[4].startswith(g["issuer"])]
            era_how = "isin" if era else None
            if not era:
                bar = BIN["data"].get(new)
                vol = bar["v"][bar["d"].index(s["newFirst"])] if bar and s["newFirst"] in bar["d"] else None
                if vol:
                    era = [r for r in rows_new if r[5] == vol]
                    era_how = "volume" if era else None
            if len(era) == 1:
                r_new = era[0]

        close_old = r_old[2] if r_old else None
        prev_new = r_new[3] if r_new else None
        rec = {
            "issuer": g["issuer"],
            "kind": g["kind"],
            "old": old,
            "new": new,
            "oldIsin": a["isin"],
            "newIsin": b["isin"],
            "oldIsinSrc": a["isinSrc"],
            "newIsinSrc": b["isinSrc"],
            "oldName": a["name"],
            "newName": b["name"],
            "oldAlive": a["alive"],
            "newAlive": b["alive"],
            "oldLast": s["oldLast"],
            "newFirst": s["newFirst"],
            "gapDays": s["gapDays"],
            "sameIsin": s["sameIsin"],
            "inRenameMap": rmap.get(old),
            "symchg": [r for r in symchg if old in (r["old"], r["new"]) or new in (r["old"], r["new"])],
            "equityL": {t: {k: d[k] for k in (old, new) if k in d} for t, d in lists.items() if old in d or new in d},
            "bhavOld": {
                "found": bool(r_old),
                "series": r_old[1] if r_old else None,
                "close": close_old,
                "prevclose": r_old[3] if r_old else None,
                "isin": r_old[4] if r_old else None,
            },
            "bhavNew": {
                "found": bool(r_new),
                "symbol": r_new[0] if r_new else None,
                "eraName": bool(r_new) and r_new[0].upper() != new,
                "series": r_new[1] if r_new else None,
                "close": r_new[2] if r_new else None,
                "prevclose": prev_new,
                "isin": r_new[4] if r_new else None,
            },
            "eraCandidates": [r[0] for r in era],
            "eraResolvedBy": era_how,
            "prevcloseFactors": factor_hits(close_old, prev_new),
        }
        res.append(rec)
        print(
            "  [%3d/%d] %-8s %-12s -> %-12s  close %s / prevclose %s  factors %s"
            % (n, len(seams), g["issuer"], old, new, close_old, prev_new, rec["prevcloseFactors"]),
            flush=True,
        )

    json.dump({"sfEnd": S["sfEnd"], "seams": res}, open(OUT, "w"), indent=1, sort_keys=True)
    print("\nwrote " + OUT)


if __name__ == "__main__":
    main()

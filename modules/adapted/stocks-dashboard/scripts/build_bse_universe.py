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
"""Build docs/bse_universe.json — the BSE-ONLY equity universe (stocks listed on BSE but NOT on NSE).

Our core price/fundamentals dataset is NSE-keyed, so ~2,700 BSE-only companies (e.g. Cella Space,
NSDL) never appear in the tool. This file is the backbone for covering them: one row per BSE-only
active-equity scrip with the metadata the pages need (ticker, name, ISIN, group, mcap, sector).

Sources (both bulk, no per-scrip loop for the base list):
- BSE `ListofScripData` — ALL active equity scrips (SCRIP_CD, scrip_id, ISIN, GROUP, FACE_VALUE, Mktcap…).
- NSE `EQUITY_L.csv` — the NSE ISIN set to subtract (BSE-only = ISIN not on NSE).

Sector is enriched per-scrip from BSE `ComHeadernew` (Industry), newest/biggest first, budgeted so a run
stays quick; already-known sectors are cached in scripts/_bse_sectors.json and reused.

Output: {"updated","count", "rows":[[scrip_cd, ticker, name, isin, group, faceval, mcap_cr, sector], …]}
        sorted by market cap desc. Guard: refuses to overwrite a good file with a tiny/failed fetch.

Run: python -X utf8 scripts/build_bse_universe.py [--sector-budget N]
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # §181 BSE headers
import csv
import datetime
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_fetch as B
import bse_names as BN  # §204: BSE's "-$" scrip-name marker never reaches a published name

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "bse_universe.json")
SEC_CACHE = os.path.join(HERE, "_bse_sectors.json")
NSE_CACHE = os.path.join(HERE, "_nse_universe.json")
MIN_ROWS = 800  # a broken fetch must never clobber a good universe


def nse_isin_set():
    """NSE equity ISINs (to subtract). Cached; refreshed from EQUITY_L.csv when possible."""
    import build_fundamentals as NB

    jar = NB.nse_jar()
    hdr = {
        "User-Agent": NB.UA,
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/market-data/securities-available-for-trading",
    }
    for url in (
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    ):
        try:
            raw = NB._get(url, headers=hdr, jar=jar, timeout=60)
            isin = set()
            syms = set()
            for row in csv.DictReader(io.StringIO(raw)):
                iz = (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or "").strip()
                sy = (row.get("SYMBOL") or "").strip()
                if iz:
                    isin.add(iz)
                if sy:
                    syms.add(sy)
            if len(isin) > 1500:
                json.dump({"isin": sorted(isin), "sym": sorted(syms)}, open(NSE_CACHE, "w"))
                return isin
        except Exception as ex:
            print(f"NSE list fetch failed ({str(ex)[:60]}), trying next/cache")
    if os.path.exists(NSE_CACHE):
        return set(json.load(open(NSE_CACHE))["isin"])
    raise SystemExit("no NSE ISIN set available")


def bse_active_equity(op):
    r = B.get(
        op,
        "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
        "?Group=&Scripcode=&industry=&segment=Equity&status=Active",
    )
    return json.loads(r if isinstance(r, str) else r.decode("utf8", "ignore"))


def sector_of(op, code, cache):
    k = str(code)
    if k in cache:
        return cache[k]
    try:
        r = B.get(
            op,
            "https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w"
            f"?quotetype=EQ&scripcode={code}&seriesid=",
        )
        j = json.loads(r if isinstance(r, str) else r.decode("utf8", "ignore"))
        sec = (j.get("Industry") or "").strip() or "Other"
    except Exception:
        sec = ""  # leave blank → retry next run
    cache[k] = sec
    return sec


SEEN = os.path.join(HERE, "bse_seen_scrips.json")
SEEN_DAYS = 120


def nse_tape_meta():
    """(symbols, ISINs) of the NSE tape from the committed docs/sf_stock_data.bin — only its trailing "meta" object is
    decoded (0.5 s; the bars are never parsed). Empty sets if the file is absent."""
    p = os.path.join(HERE, "..", "docs", "sf_stock_data.bin")
    try:
        import gzip

        b = gzip.decompress(open(p, "rb").read())
        m, _ = json.JSONDecoder().raw_decode(b[b.rfind(b'"meta":') + 7 :].decode("utf-8"))
    except (OSError, ValueError):
        return set(), set()
    return {k.upper() for k in m}, {v["isin"] for v in m.values() if v.get("isin")}


def seen_extra(allbse, nse, today=None):
    """Rows for BSE equities that TRADED within SEEN_DAYS (scripts/bse_seen_scrips.json, written by fetch_bse_bhav from
    each day's bhavcopy) but are absent from the Active list, ISIN not on NSE (exact, or the issuer of an NSE equity ISIN).
    §172: 77 such scrips traded on 21-Sep-2026 (groups XT/Z, once-a-week surveillance) with no presence on the site.
    Same shape as an API row; Mktcap 0 (unknown), FACE_VALUE 0, name/group from the bhavcopy."""
    try:
        seen = json.load(open(SEEN, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    today = today or datetime.date.today()
    floor = int((today - datetime.timedelta(days=SEEN_DAYS)).strftime("%Y%m%d"))
    have = {str(x.get("SCRIP_CD")) for x in allbse}
    tape_keys, tape_isin = nse_tape_meta()
    nse = set(nse) | tape_isin
    nse_iss = {i[:7] for i in nse if i.startswith("INE") and i[7:9] == "01"}
    out = []
    for code, (tk, name, isin, grp, last) in sorted(seen.items()):
        if code in have or last < floor or isin in nse or isin[:7] in nse_iss:
            continue
        # a symbol the NSE tape already owns (dead on NSE but still printing on BSE: RAMAPETRO, KANDAGIRI; BZ names
        # outside EQUITY_L: BLUECHIP, LASA) is not BSE-only — never a second page for it. A ticker coincidence with an
        # unrelated NSE key also lands here: that errs toward leaving a scrip out, never toward a duplicate.
        if tk.upper() in tape_keys:
            continue
        out.append(
            {
                "SCRIP_CD": int(code),
                "scrip_id": tk,
                "Scrip_Name": name,
                "ISIN_NUMBER": isin,
                "GROUP": grp,
                "FACE_VALUE": 0,
                "Mktcap": 0,
                "_seen": last,
            }
        )
    return out


def mcap(x):
    try:
        return round(float(x.get("Mktcap") or 0), 2)
    except Exception:
        return 0.0


def main():
    budget = 400
    if "--sector-budget" in sys.argv:
        budget = int(sys.argv[sys.argv.index("--sector-budget") + 1])
    op = B.session()
    time.sleep(1)
    nse = nse_isin_set()
    allbse = bse_active_equity(op)
    bse_only = [
        x
        for x in allbse
        if (x.get("ISIN_NUMBER") or "").strip() and (x.get("ISIN_NUMBER") or "").strip() not in nse
    ]
    extra = seen_extra(allbse, nse)
    bse_only += extra
    bse_only.sort(key=mcap, reverse=True)
    print(
        "BSE active equity %d; BSE-only %d (incl. %d traded but not on the Active list)"
        % (len(allbse), len(bse_only), len(extra))
    )

    cache = json.load(open(SEC_CACHE)) if os.path.exists(SEC_CACHE) else {}
    spent = 0
    rows = []
    for x in bse_only:
        code = x["SCRIP_CD"]
        sec = cache.get(str(code), "")
        if (
            not sec and spent < budget and (mcap(x) > 0 or x.get("_seen"))
        ):  # enrich biggest-first within budget
            sec = sector_of(op, code, cache)
            spent += 1
            if spent % 50 == 0:
                json.dump(cache, open(SEC_CACHE, "w"))
                time.sleep(0.2)
        try:
            fv = round(float(x.get("FACE_VALUE") or 0), 2)
        except Exception:
            fv = 0
        rows.append(
            [
                int(code),
                (x.get("scrip_id") or "").strip().upper(),
                BN.clean_scrip_name(x.get("Scrip_Name")),
                (x.get("ISIN_NUMBER") or "").strip(),
                (x.get("GROUP") or "").strip(),
                fv,
                mcap(x),
                sec,
            ]
        )
    json.dump(cache, open(SEC_CACHE, "w"))

    if len(rows) < MIN_ROWS and os.path.exists(OUT):
        raise SystemExit("ABORT: only %d rows — keeping existing bse_universe.json" % len(rows))

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    out = {
        "updated": ist.strftime("%Y-%m-%d %H:%M IST"),
        "count": len(rows),
        "sectors_known": sum(1 for r in rows if r[7]),
        "rows": rows,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(
        "WROTE %s: %d BSE-only stocks (%d with sector; +%d sectors this run)"
        % (os.path.normpath(OUT), len(rows), out["sectors_known"], spent)
    )


if __name__ == "__main__":
    main()

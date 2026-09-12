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
"""Backfill / update BSE daily closes + delivery% for the BSE-ONLY universe → docs/bse_prices.bin.

BSE-only stocks aren't in the NSE sf_stock_data.bin, so they have no price series → no last price,
no result-day reaction, no chart. This pulls BSE's UDiFF equity bhavcopy (one CSV per trading day,
~4,900 scrips, has ISIN/TckrSymb/ClsPric/TtlTradgVol) and keeps ONLY the BSE-only scrips.

Store: gzipped JSON  {"end": YYYYMMDD, "px": { "<scripcode>": {"d":[YYYYMMDD…], "c":[close…], "v":[vol…],
       "dv":[deliv%…]} }}  dates ascending, per scrip. Compact: closes 2dp, vols ints, deliv% 2dp
       (0 = unavailable; a TRUE 0.00% delivery day is stored as 0.01 so it stays distinguishable).

Delivery source: BSE gross-delivery file  bseindia.com/BSEDATA/gross/<YYYY>/SCBSEALL<DDMM>.zip
(pipe-separated TXT: DATE|SCRIP CODE|DELIVERY QTY|DELIVERY VAL|DAY'S VOLUME|DAY'S TURNOVER|DELV. PER.;
BSE T2T groups print their natural 100.00). Every run also SELF-HEALS delivery: any stored date where
no scrip has dv>0 (bounded by --dv-budget, default 600) gets its SCBSEALL fetched and applied — so the
first run after this feature lands backfills the whole store, and later runs converge to ~yesterday only.

Resumable + self-healing: appends every missing trading day between the file's `end` and today; a day
whose bhavcopy 404s (holiday/not-published-yet) is skipped. Weekend/holiday fetches just no-op.

Run:  python -X utf8 scripts/fetch_bse_bhav.py [--since YYYYMMDD] [--days N] [--dv-budget N]
      (default: from existing end+1, else last 400 calendar days, up to today)
"""
import bisect
import csv
import datetime
import gzip
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_fetch as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("BSE_PX_OUT") or os.path.join(HERE, "..", "docs", "bse_prices.bin")
UNIV = os.path.join(HERE, "..", "docs", "bse_universe.json")
BHAV = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_%s_F_0000.CSV"
GROSS = "https://www.bseindia.com/BSEDATA/gross/%d/SCBSEALL%s.zip"  # % (year, DDMM)


def load_prices():
    if os.path.exists(OUT):
        try:
            return json.loads(gzip.decompress(open(OUT, "rb").read()).decode("utf8"))
        except Exception:
            pass
    return {"end": 0, "px": {}}


def ensure_dv(s):
    """Pad a series' dv list to the length of d (0 = delivery unavailable for that date)."""
    dvl = s.setdefault("dv", [])
    if len(dvl) < len(s["d"]):
        dvl.extend([0] * (len(s["d"]) - len(dvl)))
    return dvl


def save_prices(d):
    # keep every scrip's series in ascending date order (backfill may add OLDER dates than existing)
    for s in d["px"].values():
        ensure_dv(s)
        if len(s["d"]) > 1 and any(s["d"][i] > s["d"][i + 1] for i in range(len(s["d"]) - 1)):
            order = sorted(range(len(s["d"])), key=lambda i: s["d"][i])
            for f in ("d", "c", "v", "dv"):
                s[f] = [s[f][i] for i in order]
    open(OUT, "wb").write(gzip.compress(json.dumps(d, separators=(",", ":")).encode("utf8"), 6))


def bse_only_codes():
    u = json.load(open(UNIV, encoding="utf-8"))
    # rows: [scrip_cd, ticker, name, isin, group, faceval, mcap, sector]
    return {str(r[0]) for r in u["rows"]}


def apply_delivery(px, di, dl):
    """Set dv for date di from {code: pct}; fill-only (never overwrites a non-zero). Returns cells set."""
    n = 0
    for code, s in px.items():
        pct = dl.get(code)
        if pct is None or not s["d"]:
            continue
        i = bisect.bisect_left(s["d"], di)
        if i >= len(s["d"]) or s["d"][i] != di:
            continue
        dvl = ensure_dv(s)
        if not dvl[i]:
            dvl[i] = pct
            n += 1
    return n


def heal_delivery(op, px, budget):
    """Backfill dv for stored dates that have no delivery yet (oldest first, up to budget days).
    Converges to ~yesterday-only once the store is filled; a day whose SCBSEALL never existed
    is retried each run but costs one cheap 404."""
    covered = set()
    alldates = set()
    for s in px.values():
        dvl = ensure_dv(s)
        for i, di in enumerate(s["d"]):
            alldates.add(di)
            if dvl[i]:
                covered.add(di)
    todo = sorted(alldates - covered)
    if not todo:
        return 0, 0
    done = 0
    cells = 0
    for di in todo[:budget]:
        d = datetime.date(di // 10000, di // 100 % 100, di % 100)
        dl = day_delivery(op, d)
        if dl:
            cells += apply_delivery(px, di, dl)
            done += 1
        time.sleep(0.12)
        if done and done % 25 == 0:
            print("  …dv healed %d days (%d cells so far)" % (done, cells))
    print("dv heal: %d/%d pending days fetched, %d cells set" % (done, len(todo), cells))
    return done, cells


def day_delivery(op, d):
    """Return {scripcode: deliv%} for one trading day from the SCBSEALL gross-delivery zip,
    or None when the file isn't published (holiday / too early). TRUE 0.00%-delivery rows
    are returned as 0.01 so 0 can stay the 'unavailable' sentinel in the store."""
    import zipfile

    try:
        raw = B.get(op, GROSS % (d.year, d.strftime("%d%m")), b=True)
    except Exception:
        return None
    if not raw or raw[:2] != b"PK":
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        text = z.read(z.namelist()[0]).decode("utf8", "ignore")
    except Exception:
        return None
    out = {}
    for line in text.split("\n"):
        p = line.strip().split("|")
        # DATE|SCRIP CODE|DELIVERY QTY|DELIVERY VAL|DAY'S VOLUME|DAY'S TURNOVER|DELV. PER.
        if len(p) < 7 or not p[1].strip().isdigit():
            continue
        try:
            pct = float(p[6])
        except ValueError:
            continue
        out[p[1].strip().lstrip("0") or "0"] = round(pct, 2) if pct > 0 else 0.01
    return out if len(out) > 500 else None


def day_closes(op, d):
    """Return {scripcode: (close, vol)} for one trading day, or None if no bhavcopy."""
    ymd = d.strftime("%Y%m%d")
    try:
        raw = B.get(op, BHAV % ymd, b=True)
    except Exception:
        return None
    if not raw or raw[:2] == b"<!" or (raw[:2] == b"PK" and b"html" in raw[:200].lower()):
        return None
    try:
        rd = csv.DictReader(io.StringIO(raw.decode("utf8", "ignore")))
    except Exception:
        return None
    out = {}
    for r in rd:
        code = (r.get("FinInstrmId") or "").strip()
        cls = r.get("ClsPric")
        if not code or not cls:
            continue
        try:
            c = round(float(cls), 2)
        except Exception:
            continue
        if c <= 0:
            continue
        try:
            v = int(float(r.get("TtlTradgVol") or 0))
        except Exception:
            v = 0
        out[code] = (c, v)
    return out if len(out) > 500 else None


def main():
    codes = bse_only_codes()
    data = load_prices()
    px = data["px"]
    today = datetime.date.today()
    if "--since" in sys.argv:
        start = datetime.datetime.strptime(sys.argv[sys.argv.index("--since") + 1], "%Y%m%d").date()
    elif data["end"]:
        start = datetime.datetime.strptime(str(data["end"]), "%Y%m%d").date() + datetime.timedelta(days=1)
    else:
        ndays = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 400
        start = today - datetime.timedelta(days=ndays)

    have = {code: set(s["d"]) for code, s in px.items()}  # dates already stored, per scrip
    op = B.session()
    time.sleep(1)
    d = start
    got = 0
    last = data["end"]
    while d <= today:
        # ALL calendar days — weekend special sessions (budget Saturdays, weekend muhurat,
        # DR-drill Saturdays) are real trading days the old weekday()<5 filter dropped.
        cl = day_closes(op, d)
        if cl:
            # duplicate guard: a weekend/holiday file whose closes ~all equal each scrip's
            # last stored close is a re-served prior-day file, not a session — skip it.
            same = tot = 0
            for code, s in px.items():
                t = cl.get(code)
                if t and s["c"]:
                    tot += 1
                    if abs(s["c"][-1] - t[0]) < 0.005:
                        same += 1
            if tot > 500 and same / tot > 0.99:
                print(f"  {d.isoformat()}: duplicate of prior session — skipped")
            else:
                di = int(d.strftime("%Y%m%d"))
                got += 1
                last = max(last, di)
                for code in codes:
                    t = cl.get(code)
                    if not t:
                        continue
                    s = px.get(code)
                    if s is None:
                        s = px[code] = {"d": [], "c": [], "v": []}
                        have[code] = set()
                    if di in have.get(code, ()):
                        continue  # already have this date (any order)
                    s["d"].append(di)
                    s["c"].append(t[0])
                    s["v"].append(t[1])
                    have.setdefault(code, set()).add(di)
                if got % 20 == 0:
                    data["end"] = last
                    save_prices(data)
                    print("  …%d days, through %d" % (got, last))
                    time.sleep(0.2)
        time.sleep(0.15)
        d += datetime.timedelta(days=1)

    # --- weekend special sessions (budget Saturdays, weekend muhurat, DR-drill Saturdays) ---
    # The forward walk only moves from `end`, and the old weekday()<5 filter skipped these for
    # years — so heal any that fall inside the stored span explicitly. save_prices() re-sorts
    # each series (dv stays aligned via ensure_dv) and heal_delivery() backfills their dv like
    # any other stored date. Idempotent: a date already present is skipped without a fetch.
    WEEKEND_HEAL = [
        20150228,
        20161030,
        20191027,
        20200201,
        20201114,
        20231112,
        20240120,
        20240302,
        20240518,
        20250201,
        20260201,
    ]
    floor = min((s["d"][0] for s in px.values() if s["d"]), default=None)
    for di in WEEKEND_HEAL:
        if floor is None or di <= floor or di > int(today.strftime("%Y%m%d")):
            continue
        if any(di in hs for hs in have.values()):
            continue  # already stored
        wd = datetime.date(di // 10000, di // 100 % 100, di % 100)
        cl = day_closes(op, wd)
        if not cl:
            print(f"  weekend {wd}: no BSE bhavcopy — skipped")
            time.sleep(0.15)
            continue
        # duplicate guard vs each scrip's close on its last session BEFORE this date
        same = tot = 0
        for code, s in px.items():
            t = cl.get(code)
            if not t or not s["d"]:
                continue
            k = bisect.bisect_left(s["d"], di) - 1
            if k >= 0:
                tot += 1
                if abs(s["c"][k] - t[0]) < 0.005:
                    same += 1
        if tot > 500 and same / tot > 0.99:
            print(f"  weekend {wd}: file duplicates the prior session — skipped")
            continue
        ins = 0
        for code in codes:
            t = cl.get(code)
            s = px.get(code)
            if not t or not s or not s["d"] or di in have.get(code, ()):
                continue
            if s["d"][0] > di:
                continue  # scrip's series starts later
            s["d"].append(di)
            s["c"].append(t[0])
            s["v"].append(t[1])
            have.setdefault(code, set()).add(di)
            ins += 1
        print("  weekend %s: inserted %d scrips" % (wd, ins))
        time.sleep(0.15)

    # --- bounded backward history backfill (optional, resumable) ------------------------------
    # The forward walk only extends `end` toward today, so a store that begins in (say) 2025 never
    # reaches 2020. With --backfill-floor YYYYMMDD, fetch up to --backfill-days N calendar days
    # BELOW the current earliest stored date, down to the floor. Bounded per run (fits the CI
    # timeout, ~N bhavcopy fetches) and resumable: the floor drops each run, so scheduled runs
    # converge to the floor over time WITHOUT re-fetching the days already stored above it.
    if "--backfill-floor" in sys.argv:
        bf_floor = int(sys.argv[sys.argv.index("--backfill-floor") + 1])
        bf_days = int(sys.argv[sys.argv.index("--backfill-days") + 1]) if "--backfill-days" in sys.argv else 90
        floor_date = datetime.date(bf_floor // 10000, bf_floor // 100 % 100, bf_floor % 100)
        cur = min((s["d"][0] for s in px.values() if s["d"]), default=None)
        if cur is None or cur <= bf_floor:
            print("  backfill: nothing to do (floor %d already reached; earliest=%s)" % (bf_floor, cur))
        else:
            d = datetime.date(cur // 10000, cur // 100 % 100, cur % 100) - datetime.timedelta(days=1)
            scanned = added = 0
            while d >= floor_date and scanned < bf_days:
                scanned += 1
                cl = day_closes(op, d)  # dated URL → holiday/no-file returns empty
                if cl:
                    di = int(d.strftime("%Y%m%d"))
                    ins = 0
                    for code in codes:
                        t = cl.get(code)
                        if not t:
                            continue
                        s = px.get(code)
                        if s is None:
                            s = px[code] = {"d": [], "c": [], "v": []}
                            have[code] = set()
                        if di in have.get(code, ()):
                            continue
                        s["d"].append(di)
                        s["c"].append(t[0])
                        s["v"].append(t[1])
                        have.setdefault(code, set()).add(di)
                        ins += 1
                    if ins:
                        added += 1
                        if added % 20 == 0:
                            save_prices(data)
                            print("  backfill …%d days added, at %d" % (added, di))
                            time.sleep(0.2)
                time.sleep(0.15)
                d -= datetime.timedelta(days=1)
            print("  backfill: scanned %d calendar days below %d, added %d trading days" % (scanned, cur, added))

    data["end"] = last
    save_prices(data)  # closes are safe on disk before the delivery pass touches anything
    # delivery layer: heal every stored date that still lacks dv (first run backfills the
    # whole store from SCBSEALL, later runs converge to just the freshly-appended days).
    # Shielded: a delivery-side failure must never cost the day's price append.
    dvb = int(sys.argv[sys.argv.index("--dv-budget") + 1]) if "--dv-budget" in sys.argv else 600
    try:
        heal_delivery(op, px, dvb)
    except Exception as ex:
        print(f"dv heal errored ({ex}) — prices unaffected, next run retries")
    save_prices(data)
    ncov = sum(1 for c in codes if c in px and px[c]["d"])
    ndv = sum(1 for c in codes if c in px and any(x > 0 for x in px[c].get("dv", ())))
    print(
        "WROTE %s: %d trading days added; %d/%d BSE-only scrips have prices (%d with delivery); end=%d"
        % (os.path.normpath(OUT), got, ncov, len(codes), ndv, last)
    )


if __name__ == "__main__":
    main()

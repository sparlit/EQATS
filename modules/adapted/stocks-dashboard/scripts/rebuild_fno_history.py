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
"""Rebuild scripts/fno_history.json from <START_YEAR>-01 -> today, SURVIVORSHIP-FREE, straight from
NSE's F&O bhavcopies (every stock with futures/options that month, using the POINT-IN-TIME ticker that
actually traded then — including names since delisted/renamed, e.g. IDFC, GMRINFRA, PVR, MCDOWELL-N).
The old build keyed membership off today's tickers, so it both DROPPED delisted names and back-labelled
older snapshots with modern tickers; this fixes both. Snapshots before START_YEAR are kept as-is.
Then patches docs/stock_data.bin's fnoHistory in place.

  python rebuild_fno_history.py            # 2020-01 -> today (default)
  python rebuild_fno_history.py 2001       # full history 2001-11 -> today (the real start)

Snapshots before START_YEAR are kept as-is, so a partial rebuild never truncates the deep history.
"""
import calendar
import csv
import datetime
import gzip
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "scripts" / "fno_history.json"
BIN = ROOT / "docs" / "stock_data.bin"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
IDX = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYIT",
    "NIFTYBANK",
    "BANKEX",
    "SENSEX",
    "SENSEX50",
    "NIFTYINFRA",
    "NIFTYPSE",
}


def _get(url):
    for _ in range(2):
        r = subprocess.run(
            ["curl", "-sL", "-A", UA, "-H", "Referer: https://www.nseindia.com/", "--max-time", "45", url],
            capture_output=True,
            timeout=70,
        )
        if len(r.stdout) > 500:
            return r.stdout
        time.sleep(1.0)
    return None


def _parse(data, sym_keys, tp_key, tp_ok):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        text = zf.read(zf.namelist()[0]).decode("utf-8", "ignore")
    except Exception:
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return None
    cols = {c.strip(): c for c in rows[0]}
    tp_c = cols.get(tp_key)
    sym_c = next((cols[k] for k in sym_keys if k in cols), None)
    if not tp_c or not sym_c:
        return None
    out = set()
    for row in rows:
        if (row.get(tp_c) or "").strip().upper() in tp_ok:
            s = (row.get(sym_c) or "").strip()
            if s and s not in IDX:
                out.add(s)
    return out or None


def min_expected(dt):
    """Floor for 'this looks like a real F&O day', by ERA.

    ⚠️ A FLAT >=50 FLOOR SILENTLY TRUNCATES THE HISTORY. Stock derivatives launched 2001-11-09 with
    31 underlyings and did not pass 50 until 2003-09-30 (measured on the rebuilt history: 8 months
    sit below 50, min 29 at 2002-10-31). With a flat 50 every month before 2003-09 is discarded as
    "not a real F&O day", the file starts late, and `lastSnap`'s `|| list[0]` turns that into a
    look-ahead — the exact bug fixed on 2026-08-12 (runbook §8)."""
    return 20 if dt < datetime.date(2003, 9, 1) else 50


def fno_on(dt):
    ymd = dt.strftime("%Y%m%d")
    udiff = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
    mon = dt.strftime("%b").upper()
    old = f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{dt.year}/{mon}/fo{dt.strftime('%d')}{mon}{dt.year}bhav.csv.zip"
    order = [(udiff, "udiff"), (old, "old")] if dt >= datetime.date(2024, 7, 1) else [(old, "old"), (udiff, "udiff")]
    for url, kind in order:
        data = _get(url)
        if not data:
            continue
        if kind == "udiff":
            s = _parse(data, ["TckrSymb", "SYMBOL"], "FinInstrmTp", {"STF", "STO"})
        else:
            s = _parse(data, ["SYMBOL", "TckrSymb"], "INSTRUMENT", {"FUTSTK", "OPTSTK"})
        if s and len(s) >= min_expected(dt):
            return sorted(s)
    return None


def last_trading_snapshot(y, m):
    last = calendar.monthrange(y, m)[1]
    for back in range(7):
        dt = datetime.date(y, m, last) - datetime.timedelta(days=back)
        if dt > datetime.date.today():
            continue
        s = fno_on(dt)
        if s:
            return dt.isoformat(), s
        time.sleep(0.3)
    return None, None


START_Y = int(sys.argv[1]) if len(sys.argv) > 1 else 2020
today = datetime.date.today()
snaps = []
y, m = START_Y, 1
while (y, m) <= (today.year, today.month):
    eff, syms = last_trading_snapshot(y, m)
    if syms:
        snaps.append((eff, syms))
        print(f"  {y}-{m:02d}: {eff} -> {len(syms)} F&O stocks  (IDFC={'IDFC' in syms}, GVT&D={'GVT&D' in syms})")
    else:
        print(f"  {y}-{m:02d}: no bhavcopy found — skip")
    m += 1
    if m > 12:
        m = 1
        y += 1
    time.sleep(0.3)

# dedup consecutive identical membership (keep first of each unchanged run)
deduped = []
for eff, syms in snaps:
    if deduped and set(syms) == set(deduped[-1]["symbols"]):
        continue
    deduped.append({"effectiveDate": eff, "symbols": syms})

existing = json.loads(HIST.read_text())
KEEP = f"{START_Y}-01-01"
kept = [s for s in existing if s["effectiveDate"] < KEEP]
new = kept + deduped
new.sort(key=lambda s: s["effectiveDate"])
HIST.write_text(json.dumps(new, separators=(",", ":")))
print(f"\nfno_history.json: {len(kept)} kept (<{KEEP}) + {len(deduped)} rebuilt >={START_Y} = {len(new)} total")

D = json.loads(gzip.decompress(BIN.read_bytes()))
D["fnoHistory"] = new
BIN.write_bytes(gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 6))
idfc = [s["effectiveDate"] for s in new if "IDFC" in set(s["symbols"])]
print(
    f"patched stock_data.bin. IDFC now in {len(idfc)} snaps ({idfc[0] if idfc else '-'} .. {idfc[-1] if idfc else '-'}); latest snap {new[-1]['effectiveDate']}"
)

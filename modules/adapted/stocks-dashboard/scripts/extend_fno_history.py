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
"""Extend scripts/fno_history.json with recent point-in-time F&O membership from NSE's daily
derivatives bhavcopy (survivorship-free: who actually had stock futures on that date), and patch
docs/stock_data.bin's fnoHistory in place (build_membership_v2.py preserves fnoHistory, so this
sticks through the weekly refresh).

Usage:  python extend_fno_history.py YYYYMMDD [YYYYMMDD ...]
  (no args -> uses a sensible default set of recent month-end trading days)
"""
import csv
import datetime
import gzip
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "scripts" / "fno_history.json"
BIN = ROOT / "docs" / "stock_data.bin"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
INDEX_UND = {
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
}


def fno_stocks_on(yyyymmdd):
    """Distinct stock-F&O underlyings trading on a date, from the UDiFF derivatives bhavcopy."""
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
    r = subprocess.run(
        ["curl", "-sL", "-A", UA, "-H", "Referer: https://www.nseindia.com/", "--max-time", "45", url],
        capture_output=True,
        timeout=70,
    )
    data = r.stdout
    if len(data) < 500:
        print(f"  {yyyymmdd}: response too short ({len(data)} b) — not a trading day / blocked")
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        text = zf.read(zf.namelist()[0]).decode("utf-8", "ignore")
    except Exception as e:
        print(f"  {yyyymmdd}: not a zip ({e})")
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        print(f"  {yyyymmdd}: empty csv")
        return None
    cols = {c.strip(): c for c in rows[0]}
    tp_c = cols.get("FinInstrmTp") or cols.get("OptnTp") or cols.get("InstrmTp")
    sym_c = cols.get("TckrSymb") or cols.get("SYMBOL") or cols.get("Symbol")
    if not tp_c or not sym_c:
        print(f"  {yyyymmdd}: cols not found ({list(cols)[:8]})")
        return None
    und = set()
    for row in rows:
        tp = (row.get(tp_c) or "").strip().upper()
        if tp in ("STF", "STO", "FUTSTK", "OPTSTK"):  # stock futures/options only
            s = (row.get(sym_c) or "").strip()
            if s and s not in INDEX_UND:
                und.add(s)
    return sorted(und)


# Explicit dates = backfill mode. No args = cron mode: snapshot the LATEST available trading day
# (try today back 7 days; first valid bhavcopy wins).
LATEST = not sys.argv[1:]
targets = sys.argv[1:] or [(datetime.date.today() - datetime.timedelta(days=i)).strftime("%Y%m%d") for i in range(7)]
hist = json.loads(HIST.read_text())
existing = {s["effectiveDate"] for s in hist}
hist.sort(key=lambda s: s["effectiveDate"])
prev = set(hist[-1]["symbols"]) if hist else set()
added = []
for yd in targets:
    syms = fno_stocks_on(yd)
    # Era-aware floor. Today a real F&O day has ~200 stocks, but the universe launched 2001-11 with
    # 31 and only passed 50 on 2003-09-30 (min 29 at 2002-10-31). A flat 50 would silently discard
    # every backfill date before 2003-09 — see min_expected() in rebuild_fno_history.py + runbook §8.
    floor = 20 if yd < "20030901" else 50
    if not syms or len(syms) < floor:
        if not LATEST:
            print(f"  {yd}: skipped (got {len(syms) if syms else 0})")
        continue
    eff = f"{yd[:4]}-{yd[4:6]}-{yd[6:]}"
    print(f"  {eff}: {len(syms)} F&O stocks  (GVT&D present: {'GVT&D' in syms})")
    if eff in existing:
        print("    already in history — skip")
    elif set(syms) == prev:
        print("    identical to prior snapshot — skip (no membership change)")
    else:
        hist.append({"effectiveDate": eff, "symbols": syms})
        added.append((eff, len(syms)))
        prev = set(syms)
    if LATEST:
        break  # cron: only the latest available trading day

hist.sort(key=lambda s: s["effectiveDate"])
HIST.write_text(json.dumps(hist, separators=(",", ":")))
print("fno_history.json snapshots:", len(hist), "| appended:", added)

# patch stock_data.bin in place (preserve everything else; just swap fnoHistory)
D = json.loads(gzip.decompress(BIN.read_bytes()))
D["fnoHistory"] = hist
BIN.write_bytes(gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 6))
print(
    "patched docs/stock_data.bin fnoHistory -> latest",
    hist[-1]["effectiveDate"],
    f"({len(hist[-1]['symbols'])} stocks)",
)

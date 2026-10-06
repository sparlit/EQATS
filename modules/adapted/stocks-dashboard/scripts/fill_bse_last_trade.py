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
# -*- coding: utf-8 -*-
"""Last traded price + date for BSE-only dashboard rows that still have NO price series after the
Yahoo fetch and the bhavcopy-store fills. DATA_RUNBOOK §145.

WHY: 66 BSE-only rows (2026-09-23) had no bar at all in BSE's own daily bhavcopy since 2023-12 — the
store watches them every day and BSE printed no trade. They are LISTED but untraded. BSE's scrip header
(getScripHeaderData) still states the last trade: `Header.LTP` and `Header.Ason` ("29 Jul 20 | 16:00" =
Apex Capital's last session). Measured: 27 last traded 2001-2023, 36 show LTP 0.00 (no trade on record),
3 are group IP (BSE's institutional trading platform: no public quote at all). The page shows the last
price with "not traded since <date>", or "no trades on record", instead of a blank row.

Output: meta[ticker]["lastTrade"] = {"d": "YYYY-MM-DD" | null, "p": float | null} in
scripts/stock_data.json, and a ticker-keyed cache scripts/bse_last_trade.json (re-checked after
MAX_AGE_DAYS, so a normal run makes few BSE calls). Non-fatal in refresh.yml.
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import bse_headers as BH  # §181 BSE headers
import os
import json
import time
import datetime
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PAYLOAD = os.path.join(HERE, "stock_data.json")
LEDGER = os.path.join(HERE, "bse_last_trade.json")
# BSE's quote page forgets old trades (LTP 0.00 for scrips whose last session is years back). Their real
# last trade comes from BSE's own daily archive (EQ_ISINCODE_/EQ..._CSV files, 2007-01 -> 2023-12),
# scanned once: {"scanned": [from, to], "rows": {code: {d, p, trades, file}}, "none": [codes with no
# trade in the whole span]}. Written by a one-off scan (DATA_RUNBOOK §145); read-only here.
ARCHIVE = os.path.join(HERE, "bse_last_trade_archive.json")
UNIV = os.path.join(ROOT, "docs", "bse_universe.json")
MAX_AGE_DAYS = 7


def header(code):
    out = subprocess.run(
        [
            "curl",
            "-s",
            "--max-time",
            "30",
            "-A",
            BH.UA,
            *BH.CURL_ARGS,
            f"https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w?Debtflag=&scripcode={code}&seriesid=",
        ],
        capture_output=True,
        timeout=45,
    ).stdout
    return (json.loads(out or b"{}") or {}).get("Header") or {}


def main():
    try:
        led = json.load(open(LEDGER, encoding="utf-8"))
    except Exception:
        led = {
            "_doc": "Last BSE trade per BSE-only dashboard ticker with no price series "
            "(getScripHeaderData LTP + Ason). Written by scripts/fill_bse_last_trade.py. §145.",
            "rows": {},
        }
    rows = led.setdefault("rows", {})
    payload = json.load(open(PAYLOAD, encoding="utf-8"))
    meta, series = payload["meta"], payload["series"]
    sid2code = {}
    for src in (UNIV, "/tmp/bse.json"):
        try:
            j = json.load(open(src, encoding="utf-8"))
            if isinstance(j, dict):
                for r in j.get("rows") or ():
                    sid2code.setdefault(str(r[1]).upper(), str(r[0]))
            else:
                for b in j:
                    sid, code = (
                        (b.get("scrip_id") or "").strip().upper(),
                        (b.get("SCRIP_CD") or "").strip(),
                    )
                    if sid and code:
                        sid2code.setdefault(sid, code)
        except Exception:
            pass
    try:
        arch = json.load(open(ARCHIVE, encoding="utf-8"))
    except Exception:
        arch = {}
    arows, anone, aspan = (
        arch.get("rows") or {},
        set(arch.get("none") or ()),
        arch.get("scanned") or [None, None],
    )
    today = datetime.date.today()
    todo = [t for t in meta if t.endswith(".BO") and not series.get(t)]
    fetched = cached = nocode = 0
    for t in todo:
        cur = rows.get(t) or {}
        try:
            age = (today - datetime.date.fromisoformat(cur.get("checked", "1900-01-01"))).days
        except ValueError:
            age = 9999
        if age > MAX_AGE_DAYS:
            base = t[:-3]
            code = base if base.isdigit() else sid2code.get(base.upper())
            if not code:
                nocode += 1
                continue
            try:
                h = header(code)
            except Exception as e:
                print(f"  {t}: header failed ({e!r})")
                continue
            ason = (h.get("Ason") or "").split("|")[0].strip()
            try:
                d = datetime.datetime.strptime(ason, "%d %b %y").date().isoformat()
            except ValueError:
                d = None
            try:
                p = float(h.get("LTP") or 0)
            except ValueError:
                p = 0.0
            # LTP 0.00 is BSE's "no trade on record"; its Ason is then just today's page time, not a trade
            cur = {
                "code": code,
                "p": (round(p, 2) if p > 0 else None),
                "d": (d if p > 0 else None),
                "quote": bool(h),
                "checked": today.isoformat(),
            }
            rows[t] = cur
            fetched += 1
            time.sleep(0.8)
        else:
            cached += 1
        lt = {"d": cur.get("d"), "p": cur.get("p")}
        if not lt["p"]:
            a = arows.get(cur.get("code") or "")
            if a and a.get("p"):
                lt = {
                    "d": a["d"],
                    "p": a["p"],
                    "src": "bse-archive",
                }  # last trade from BSE's daily archive
            elif (cur.get("code") or "") in anone and aspan[0]:
                lt["since"] = aspan[0]  # measured: no BSE trade since then
        meta[t]["lastTrade"] = lt
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1, sort_keys=True)
    json.dump(payload, open(PAYLOAD, "w", encoding="utf-8"), separators=(",", ":"))
    withp = sum(1 for t in todo if (meta[t].get("lastTrade") or {}).get("p"))
    print(
        "fill_bse_last_trade: %d price-less .BO rows — %d fetched, %d cached, %d without a code; "
        "%d have a last trade, %d have none on record"
        % (len(todo), fetched, cached, nocode, withp, len(todo) - withp - nocode)
    )


if __name__ == "__main__":
    main()

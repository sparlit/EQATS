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
"""Phase 2: fetch SHPQNewFormat for every symbol carrying a post-2016 convention cell.
Raw tables cached to raw_full.jsonl (F4 rule: a matcher tweak must never cost another crawl).
Resumable — skips symbols already in the output. Sharded like the redating campaign.

Run: fetch_full.py <shard_index> <n_shards>
"""
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SCRIPTS, "_staleness_fix"))
import contextlib

import fetch_and_match as m
import shp_dates as SD

API = "https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode="


def main():
    shard = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    nsh = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    out_p = os.path.join(HERE, f"full_shard{shard}.json")
    raw_p = os.path.join(HERE, f"raw_full{shard}.jsonl")
    log_p = os.path.join(HERE, f"full_shard{shard}.log")

    def log(msg):
        with open(log_p, "a") as f:
            f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")

    shp = json.load(open(os.path.join(ROOT, "docs", "shp_engine.json")))
    by_id = json.load(open(os.path.join(SCRIPTS, "bse_scrips.json")))["by_id"]
    master = {}
    for r in json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json"))):
        sid, cd = r.get("scrip_id"), r.get("SCRIP_CD")
        if sid and cd and sid not in master:
            with contextlib.suppress(TypeError, ValueError):
                master[sid] = int(cd)

    targets = {}
    for sym, rows in shp.items():
        conv = [
            q[0]
            for q in rows
            if isinstance(q, list) and len(q) > 3 and q[0] >= 20160101 and SD.is_convention(q[0], q[3])
        ]
        if conv:
            targets[sym] = sorted(conv)
    syms = sorted(targets)[shard::nsh]
    results = json.load(open(out_p)) if os.path.exists(out_p) else {}
    log(f"START shard {shard}/{nsh}: {len(syms)} symbols, {len(results)} already done")

    done = 0
    for sym in syms:
        if sym in results:
            continue
        sc = by_id.get(sym) or master.get(sym)
        entry = {"scripcode": sc, "resolved": {}, "error": None}
        if not sc:
            entry["error"] = "no-scripcode"
            log(f"  SKIP {sym}: no-scripcode")
        else:
            try:
                table = json.loads(m.get(API + str(sc), timeout=30))["Table"]
                with open(raw_p, "a") as f:
                    f.write(json.dumps({"sym": sym, "scripcode": sc, "table": table}, separators=(",", ":")) + "\n")
                res = SD.resolve_rows(table)
                entry["resolved"] = {str(k): v for k, v in res.items()}
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
                log(f"  FAILED {sym}: {entry['error']}")
        results[sym] = entry
        done += 1
        if done % 25 == 0:
            json.dump(results, open(out_p, "w"))
            log(f"CHECKPOINT {len(results)}/{len(syms)}")
        time.sleep(0.3)
    json.dump(results, open(out_p, "w"))
    log(f"COMPLETE done={len(results)}")


if __name__ == "__main__":
    main()

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


"""Retry only the PE samples that hit rate limit, then merge into baseline JSON."""
import json
import os
import sys
import time
import urllib.request

API_KEY = os.environ.get("OPENALGO_API_KEY")
if not API_KEY:
    sys.exit("Set OPENALGO_API_KEY before running this benchmark.")
URL = "http://127.0.0.1:5000/api/v1/optiongreeks"
PATH = "docs/benchmarks/greeks_baseline_pyvollib.json"

with open(PATH) as f:
    data = json.load(f)

failed = [r for r in data["samples"] if r["response"].get("status") != "success"]
print(f"Retrying {len(failed)} samples at 1 req/sec...")

for r in failed:
    body = json.dumps({"apikey": API_KEY, "exchange": "NFO", "symbol": r["symbol"]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read().decode())
    dt_ms = (time.perf_counter() - t0) * 1000.0
    r["response"] = payload
    r["latency_ms"] = round(dt_ms, 2)
    print(
        f"{r['type']} {r['strike']:>5} {r['moneyness']:<9} {dt_ms:6.1f} ms  status={payload.get('status')}"
    )
    time.sleep(1.1)

with open(PATH, "w") as f:
    json.dump(data, f, indent=2)
print(f"\nMerged → {PATH}")

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


"""
Post-migration benchmark: /api/v1/optiongreeks now backed by opengreeks.
Replays the same 40 symbols as the baseline so we get an apples-to-apples diff.
Pacing: 1.1s between calls to stay under the 30/min rate limit.
"""
import json
import os
import sys
import time
import urllib.request

API_KEY = os.environ.get("OPENALGO_API_KEY")
if not API_KEY:
    sys.exit("Set OPENALGO_API_KEY before running this benchmark.")
URL = "http://127.0.0.1:5000/api/v1/optiongreeks"
BASELINE = "docs/benchmarks/greeks_baseline_pyvollib.json"
OUT = "docs/benchmarks/greeks_post_opengreeks.json"

with open(BASELINE) as f:
    baseline = json.load(f)

samples_in = baseline["samples"]
out_samples = []

for s in samples_in:
    body = json.dumps({"apikey": API_KEY, "exchange": "NFO", "symbol": s["symbol"]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            payload = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read().decode())
    dt_ms = (time.perf_counter() - t0) * 1000.0
    out_samples.append(
        {
            "type": s["type"],
            "strike": s["strike"],
            "moneyness": s["moneyness"],
            "symbol": s["symbol"],
            "latency_ms": round(dt_ms, 2),
            "response": payload,
        }
    )
    print(
        f"{s['type']} {s['strike']:>5} {s['moneyness']:<9} {dt_ms:6.1f} ms  status={payload.get('status')}"
    )
    time.sleep(1.1)

with open(OUT, "w") as f:
    json.dump(
        {
            "engine": "opengreeks==0.1.0 (Black-76)",
            "spot": baseline["spot"],
            "expiry": baseline["expiry"],
            "samples": out_samples,
        },
        f,
        indent=2,
    )
print(f"\nSaved → {OUT}")

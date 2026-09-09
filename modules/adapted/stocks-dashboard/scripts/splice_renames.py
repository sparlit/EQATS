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
"""Splice pre-rename old-ticker price history into renamed symbols so the 2020-21 backtest
window can screen them. Surviving-entity renames -> prices continuous for that window."""
import gzip
import json

path = "docs/sf_stock_data.bin"
D = json.loads(gzip.decompress(open(path, "rb").read()))
data = D["data"]
renames = [
    ("ADANIENSOL", "ADANITRANS"),
    ("ANGELONE", "ANGELBRKG"),
    ("COHANCE", "SUVENPHAR"),
    ("SHRIRAMFIN", "SRTRANSFIN"),
    ("PCBL", "PHILIPCARB"),
]
FIELDS = ["d", "c", "t", "hb", "lb", "ob", "v", "dv", "vw"]
for new, old in renames:
    n = data[new]
    o = data.get(old)
    if not o:
        print("SKIP", new, "no", old)
        continue
    new_start = n["d"][0]
    idx = [i for i, dd in enumerate(o["d"]) if dd < new_start]
    if not idx:
        print("SKIP", new, "no older pts")
        continue
    flds = [f for f in FIELDS if f in o and f in n]
    for f in flds:
        n[f] = [o[f][i] for i in idx] + n[f]
    print("%s spliced %d pts from %s -> starts %d n=%d" % (new, len(idx), old, n["d"][0], len(n["d"])))
buf = gzip.compress(json.dumps(D, separators=(",", ":")).encode())
open(path, "wb").write(buf)
print("SAVED", len(buf), "bytes")

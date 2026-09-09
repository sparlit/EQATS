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
import re
import sys
from collections import defaultdict

import fitz

pdf_path, page = sys.argv[1], int(sys.argv[2])
doc = fitz.open(pdf_path)
pg = doc[page]
# header detection
low = pg.get_text().lower()
print("--- unit hint ---")
for kw in ["lakh", "lac", "crore", "million", "rupees in"]:
    if kw in low:
        print("  found:", kw)
print("--- profit-related rows (with x-sorted cells) ---")
rows = defaultdict(list)
for w in pg.get_text("words"):
    rows[round(w[1] / 3) * 3].append((w[0], w[4]))
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
for y in sorted(rows):
    cells = sorted(rows[y])
    txt = " ".join(w for _, w in cells)
    l = txt.lower()
    if (
        "profit" in l
        or "quarter ended" in l
        or "period ended" in l
        or "year ended" in l
        or "particulars" in l
        or "ended" in l
    ):
        nums = [(round(x), w) for x, w in cells if NUM.match(w.replace(",", ""))]
        label = " ".join(w for x, w in cells if not NUM.match(w.replace(",", "")))
        print("y=%4d | %s || nums=%s" % (y, label[:60], nums))

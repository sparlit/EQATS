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
import json
import re
import sys
from collections import defaultdict

import fitz

pdf_path = sys.argv[1]
basis = sys.argv[2]  # 'std' or 'con'
doc = fitz.open(pdf_path)
print("PAGES:", len(doc))

want = "consolidated" if basis == "con" else "standalone"
PFT = re.compile(r"profit")
for p in range(len(doc)):
    low = doc[p].get_text().lower()
    has_basis = want in low
    has_qe = ("quarter ended" in low) or ("period ended" in low) or ("quarter and" in low)
    has_profit = (
        ("profit for the" in low)
        or ("profit after tax" in low)
        or ("profit/(loss)" in low)
        or ("profit /(loss)" in low)
    )
    if has_basis and has_profit and has_qe:
        # also flag if the OTHER basis appears (to avoid combined pages confusion)
        other = "standalone" if basis == "con" else "consolidated"
        print("PAGE %d  basis=%s other_also=%s" % (p, has_basis, other in low))

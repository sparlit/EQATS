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
import sys

import fitz

pdf_path, page, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
y0, y1 = float(sys.argv[4]), float(sys.argv[5])
doc = fitz.open(pdf_path)
pg = doc[page]
r = pg.rect
clip = fitz.Rect(r.x0, r.y0 + (r.height * y0), r.x1, r.y0 + (r.height * y1))
pix = pg.get_pixmap(dpi=320, clip=clip)
pix.save(out)
print("saved", out, pix.width, "x", pix.height)

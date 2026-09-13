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
"""Seed common tags into tag_master table."""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / "web" / ".env"
load_dotenv(env_path)

DATABASE_URL = os.environ["DATABASE_URL"]

TAGS = [
    # Themes
    "AI",
    "Data Centre",
    "Data Centre Cooling",
    "Data Centre Infra",
    "Semiconductor",
    "Wire & Cable",
    "Defence",
    "Aerospace",
    "IT Services",
    "Solar/Renewable",
    "EV",
    "Infrastructure",
    # Sectors
    "FMCG",
    "Pharma",
    "Banking",
    "NBFC",
    "Insurance",
    "Real Estate",
    "Auto",
    "Chemical",
    "Specialty Chemical",
    "Logistics",
    "Retail",
    "Telecom",
    "PSU",
    # Investment style
    "Largecap",
    "Midcap",
    "Smallcap",
    "Dividend",
    "Watchlist",
    "High Conviction",
]


def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    for tag in TAGS:
        cur.execute("INSERT INTO tag_master (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (tag,))
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"Done: {inserted} inserted, {skipped} already existed")


if __name__ == "__main__":
    main()

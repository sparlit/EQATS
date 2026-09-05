#!/usr/bin/env python3
"""Seed common tags into tag_master table."""
import os
import sys
from pathlib import Path
import psycopg2
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / 'web' / '.env'
load_dotenv(env_path)

DATABASE_URL = os.environ['DATABASE_URL']

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
        cur.execute(
            "INSERT INTO tag_master (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (tag,)
        )
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"Done: {inserted} inserted, {skipped} already existed")

if __name__ == '__main__':
    main()

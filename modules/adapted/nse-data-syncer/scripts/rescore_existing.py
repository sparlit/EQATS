from __future__ import annotations

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
Re-download and rescore all presentations already in the DB.
Uses presentation_url already stored — no NSE API scanning.

Usage:
  python scripts/rescore_existing.py               # all companies with a stored URL
  python scripts/rescore_existing.py --resume-after SYMBOL
"""

import argparse
import io
import sys
import time

import psycopg2

sys.path.insert(0, "/Users/gurudayal/Desktop/data-syncer/scripts")
import pdfplumber
from keyword_analysis import (
    ALTER_TABLE_SQL,
    DB,
    DB_URL,
    THEME_COLUMNS,
    analyse_sentiment,
    clean_db_url,
    count_theme_keywords,
    download_pdf,
    extract_text,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-after", default="")
    args = parser.parse_args()

    db = DB(clean_db_url(DB_URL))

    # Ensure new columns exist
    for stmt in ALTER_TABLE_SQL:
        db.execute(stmt)
    db.commit()

    db.execute("""
        SELECT symbol, company_name, result_date, presentation_url
        FROM presentation_keyword_analysis
        WHERE has_presentation = TRUE AND presentation_url IS NOT NULL AND presentation_url != ''
        ORDER BY symbol
    """)
    rows = db.fetchall()

    if args.resume_after:
        rows = [(s, n, d, u) for s, n, d, u in rows if s.upper() > args.resume_after.upper()]

    print(f"Companies to rescore: {len(rows)}\n")

    update_cols = [
        "presentation_url",
        "pdf_pages",
        "pdf_chars",
        *THEME_COLUMNS,
        "word_count",
        "positive_hits",
        "negative_hits",
        "positive_density",
        "negative_density",
        "sentiment_score",
    ]
    update_sql = f"""
        UPDATE presentation_keyword_analysis SET
            {", ".join(f"{c} = %s" for c in update_cols)},
            analysed_at = NOW()
        WHERE symbol = %s AND result_date = %s
    """

    for i, (symbol, _company_name, result_date, pres_url) in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {symbol} ({result_date}) … ", end="", flush=True)

        pdf_bytes = download_pdf(pres_url)
        if not pdf_bytes:
            print("download failed, skipping")
            continue

        text = extract_text(pdf_bytes)
        theme_counts = count_theme_keywords(text)
        sentiment = analyse_sentiment(text)

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                n_pages = len(pdf.pages)
        except Exception:
            n_pages = 0

        kw_display = ", ".join(f"{k}={v}" for k, v in theme_counts.items() if v > 0) or "no theme matches"
        print(f"{n_pages}pp → {kw_display}")

        values = [pres_url, n_pages, len(text)]
        values += [theme_counts[c] for c in THEME_COLUMNS]
        values += [
            sentiment["word_count"],
            sentiment["positive_hits"],
            sentiment["negative_hits"],
            sentiment["positive_density"],
            sentiment["negative_density"],
            sentiment["sentiment_score"],
        ]
        values += [symbol, result_date]

        db.execute(update_sql, values)
        db.commit()

        time.sleep(0.5)

    db.close()
    print("\nDone.")


if __name__ == "__main__":
    main()

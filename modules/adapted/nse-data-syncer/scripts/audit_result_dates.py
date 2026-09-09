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
Audit symbols whose pead_announcements EARLIEST row is "Outcome of Board
Meeting" but the next row comes 10+ days later — a sign the first row may
be a false positive (board meeting about something other than results,
e.g. auditor appointment, that is_result() wrongly accepted).

For each flagged symbol, walk its full pead_announcements history in time
order. For each "Outcome of Board Meeting" row, re-fetch that day's NSE
announcement by seq_id and check whether it is genuinely about results
(see is_genuine_result). Stop at the first genuine row — everything before
it is a false positive to delete. Rows with a different subject are
trusted as-is (is_result()'s RESULT_KEYWORDS check already covers them).

Usage:
  python3 scripts/audit_result_dates.py            # dry run, just reports
  python3 scripts/audit_result_dates.py --fix      # apply fixes + re-analyse
"""

import argparse
import re
import subprocess
import sys
import time
from datetime import timedelta, timezone

from keyword_analysis import DB, DB_URL, clean_db_url, fetch_nse_day

IST = timezone(timedelta(hours=5, minutes=30))

# Most genuine results outcomes use NSE's generic boilerplate ("X Limited has
# informed the Exchange regarding Outcome of [the] Board Meeting held on
# <date>.") because the actual financial figures live in the XBRL/PDF, not
# this text field. Only treat a filing as suspicious if it names something
# ELSE specific instead of (or in addition to) that generic phrase.
GENERIC_OUTCOME_RE = re.compile(
    r"^.*\boutcome of (the )?board meeting\b(\s+held on [^.]+)?\.?\s*$",
    re.IGNORECASE,
)


def is_genuine_result(desc: str, attchmnt_text: str) -> bool:
    text = (attchmnt_text or "").strip()
    combined = (desc + " " + text).lower()
    if "result" in combined:
        return True
    if text == "" or GENERIC_OUTCOME_RE.match(text):
        return True
    return False


FLAG_QUERY = """
WITH per_symbol AS (
  SELECT id, symbol, seq_id, announced_at, subject,
         ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY announced_at) AS rn
  FROM pead_announcements
)
SELECT a.id, a.symbol, a.seq_id, a.announced_at
FROM per_symbol a
JOIN per_symbol b ON a.symbol = b.symbol AND b.rn = 2
WHERE a.rn = 1
  AND a.subject ILIKE '%outcome of board meeting%'
  AND (b.announced_at - a.announced_at) > INTERVAL '10 days'
ORDER BY a.symbol
"""

HISTORY_QUERY = """
SELECT id, seq_id, announced_at, subject
FROM pead_announcements
WHERE symbol = %s
ORDER BY announced_at
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    db = DB(clean_db_url(DB_URL))
    db.execute(FLAG_QUERY)
    flagged = db.fetchall()
    symbols = [s for _, s, _, _ in flagged]
    print(f"{len(symbols)} symbols flagged for review\n")

    day_cache: dict[str, list[dict]] = {}
    # symbol -> (list of bad row ids to delete, new correct result_date)
    fixes: dict[str, tuple[list[int], object]] = {}

    for i, symbol in enumerate(symbols, 1):
        db.execute(HISTORY_QUERY, (symbol,))
        rows = db.fetchall()

        bad_ids = []
        new_result_date = None

        for row_id, seq_id, announced_at, subject in rows:
            if "outcome of board meeting" not in subject.lower():
                # Non-OOBM categories already pass through RESULT_KEYWORDS in
                # is_result() — trust them and stop here.
                new_result_date = announced_at.astimezone(IST).date()
                break

            ist_dt = announced_at.astimezone(IST)
            date_str = ist_dt.strftime("%d-%m-%Y")
            if date_str not in day_cache:
                day_cache[date_str] = fetch_nse_day(date_str)
                time.sleep(0.4)
            anns = day_cache[date_str]
            match = next((a for a in anns if str(a.get("seq_id", "")) == str(seq_id)), None)

            if match is None:
                print(
                    f"[{i}/{len(symbols)}] {symbol}: seq_id {seq_id} not found in NSE response on {date_str}, stopping walk here (unresolved)"
                )
                new_result_date = None
                bad_ids = []
                break

            if is_genuine_result(match.get("desc", ""), match.get("attchmntText", "")):
                new_result_date = ist_dt.date()
                break
            bad_ids.append(row_id)

        if bad_ids and new_result_date:
            print(
                f"[{i}/{len(symbols)}] {symbol}: {len(bad_ids)} false-positive row(s) before genuine result_date {new_result_date}"
            )
            fixes[symbol] = (bad_ids, new_result_date)
        elif not bad_ids:
            print(f"[{i}/{len(symbols)}] {symbol}: first row genuine, no fix needed")
        else:
            print(
                f"[{i}/{len(symbols)}] {symbol}: could not resolve a genuine result row, SKIPPING (needs manual review)"
            )

    print(f"\n{len(fixes)} symbols need correction: {list(fixes.keys())}")

    if not args.fix:
        print("\nDry run only — re-run with --fix to apply corrections.")
        db.close()
        return

    old_dates = {}
    for symbol, (bad_ids, new_result_date) in fixes.items():
        db.execute("SELECT DISTINCT result_date FROM presentation_keyword_analysis WHERE symbol = %s", (symbol,))
        old_dates[symbol] = [r[0] for r in db.fetchall()]

    for symbol, (bad_ids, new_result_date) in fixes.items():
        print(f"\nFixing {symbol} -> new result_date {new_result_date} (deleting {len(bad_ids)} bad row(s)) …")
        for row_id in bad_ids:
            db.execute("DELETE FROM pead_announcements WHERE id = %s", (row_id,))
        for old_date in old_dates[symbol]:
            db.execute(
                "DELETE FROM presentation_keyword_analysis WHERE symbol = %s AND result_date = %s", (symbol, old_date)
            )
        db.commit()

    db.close()

    print(f"\nRe-running keyword_analysis.py for {len(fixes)} corrected symbols...\n")
    for symbol in fixes:
        subprocess.run(
            [sys.executable, "keyword_analysis.py", "--symbol", symbol, "--force"],
            cwd="/Users/gurudayal/Desktop/data-syncer/scripts",
        )

    print("\nDone.")


if __name__ == "__main__":
    main()

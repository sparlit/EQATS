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


import os

import pandas as pd
from dotenv import load_dotenv
from supabase import Client, create_client

# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL:
    msg = "SUPABASE_URL is missing from .env"
    raise RuntimeError(msg)

if not SUPABASE_SERVICE_KEY:
    msg = "SUPABASE_SERVICE_KEY is missing from .env"
    raise RuntimeError(msg)


# ============================================================
# SUPABASE CLIENT
# ============================================================

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ============================================================
# REPORT CONFIGURATION
# ============================================================

REPORTS = {
    "all_scores.csv": "all_scores",
    "next_day_candidates.csv": "next_day_candidates",
    "swing_candidates.csv": "swing_candidates",
    "historical_setup_stats.csv": "historical_setup_stats",
    "position_selection.csv": "position_selection",
    "high_priority_overlap.csv": "high_priority_overlap",
}


# ============================================================
# HELPERS
# ============================================================


def clean_value(value):

    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        try:
            return value.item()

        except Exception:
            pass

    return value


def find_symbol(row):

    possible_columns = [
        "SYMBOL",
        "symbol",
        "Symbol",
        "Ticker",
        "ticker",
    ]

    for column in possible_columns:
        if column in row.index:
            value = row[column]

            if pd.notna(value):
                return str(value)

    return ""


# ============================================================
# TEST SUPABASE CONNECTION
# ============================================================


def test_connection():

    print()
    print("=" * 70)
    print("TESTING SUPABASE CONNECTION")
    print("=" * 70)

    try:
        (supabase.table("all_scores").select("id").limit(1).execute())

        print("Supabase connection : OK")
        print("SELECT permission   : OK")
        print()

        return True

    except Exception as exc:
        print("Supabase connection failed:")
        print(exc)

        return False


# ============================================================
# TEST INSERT
# ============================================================


def test_insert():

    print("=" * 70)
    print("TESTING API INSERT")
    print("=" * 70)

    test_data = {"scan_date": "2026-08-27", "symbol": "__PYTHON_TEST__", "data": {"test": True}}

    try:
        result = supabase.table("all_scores").insert(test_data).execute()

        print("API INSERT : OK")
        print(result)

        # Clean test row
        (supabase.table("all_scores").delete().eq("symbol", "__PYTHON_TEST__").execute())

        print("Test row removed.")

        return True

    except Exception as exc:
        print()
        print("API INSERT FAILED")
        print(exc)
        print()

        return False


# ============================================================
# UPLOAD REPORT
# ============================================================


def upload_report(filename, table_name):

    path = os.path.join("output", filename)

    print()
    print("=" * 70)
    print(f"REPORT : {filename}")
    print(f"TABLE  : {table_name}")
    print("=" * 70)

    if not os.path.isfile(path):
        print(f"FILE NOT FOUND: {path}")
        return False

    try:
        df = pd.read_csv(path)

    except Exception as exc:
        print("CSV READ ERROR:")
        print(exc)

        return False

    print(f"Rows found: {len(df)}")

    if df.empty:
        print("CSV contains no data.")
        return True

    records = []

    # --------------------------------------------------------
    # IMPORTANT:
    # Use the report's actual scan date when available.
    # Otherwise use today's date.
    # --------------------------------------------------------

    scan_date = pd.Timestamp.today().strftime("%Y-%m-%d")

    for _, row in df.iterrows():
        data = {}

        for column in df.columns:
            data[str(column)] = clean_value(row[column])

        records.append(
            {
                "scan_date": scan_date,
                "symbol": find_symbol(row),
                "data": data,
            }
        )

    # --------------------------------------------------------
    # Upload in batches
    # --------------------------------------------------------

    batch_size = 250

    total = len(records)

    for start in range(0, total, batch_size):
        batch = records[start : start + batch_size]

        try:
            (supabase.table(table_name).insert(batch).execute())

        except Exception as exc:
            print()
            print(f"INSERT ERROR at rows {start + 1}-{min(start + batch_size, total)}")

            print(exc)

            return False

        end = min(start + batch_size, total)

        print(f"Uploaded {end}/{total}")

    print("Completed successfully.")

    return True


# ============================================================
# MAIN
# ============================================================


def main():

    print()
    print("=" * 70)
    print("NSE REPORT → SUPABASE")
    print("=" * 70)

    # --------------------------------------------------------
    # Connection test
    # --------------------------------------------------------

    if not test_connection():
        return

    # --------------------------------------------------------
    # API INSERT test
    # --------------------------------------------------------

    if not test_insert():
        print()
        print("=" * 70)
        print("STOPPING")
        print("=" * 70)
        print()
        print("Supabase SELECT works but API INSERT is still being rejected.")

        return

    # --------------------------------------------------------
    # Upload six reports
    # --------------------------------------------------------

    success = 0
    failed = 0

    for filename, table_name in REPORTS.items():
        if upload_report(filename, table_name):
            success += 1

        else:
            failed += 1

    # --------------------------------------------------------
    # Final summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("UPLOAD SUMMARY")
    print("=" * 70)

    print(f"Successful reports : {success}")
    print(f"Failed reports     : {failed}")

    print("=" * 70)


if __name__ == "__main__":
    main()

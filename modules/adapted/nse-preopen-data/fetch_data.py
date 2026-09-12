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


import csv
import datetime
import glob
import json
import os
import re
import sys
import time
import traceback

import requests

# Define both URLs
URLS = [
    "https://www.nseindia.com/api/market-data-pre-open?key=NIFTY",
    "https://www.nseindia.com/api/market-data-pre-open?key=FO",
]

HOME_URL = "https://www.nseindia.com/report-detail/fo_eq_security"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/report-detail/fo_eq_security",
}


def check_file_exists_for_today(url):
    """
    Check if a file for today's date already exists for the given URL
    Returns: (exists, filename_if_exists)
    """
    # Extract key from URL
    key_match = re.search(r"key=([^&]+)", url)
    key = key_match.group(1) if key_match else "UNKNOWN"

    today = datetime.date.today()
    date_str = today.strftime("%d-%b-%Y").upper()
    base_filename = f"pre-open-{key}-{date_str}.csv"

    # Check for base filename and any numbered versions
    pattern = f"data/{base_filename.replace('.csv', '')}*.csv"
    existing_files = glob.glob(pattern)

    if existing_files:
        return True, existing_files[0]  # Return the first existing file
    return False, None


def should_download_url(url):
    """
    Determine if we should download data for this URL
    Returns: (should_download, reason)
    """
    exists, filename = check_file_exists_for_today(url)

    if exists:
        # Check if it's from today (based on file modification time or content)
        try:
            # Read the file to check the date in LAST_UPDATE
            with open(filename, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "LAST_UPDATE" in row:
                        last_update = row["LAST_UPDATE"]
                        if last_update:
                            # Check if the date in the file is from today
                            date_part = last_update.split(" ")[0]
                            try:
                                file_date = datetime.datetime.strptime(date_part, "%d-%b-%Y").date()
                                today = datetime.date.today()
                                if file_date == today:
                                    print(f"✅ File {filename} already has today's data ({last_update})")
                                    return False, "Today's data already exists"
                                print(f"⚠️ File {filename} exists but has data from {file_date}, not today")
                                return True, "File exists but has old data"
                            except:
                                print(f"⚠️ Could not parse date from {last_update}, will re-download")
                                return True, "Could not verify date"
        except Exception as e:
            print(f"⚠️ Could not read existing file: {e}, will re-download")
            return True, "Could not read existing file"
    else:
        print(f"📊 No existing file found for {url.split('key=')[1]} today")
        return True, "No existing file"

    return True, "Default to download"


def get_filename_from_data(json_data, url):
    """
    Get filename based on LAST_UPDATE from the data
    URL: https://www.nseindia.com/api/market-data-pre-open?key=NIFTY
    Returns: pre-open-NIFTY-DD-MMM-YYYY.csv
    """
    # Extract key from URL
    key_match = re.search(r"key=([^&]+)", url)
    key = key_match.group(1) if key_match else "UNKNOWN"

    # Try to get date from the data
    data_list = json_data.get("data", [])
    date_str = None

    # Look for LAST_UPDATE in the data
    for item in data_list:
        detail = item.get("detail", {})
        preopen = detail.get("preOpenMarket", {})
        last_update = preopen.get("lastUpdateTime", "")

        if last_update:
            # Parse the date from LAST_UPDATE
            try:
                # LAST_UPDATE format: "DD-MMM-YYYY HH:MM:SS" or similar
                # Example: "01-JUL-2026 09:15:00"
                date_part = last_update.split(" ")[0]  # Get the date part
                # Try to parse it
                parsed_date = datetime.datetime.strptime(date_part, "%d-%b-%Y")
                date_str = parsed_date.strftime("%d-%b-%Y").upper()
                break
            except:
                # If parsing fails, try alternative format
                try:
                    # Try with different format
                    parsed_date = datetime.datetime.strptime(last_update, "%d-%b-%Y %H:%M:%S")
                    date_str = parsed_date.strftime("%d-%b-%Y").upper()
                    break
                except:
                    continue

    # If no valid date found in data, use today's date
    if not date_str:
        today = datetime.date.today()
        date_str = today.strftime("%d-%b-%Y").upper()
        print(f"⚠️ No LAST_UPDATE found in data, using today's date: {date_str}")
    else:
        print(f"📅 Using date from data: {date_str}")

    return f"pre-open-{key}-{date_str}.csv"


def get_next_filename(base_name):
    """
    Get the next available filename with number suffix.
    Example: if base_name.csv exists, returns base_name (1).csv
    """
    # Create data folder if it doesn't exist
    os.makedirs("data", exist_ok=True)

    # First, check if the base file exists
    base_file = f"data/{base_name}"
    if not os.path.exists(base_file):
        return base_file

    # If it exists, find the next number
    base_without_ext = os.path.splitext(base_name)[0]
    ext = os.path.splitext(base_name)[1]
    pattern = f"data/{base_without_ext} (*){ext}"
    existing_files = glob.glob(pattern)

    # Extract numbers from existing files
    numbers = []
    for f in existing_files:
        # Extract number between ( and )
        try:
            num = int(f.split("(")[1].split(")")[0])
            numbers.append(num)
        except:
            continue

    # Find the next number
    next_num = max(numbers) + 1 if numbers else 1

    return f"data/{base_without_ext} ({next_num}){ext}"


def fetch_json_data(url):
    """Fetch JSON data from NSE API for a specific URL"""
    print(f"🔍 Fetching data from: {url}")

    session = requests.Session()
    session.headers.update(HEADERS)

    # First visit homepage to get cookies
    try:
        home_response = session.get(HOME_URL, timeout=10)
        print(f"   Homepage status: {home_response.status_code}")
    except Exception as e:
        print(f"❌ Homepage error: {e}")
        raise

    # Fetch API data
    print(f"📊 Fetching pre-open data for {url.split('key=')[1]}...")
    try:
        response = session.get(url, timeout=10)
        print(f"   Response status: {response.status_code}")
        response.raise_for_status()
    except Exception as e:
        print(f"❌ API error: {e}")
        print(f"   Response: {response.text[:200] if 'response' in locals() else 'No response'}")
        raise

    print("✅ Data fetched successfully")
    return response.json()


def parse_and_save(json_data, url):
    """Parse JSON and save as CSV with filename from data's LAST_UPDATE field"""
    print("🔍 Debug: Starting parse_and_save...")

    # Create data folder if it doesn't exist
    os.makedirs("data", exist_ok=True)

    # Get the filename based on data's LAST_UPDATE
    url_filename = get_filename_from_data(json_data, url)
    print(f"📁 Filename from data: {url_filename}")

    # Check if this exact file already exists (without number suffix)
    base_file = f"data/{url_filename}"
    if os.path.exists(base_file):
        # Check if the existing file has today's data
        try:
            with open(base_file, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "LAST_UPDATE" in row:
                        last_update = row["LAST_UPDATE"]
                        if last_update:
                            date_part = last_update.split(" ")[0]
                            try:
                                file_date = datetime.datetime.strptime(date_part, "%d-%b-%Y").date()
                                today = datetime.date.today()
                                if file_date == today:
                                    print(f"⏭️ File {base_file} already has today's data, skipping...")
                                    return []  # Return empty list to indicate no new data
                            except:
                                pass
        except Exception as e:
            print(f"⚠️ Could not check existing file: {e}")

    # Get the next available filename (handles duplicates)
    filename = get_next_filename(url_filename)
    print(f"📁 Saving to: {filename}")

    records = []
    data_list = json_data.get("data", [])
    print(f"📊 Found {len(data_list)} items in data")

    if not data_list:
        print("⚠️ No data received from API")
        return []

    # Store the date from first record for verification
    first_date = None

    for item in data_list:
        metadata = item.get("metadata", {})
        detail = item.get("detail", {})
        preopen = detail.get("preOpenMarket", {})

        # Extract IEP price from order book
        preopen_list = preopen.get("preopen", [])
        iep_price = None
        for entry in preopen_list:
            if entry.get("iep"):
                iep_price = entry.get("price")
                break

        if iep_price is None and preopen_list:
            iep_price = preopen_list[0].get("price")

        buy_qty = preopen.get("totalBuyQuantity", 0)
        sell_qty = preopen.get("totalSellQuantity", 0)

        # Determine ADV/DECL
        if buy_qty > sell_qty:
            adv_decl = "BUY"
        elif buy_qty < sell_qty:
            adv_decl = "SELL"
        else:
            adv_decl = "NEUTRAL"

        last_update = preopen.get("lastUpdateTime", "")

        # Store the first valid date for verification
        if last_update and not first_date:
            first_date = last_update

        record = {
            "SYMBOL": metadata.get("symbol", ""),
            "PREOPEN": iep_price,
            "FINAL_PRICE": preopen.get("finalPrice", ""),
            "FINAL_QUANTITY": preopen.get("finalQuantity", ""),
            "LAST_UPDATE": last_update,
            "TOTAL_BUY_QTY": buy_qty,
            "TOTAL_SELL_QTY": sell_qty,
            "ADV_DECL": adv_decl,
        }
        records.append(record)

    # Write to CSV
    try:
        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = [
                "SYMBOL",
                "PREOPEN",
                "FINAL_PRICE",
                "FINAL_QUANTITY",
                "LAST_UPDATE",
                "TOTAL_BUY_QTY",
                "TOTAL_SELL_QTY",
                "ADV_DECL",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

        # Verify file was created
        if os.path.exists(filename):
            file_size = os.path.getsize(filename)
            print(f"✅ File created: {filename} ({file_size} bytes)")
            if first_date:
                print(f"📅 Data date from LAST_UPDATE: {first_date}")
        else:
            print(f"❌ File NOT created at {filename}")
            return []

    except Exception as e:
        print(f"❌ Error saving file: {e}")
        raise

    print(f"✅ Saved: {filename}")
    print(f"📊 Records: {len(records)}")
    return records


def download_all():
    """Download data for all URLs"""
    print("=" * 60)
    print("🚀 Starting NSE data fetch for multiple URLs...")
    print(f"📅 Current time: {datetime.datetime.now()}")
    print(f"📁 Current directory: {os.getcwd()}")
    print("=" * 60)

    all_results = []
    total_records = 0
    skipped_urls = []

    for i, url in enumerate(URLS, 1):
        print(f"\n{'=' * 60}")
        print(f"📌 Processing URL {i}/{len(URLS)}: {url}")
        print("=" * 60)

        # Check if we should download this URL
        should_download, reason = should_download_url(url)

        if not should_download:
            print(f"⏭️ Skipping {url.split('key=')[1]}: {reason}")
            skipped_urls.append(url.split("key=")[1])
            all_results.append(
                {
                    "url": url,
                    "key": url.split("key=")[1],
                    "records": 0,
                    "success": True,
                    "skipped": True,
                    "reason": reason,
                }
            )
            continue

        try:
            # Add a small delay between requests to avoid rate limiting
            if i > 1:
                print("⏳ Waiting 2 seconds before next request...")
                time.sleep(2)

            # Fetch data
            json_data = fetch_json_data(url)

            # Parse and save
            records = parse_and_save(json_data, url)

            if records:
                total_records += len(records)
                all_results.append(
                    {
                        "url": url,
                        "key": url.split("key=")[1],
                        "records": len(records),
                        "success": True,
                        "skipped": False,
                    }
                )
                print(f"✅ Successfully processed {url.split('key=')[1]}")
            else:
                # Check if we skipped because data already exists
                all_results.append(
                    {
                        "url": url,
                        "key": url.split("key=")[1],
                        "records": 0,
                        "success": True,
                        "skipped": True,
                        "reason": "Data already exists for today",
                    }
                )
                print(f"⏭️ Skipped {url.split('key=')[1]}: Data already exists for today")

        except Exception as e:
            print(f"\n❌ ERROR processing {url}: {e}")
            print("\n📋 Full traceback:")
            traceback.print_exc()
            all_results.append(
                {
                    "url": url,
                    "key": url.split("key=")[1],
                    "records": 0,
                    "success": False,
                    "skipped": False,
                    "error": str(e),
                }
            )

    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY REPORT")
    print("=" * 60)

    downloaded = [r for r in all_results if r["success"] and not r.get("skipped", False)]
    skipped = [r for r in all_results if r.get("skipped", False)]
    failed = [r for r in all_results if not r["success"]]

    print(f"✅ Downloaded: {len(downloaded)}")
    print(f"⏭️ Skipped (already exists): {len(skipped)}")
    print(f"❌ Failed: {len(failed)}")
    print(f"📊 Total new records saved: {total_records}")

    if skipped:
        print("\n⏭️ Skipped URLs:")
        for result in skipped:
            print(f"   - {result['key']}: {result.get('reason', 'Already exists')}")

    if failed:
        print("\n❌ Failed URLs:")
        for result in failed:
            error_msg = result.get("error", "Unknown error")
            print(f"   - {result['url']} ({error_msg})")

    print("=" * 60)
    return all_results


if __name__ == "__main__":
    try:
        download_all()
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        print("\n📋 Full traceback:")
        traceback.print_exc()

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
import datetime
import os
import sys
import time
import traceback
import zipfile

import requests

# Configuration
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
TIMEOUT = 60  # seconds for download requests


def safe_print(*args, **kwargs):
    """Thread-safe print function with timestamp"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}]", *args, **kwargs)
    sys.stdout.flush()  # Force flush to ensure output is written immediately


def log_exception(prefix="EXCEPTION"):
    """Log the full exception traceback with prefix"""
    print(f"\n[{prefix}] {'=' * 60}")
    traceback.print_exc(file=sys.stdout)
    print(f"[{prefix}] {'=' * 60}\n")
    sys.stdout.flush()


def download_and_extract(url, extract_dir=".", retry_count=0):
    """
    Download a zip file from URL and extract it to the specified directory
    with improved error handling and retries
    """
    try:
        # Get filename from URL
        filename = url.split("/")[-1]
        safe_print(f"Downloading {filename}...")

        # Download the file with timeout
        try:
            response = requests.get(url, stream=True, timeout=TIMEOUT)
            response.raise_for_status()  # Raise exception for HTTP errors
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            if retry_count < MAX_RETRIES:
                retry_count += 1
                safe_print(f"Download error: {e}")
                safe_print(f"Retrying ({retry_count}/{MAX_RETRIES}) after {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
                return download_and_extract(url, extract_dir, retry_count)
            safe_print(f"Error downloading file after {MAX_RETRIES} attempts: {e}")
            return False

        file_size = int(response.headers.get("content-length", 0))
        safe_print(f"File size: {file_size / 1024 / 1024:.2f} MB")

        # Save the zip file with progress reporting
        downloaded = 0
        last_report = 0
        start_time = time.time()

        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Report progress every 10% or 5 seconds
                    current_time = time.time()
                    progress = int((downloaded / file_size) * 100) if file_size > 0 else 0
                    if (progress >= last_report + 10) or (current_time - start_time >= 5 and progress > last_report):
                        safe_print(
                            f"Download progress: {progress}% ({downloaded / 1024 / 1024:.2f} MB / {file_size / 1024 / 1024:.2f} MB)"
                        )
                        last_report = progress
                        start_time = current_time

        if file_size > 0 and downloaded < file_size:
            safe_print(f"Warning: Downloaded only {downloaded} bytes of {file_size} bytes")
            if retry_count < MAX_RETRIES:
                retry_count += 1
                safe_print(f"Retrying ({retry_count}/{MAX_RETRIES}) after {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
                # Clean up partial download
                if os.path.exists(filename):
                    os.remove(filename)
                return download_and_extract(url, extract_dir, retry_count)

        safe_print(f"Downloaded {downloaded / 1024 / 1024:.2f} MB successfully")

        # Verify the zip file integrity
        try:
            with zipfile.ZipFile(filename, "r") as test_zip:
                # Test the zip file integrity
                test_result = test_zip.testzip()
                if test_result is not None:
                    safe_print(f"Error: Corrupt zip file - first bad file: {test_result}")
                    if retry_count < MAX_RETRIES:
                        retry_count += 1
                        safe_print(f"Retrying ({retry_count}/{MAX_RETRIES}) after {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                        # Clean up corrupt file
                        if os.path.exists(filename):
                            os.remove(filename)
                        return download_and_extract(url, extract_dir, retry_count)
                    return False
        except zipfile.BadZipFile:
            safe_print(f"Error: {filename} is not a valid zip file")
            if retry_count < MAX_RETRIES:
                retry_count += 1
                safe_print(f"Retrying ({retry_count}/{MAX_RETRIES}) after {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
                # Clean up corrupt file
                if os.path.exists(filename):
                    os.remove(filename)
                return download_and_extract(url, extract_dir, retry_count)
            return False

        # Extract the zip file
        safe_print(f"Extracting {filename}...")
        with zipfile.ZipFile(filename, "r") as zip_ref:
            # Show files in the zip
            safe_print("Files in the zip archive:")
            for i, file_info in enumerate(zip_ref.infolist()):
                safe_print(f"  {i + 1}. {file_info.filename} ({file_info.file_size / 1024:.2f} KB)")

            # Extract all files
            zip_ref.extractall(extract_dir)

        # Get the extracted filename (should be the same as zip but without .zip)
        expected_file = filename.replace(".zip", "")
        actual_files = []

        for file_info in zipfile.ZipFile(filename).infolist():
            extracted_path = os.path.join(extract_dir, file_info.filename)
            if os.path.exists(extracted_path):
                actual_files.append(file_info.filename)
                safe_print(f"Extracted file: {file_info.filename} ({os.path.getsize(extracted_path) / 1024:.2f} KB)")

        if not actual_files:
            safe_print(f"Warning: No files were extracted from {filename}")
            if retry_count < MAX_RETRIES:
                retry_count += 1
                safe_print(f"Retrying ({retry_count}/{MAX_RETRIES}) after {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
                # Clean up
                if os.path.exists(filename):
                    os.remove(filename)
                return download_and_extract(url, extract_dir, retry_count)
            return False

        # Check if expected file exists
        if expected_file not in actual_files and not os.path.exists(os.path.join(extract_dir, expected_file)):
            safe_print(f"Note: Expected file {expected_file} not found in extracted files.")
            safe_print(f"Using extracted files: {', '.join(actual_files)}")

            # Rename main file if needed
            if len(actual_files) == 1 and expected_file.endswith("_symbols.txt"):
                main_file = os.path.join(extract_dir, actual_files[0])
                target_file = os.path.join(extract_dir, expected_file)
                safe_print(f"Renaming {actual_files[0]} to {expected_file}")
                try:
                    os.rename(main_file, target_file)
                    safe_print(f"Successfully renamed to {expected_file}")
                except Exception as e:
                    safe_print(f"Error renaming file: {e}")

        # Clean up - remove the zip file
        try:
            os.remove(filename)
            safe_print(f"Cleaned up {filename}")
        except Exception as e:
            safe_print(f"Warning: Could not remove zip file: {e}")

        # Verify the file content
        expected_path = os.path.join(extract_dir, expected_file)
        if os.path.exists(expected_path):
            file_size = os.path.getsize(expected_path)
            safe_print(f"Extracted {expected_file} successfully: {file_size / 1024:.2f} KB")

            # Read the first few lines to verify it's a CSV
            try:
                with open(expected_path, errors="replace") as f:
                    header = f.readline().strip()
                    safe_print(f"File header: {header}")
                    if not header or not ("," in header or "\t" in header):
                        safe_print("Warning: File doesn't appear to be valid CSV/TSV format")
                        # Show file encoding and first few lines
                        with open(expected_path, "rb") as fb:
                            firstbytes = fb.read(100)
                            safe_print(f"First 100 bytes: {firstbytes}")
            except Exception as e:
                safe_print(f"Warning: Could not read file: {e}")

        return True

    except Exception as e:
        safe_print(f"An unexpected error occurred: {e}")
        log_exception("DOWNLOAD")

        if retry_count < MAX_RETRIES:
            retry_count += 1
            safe_print(f"Retrying ({retry_count}/{MAX_RETRIES}) after {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
            return download_and_extract(url, extract_dir, retry_count)

        return False


def main():
    # URLs for NSE and BSE symbol files
    nse_url = "https://api.shoonya.com/NSE_symbols.txt.zip"
    bse_url = "https://api.shoonya.com/BSE_symbols.txt.zip"

    # Create log directory if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Log file path with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"symbol_download_{timestamp}.log")

    # Redirect output to log file
    original_stdout = sys.stdout
    try:
        with open(log_file, "w") as f:
            sys.stdout = f

            safe_print("Starting symbol file download...")
            safe_print(f"Python version: {sys.version}")
            safe_print(f"Current directory: {os.getcwd()}")

            # Check if files already exist
            need_nse = not os.path.exists("NSE_symbols.txt")
            need_bse = not os.path.exists("BSE_symbols.txt")

            if not need_nse and not need_bse:
                safe_print("Both NSE and BSE symbol files already exist. Use --force to redownload.")
                return 0

            # Download and extract both files
            results = []

            if need_nse:
                safe_print("\n" + "=" * 50)
                safe_print("Downloading NSE symbols file")
                safe_print("=" * 50)
                nse_success = download_and_extract(nse_url)
                results.append(("NSE", nse_success))
            else:
                safe_print("NSE symbols file already exists, skipping.")
                results.append(("NSE", True))

            if need_bse:
                safe_print("\n" + "=" * 50)
                safe_print("Downloading BSE symbols file")
                safe_print("=" * 50)
                bse_success = download_and_extract(bse_url)
                results.append(("BSE", bse_success))
            else:
                safe_print("BSE symbols file already exists, skipping.")
                results.append(("BSE", True))

            # Final summary
            safe_print("\n" + "=" * 50)
            safe_print("DOWNLOAD SUMMARY")
            safe_print("=" * 50)

            all_success = True
            for exchange, success in results:
                safe_print(f"{exchange}: {'SUCCESS' if success else 'FAILED'}")
                all_success = all_success and success

                # Verify file exists and has content
                filename = f"{exchange}_symbols.txt"
                if os.path.exists(filename):
                    size = os.path.getsize(filename)
                    safe_print(f"  - File size: {size / 1024:.2f} KB")

                    # Count lines
                    try:
                        with open(filename, errors="replace") as f:
                            line_count = sum(1 for _ in f)
                        safe_print(f"  - Line count: {line_count}")
                    except Exception as e:
                        safe_print(f"  - Error counting lines: {e}")
                else:
                    safe_print("  - File does not exist!")
                    all_success = False

            if all_success:
                safe_print("\nSuccessfully downloaded and verified all required symbol files.")
                return 0
            safe_print("\nFailed to download or verify one or more symbol files.")
            return 1

    except Exception as e:
        # Make sure we restore stdout before printing
        sys.stdout = original_stdout
        print(f"Critical error: {e}")
        traceback.print_exc()
        return 1
    finally:
        # Restore stdout
        sys.stdout = original_stdout
        print(f"Symbol download completed. Log saved to {log_file}")

        # Copy important messages to console
        try:
            with open(log_file) as f:
                last_lines = f.readlines()[-10:]  # Last 10 lines
                print("\nLast few log entries:")
                for line in last_lines:
                    print(line.strip())
        except:
            pass


if __name__ == "__main__":
    # Check for force flag
    if "--force" in sys.argv:
        print("Force flag detected. Will redownload files even if they exist.")
        # Remove existing files
        for file in ["NSE_symbols.txt", "BSE_symbols.txt"]:
            if os.path.exists(file):
                print(f"Removing existing file: {file}")
                os.remove(file)

    sys.exit(main())

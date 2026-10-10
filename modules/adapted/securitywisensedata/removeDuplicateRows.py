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

# Folder containing your CSV files
FOLDER_PATH = "SecurityWiseData"  # change this if needed


def clean_csv_files(folder_path):
    for filename in os.listdir(folder_path):
        if filename.endswith(".csv"):
            file_path = os.path.join(folder_path, filename)
            try:
                # Read CSV
                df = pd.read_csv(file_path)

                # Drop duplicate rows
                df = df.drop_duplicates()

                # Save back (overwrite same file)
                df.to_csv(file_path, index=False)

                print(f"Cleaned: {filename} (removed duplicates)")
            except Exception as e:
                print(f"Error processing {filename}: {e}")


if __name__ == "__main__":
    clean_csv_files(FOLDER_PATH)

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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd

FOLDER = "SecurityWiseData"


def process_file(file):
    try:
        filepath = os.path.join(FOLDER, file)
        df = pd.read_csv(filepath)
        # Convert DATE1 column to datetime
        df["DATE1"] = pd.to_datetime(df["DATE1"], format="%d-%m-%Y")
        # Sort by DATE1
        df_sorted = df.sort_values(by="DATE1")
        df_sorted.to_csv(filepath, index=False)
        print(f"Processed: {file}")

    except Exception as e:
        print(f"Error processing {file}: {e}")


def main():
    files = [f for f in os.listdir(FOLDER) if f.endswith(".csv")]

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        executor.map(process_file, files)


if __name__ == "__main__":
    main()

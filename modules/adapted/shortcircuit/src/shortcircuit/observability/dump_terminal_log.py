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
from datetime import datetime

LOG_FILE = "logs/bot.log"
DATE_STR = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = f"logs/{DATE_STR}_session.log"


def update_log():
    if not os.path.exists(LOG_FILE):
        print(f"Log file not found: {LOG_FILE}")
        return

    print(f"Reading log file: {LOG_FILE}")
    matching_lines = []

    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(DATE_STR):
                    matching_lines.append(line.rstrip())

        print(f"Found {len(matching_lines)} lines for {DATE_STR}")

        # Ensure output directory exists (if path has dirs)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            if matching_lines:
                for line in matching_lines:
                    f.write(line + "\n")
            else:
                f.write(f"# No log entries found for {DATE_STR} in {LOG_FILE}.\n")

        print(f"Successfully updated {OUTPUT_FILE}")

    except Exception as e:
        print(f"Error updating log: {e}")


if __name__ == "__main__":
    update_log()

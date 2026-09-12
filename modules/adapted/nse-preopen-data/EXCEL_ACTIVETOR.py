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
import re
import subprocess


def rearm_office():
    office_path = r"C:\Program Files\Microsoft Office\Office16"

    if not os.path.exists(office_path):
        print(f"Office not found at {office_path}")
        return

    os.chdir(office_path)

    # Check status
    print("Checking Office status...")
    result = subprocess.run("cscript ospp.vbs /dstatus", shell=True, capture_output=True, text=True)
    print(result.stdout)

    # Extract SKU ID
    sku_match = re.search(r"SKU ID:\s*([a-f0-9-]+)", result.stdout, re.IGNORECASE)

    print("\n" + "=" * 50)

    if sku_match:
        sku_id = sku_match.group(1)
        print(f"🔑 SKU ID Found: {sku_id}")
        print(f"📋 Command: ospprearm {sku_id}")
        print("\n" + "=" * 50)

        # Rearm with SKU ID
        print(f"Rearming Office with SKU: {sku_id}...")
        subprocess.run(f"ospprearm {sku_id}", shell=True)
    else:
        print("⚠️  No SKU ID found, rearming all...")
        subprocess.run("ospprearm", shell=True)

    print("\n" + "=" * 50)
    print("Office rearm completed!")


if __name__ == "__main__":
    rearm_office()
    input("Press Enter to exit...")

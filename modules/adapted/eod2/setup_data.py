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


import sys
from pathlib import Path
from shutil import copyfileobj
from urllib.request import urlopen
from zipfile import ZipFile

# ################################
# This script is written for non git users,
# who may download this repository as a zip file.
# The zip file does not install the submodule eod2_data.
#
# This script will download the eod2_data as a zip and
# extract the contents into eod2_data folder.
# ################################

DIR = Path(__file__).parent
url = "https://github.com/BennyThadikaran/eod2_data/archive/main.zip"
ZIP_FILE = DIR / "eod2_data.zip"
FOLDER = DIR / "src" / "eod2_data"
DAILY_FOLDER = FOLDER / "daily"

if not FOLDER.exists():
    FOLDER.mkdir()
elif any(FOLDER.iterdir()):
    # check if the folder has any files in it
    print("eod2_data folder has data. Renaming folder to eod2_data_backup.")

    # Rename the folder to protect files from being overwritten.
    FOLDER.rename("eod2_data_backup")

chunk_size = 15 * 1024 * 1024  # 15 MB

with urlopen(url, timeout=30) as response, ZIP_FILE.open("wb") as f:
    while True:
        chunk = response.read(chunk_size)
        if not chunk:
            break
        f.write(chunk)

if not ZIP_FILE.is_file():
    sys.exit("download failed")

print("Download success.")
# create the eod2_data and daily folder if not exists
if not FOLDER.exists():
    FOLDER.mkdir()

if not DAILY_FOLDER.exists():
    DAILY_FOLDER.mkdir()

print("Extracting Zipfile to eod2_data")

with ZipFile(ZIP_FILE) as zip:
    for filePath in zip.namelist():
        # zip file comes in eod2_data-main,
        # we dont need the folder so remove it from filepath
        outPath = FOLDER / filePath.replace("eod2_data-main/", "")

        if outPath.is_dir():
            continue

        with zip.open(filePath) as src, outPath.open("wb") as dst:
            # copy file from src to dst without extracting them to disk
            copyfileobj(src, dst)

ZIP_FILE.unlink()
print("Done")

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


import shutil
from urllib.request import Request, urlopen

link = "https://www1.nseindia.com/content/historical/EQUITIES/2017/NOV/cm03NOV2017bhav.csv.zip"
link = "https://www1.nseindia.com/content/historical/EQUITIES/2021/JAN/cm01JAN2021bhav.csv.zip"
link = "https://www1.nseindia.com/content/historical/DERIVATIVES/2021/JAN/fo01JAN2021bhav.csv.zip"
header = {
    "Accept-Encoding": "gzip, deflate, sdch, br",
    "Accept-Language": "fr-FR,fr;q=0.8,en-US;q=0.6,en;q=0.4",
    "Host": "www1.nseindia.com",
    "Referer": "https://www1.nseindia.com/",
    "User-Agent": "Mozilla/5.0 (X11; Linux i686) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/53.0.2785.143 Chrome/53.0.2785.143 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def download_file(link, file_name, length):
    try:
        req = Request(link, headers=header)
        with open(file_name, "wb") as writer:
            request = urlopen(req, timeout=3)
            shutil.copyfileobj(request, writer, length)
    except Exception as e:
        print("File cannot be downloaded:", e)
    finally:
        print("File downloaded with success!")


file_name = "fo_file.zip"
length = 1024
download_file(link, file_name, length)

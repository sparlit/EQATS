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
import os

import requests
from bs4 import BeautifulSoup

file_headers_1 = ["key-ratio", "balance-sheet", "profit-loss", "cashflow", "quarterly", "half"]
file_headers_2 = ["consolidated", "standalone"]

filenames = []

for i in file_headers_1:
    for j in file_headers_2:
        filenames.append(i + "(" + j + ")" + ".csv")

FILE = "company_urls.txt"  # Path of the text file containing the extracted URLs

with open(FILE) as f:
    data = f.read()
    urls = data.split("\n")

for url in urls:
    temp = url.split("/")
    company = temp[4]
    temp.insert(5, "ratio")
    url = "/".join(temp)
    if not os.path.exists(company):
        os.makedirs(company)
    os.chdir(company)

    resp = requests.get(url)
    soup = BeautifulSoup(resp.content, "html5lib")
    tables = soup.findAll("table")
    sub_counter = 0
    counter = 0
    for table in tables:
        if counter % 2 == 0:
            if sub_counter == 12:
                break
            headers = [th.text for th in table.select("tr th")]
            with open(filenames[sub_counter], "w") as f:
                wr = csv.writer(f)
                wr.writerow(headers)
                wr.writerows([[td.text for td in row.find_all("td")] for row in table.select("tr + tr")])
            sub_counter += 1
        counter += 1
    print("Done")
    os.chdir("..")

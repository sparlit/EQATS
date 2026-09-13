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


from concurrent import futures
from datetime import datetime
from itertools import count

import utilities
from models import Script
from mongoengine import connect


def get_company_info(tag, count):
    try:
        if tag["href"] == "":
            return
        soup = utilities.get_soup(tag["href"])
        code = soup.find("input", {"id": "ap_sc_id"})["value"].lower()
        Script.objects(code=code).update_one(set__url=tag["href"], upsert=True)
        print(count, ".\t" + code)
    except Exception as e:
        print(type(e).__name__)
        print(e)
        print(count, ".\t" + tag)
        return


if __name__ == "__main__":
    try:
        connect("stock_exchange")
        soup = utilities.get_soup("https://www.moneycontrol.com/india/stockpricequote")
        alphabet_list = soup.find("div", {"class": "MT2 PA10 brdb4px alph_pagn"})
        alphabet_links = alphabet_list.find_all("a")
        companies = []
        for link in alphabet_links[1:]:
            soup = utilities.get_soup("https://www.moneycontrol.com" + link["href"])
            companies_table = soup.find("table", {"class": "pcq_tbl MT10"})
            print(link["href"])
            companies.extend(companies_table.find_all("a"))

        # j=0
        # for i in companies:
        # 	get_company_info(i, j)
        # 	j +=1
        executor = futures.ThreadPoolExecutor()
        results = executor.map(get_company_info, companies, count())
    except Exception as e:
        print(type(e).__name__)
        print(e)

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


import time

from selenium import webdriver
from selenium.webdriver.common.keys import Keys

PATH = ""  # Path to the driver's executable

driver = webdriver.PhantomJS(PATH)

search_id = "Menu_ctrlAutoCompleteExtender1_TxtAutoComplete"


xpath = "/html/body/ul/li[1]/a/div"

URL = "http://www.religareonline.com/"


with open("ind_nifty500list.csv") as f:
    data = f.read()

companies = data.split("\n")
urls = []

with open("company_urls.txt", "a") as f:
    for company in companies:
        try:
            driver.get(URL)
            driver.find_element_by_id(search_id).clear()
            input_s = driver.find_element_by_id(search_id)
            input_s.send_keys(company)
            time.sleep(1)
            driver.find_element_by_xpath(xpath).click()
            f.write(driver.current_url + "\n")
            print("done")
        except:
            continue

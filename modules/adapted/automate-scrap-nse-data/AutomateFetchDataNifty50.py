
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
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
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pickle
import bs4 as bs
import requests

def nifty50_list():
    resp = requests.get('https://en.wikipedia.org/wiki/NIFTY_50')
    soup = bs.BeautifulSoup(resp.text, 'lxml')
    table = soup.find('table', {'class': 'wikitable sortable'},'tbody')
##    print table
    tickers = []
    for row in table.findAll('tr')[1:]:
##        print row
        ticker = row.findAll('td')[1].text
        print ticker
        tickers.append(ticker)
        
    with open("nifty50_list.pickle","wb") as f:
        pickle.dump(tickers,f)
        
    return tickers

nifty50_list()



# create a new Chrome session
driver = webdriver.Chrome()
##driver.implicitly_wait(30)
driver.maximize_window()

#Navigate to NSE's(National stock exchange) archive page where historical data of any stock can be downloaded in archive format
driver.get("https://www.nseindia.com/products/content/equities/equities/eq_security.htm")

#Selecting 12 month daterange to fetch the data


with open("nifty50_list.pickle","rb") as f:
            tickers = pickle.load(f)


for ticker in tickers[20:]:
     driver.execute_script("$('#dateRange').val('12month')")
     WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, 'symbol')))
     driver.execute_script("$('#symbol').click()")
     driver.find_element_by_id('symbol').send_keys(ticker)
     WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "get"))).click()
     try:
         WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//span[@class='download-data-link']/a"))).click()
         
     except:
         print "data not available for {} on NSE for 12 months".format(ticker)
     try:
         WebDriverWait(driver, 3).until(EC.alert_is_present(),'Timed out waiting for alert creation ' +'confirmation alert to appear.')
         alert = driver.switch_to.alert
         alert.accept()
         print("alert accepted")

     except:
         print "No alert"
     
     driver.implicitly_wait(10)
     driver.refresh()


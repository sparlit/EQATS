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


import datetime
import logging
import pdb
import time
import urllib.parse as urlparse

import joblib
import pandas as pd
from kiteconnect import KiteConnect, KiteTicker
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(level=logging.ERROR)

# pip3 install selenium
# pip3 install urllib3


class ZerodhaAccessToken:
    def __init__(self):
        self.apiKey = "API_KEY"
        self.apiSecret = "API_SECRET"
        self.accountUserName = "ACCOUNT_ID"
        self.accountPassword = "ACCOUNT_PASSWORD"
        self.securityPin = "ACCOUNT_PIN"

    def getaccesstoken(self):
        try:
            login_url = f"https://kite.trade/connect/login?v=3&api_key={self.apiKey}"

            chrome_driver_path = "/usr/bin/chromedriver"
            options = Options()
            #             options.add_argument('--headless') #for headless
            driver = webdriver.Chrome(chrome_driver_path, options=options)
            driver.get(login_url)
            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.XPATH, '//input[@type="text"]'))).send_keys(
                self.accountUserName
            )
            wait.until(EC.presence_of_element_located((By.XPATH, '//input[@type="password"]'))).send_keys(
                self.accountPassword
            )
            wait.until(EC.element_to_be_clickable((By.XPATH, '//button[@type="submit"]'))).submit()
            wait.until(EC.presence_of_element_located((By.XPATH, '//input[@type="password"]'))).click()
            time.sleep(20)
            driver.find_element_by_xpath('//input[@type="password"]').send_keys(self.securityPin)
            wait.until(EC.element_to_be_clickable((By.XPATH, '//button[@type="submit"]'))).submit()
            wait.until(EC.url_contains("status=success"))
            tokenurl = driver.current_url
            parsed = urlparse.urlparse(tokenurl)
            driver.close()
            return urlparse.parse_qs(parsed.query)["request_token"][0]
        except Exception as ex:
            print(ex)


# _ztoken = ZerodhaAccessToken()
# actual_token = _ztoken.getaccesstoken()
# print('access token : '+str(actual_token))
# kite = KiteConnect(api_key=_ztoken.apiKey)
# data = kite.generate_session(actual_token,api_secret=_ztoken.apiSecret)
# kite.set_access_token(data["access_token"])
# print('request token : '+str(data["access_token"]))
# joblib.dump(kite,'kitefile.p')
# kws = KiteTicker(_ztoken.apiKey, data["access_token"])


def auto_login():
    global kite, kws, data, _ztoken, actual_token
    _ztoken = ZerodhaAccessToken()
    actual_token = _ztoken.getaccesstoken()
    print("access token : " + str(actual_token))
    kite = KiteConnect(api_key=_ztoken.apiKey)
    data = kite.generate_session(actual_token, api_secret=_ztoken.apiSecret)
    kite.set_access_token(data["access_token"])
    print("request token : " + str(data["access_token"]))
    joblib.dump(kite, "kitefile.p")
    kws = KiteTicker(_ztoken.apiKey, data["access_token"])


def retry_autologin():
    try:
        print("Trying to login...")
        auto_login()
    except AttributeError:
        retry_autologin()


# retry_autologin()

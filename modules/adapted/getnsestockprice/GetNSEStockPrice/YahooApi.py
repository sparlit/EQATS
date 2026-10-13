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


"""
    Contains implementaion for Yahoo Finance Stock Syncer library
    inherits the ApiBase base class common to all API implementations
    License : GNU GPLv2
    Author : Rajaram Srinivasan
    Initial Commit : May 2016
"""
import json
import sys
from datetime import datetime

import requests
from ApiBase import ApiBase
from dateutil import tz


class YahooApi(ApiBase):
    def __init__(self):
        """
        Initialising attributes specific to Google API
        """
        self.url_endpoint = "http://finance.yahoo.com/webservice/v1/symbols/"
        self.batch_size = 25
        self.method = "GET"

    def make_request(self, scrips):
        """
        See base class for documentation. Contains Yahoo specific implementation
        Warning : Throws exception. Use within try catch block
        """
        scrip_string = []
        for scrip in scrips:
            scrip_string.append(scrip + ".NS")
        url = self.url_endpoint + ",".join(scrip_string) + "/quote?format=json"
        resp = requests.get(url)
        if resp.status_code != requests.codes.ok:
            print >> sys.stderr, "YAHOO API ERROR"
            print >> sys.stderr, resp.json
            raise Exception("YAHOO API ERROR")
        return resp

    def get_time(self, timezone_string, utctime):
        """
        Gets timestamp of the given Timezone
        Input : tz : Timezone to be converted to
                utctime : Time in UTC as String of format
                          2016-05-30T09:59:59+0000
        """
        from_zone = tz.gettz("UTC")
        to_zone = tz.gettz(timezone_string)
        tz_time = datetime.strptime(utctime, "%Y-%m-%dT%H:%M:%S+0000")
        tz_time = tz_time.replace(tzinfo=from_zone)
        return tz_time.astimezone(to_zone)

    def process_response(self, text_responses):
        """
        See base class for documentation. Contains Yahoo specific implementation
        Warning : Throws exception. Use within try catch block
        """
        stock_data = {}
        for resp in text_responses:
            content = resp.text
            response = json.loads(content)
            resources = response["list"]["resources"]
            for resource in resources:
                price = resource["resource"]["fields"]["price"]
                volume = resource["resource"]["fields"]["volume"]
                scrip = resource["resource"]["fields"]["symbol"][:-3]
                timestamp_string = resource["resource"]["fields"]["utctime"]
                timestamp = self.get_time("Asia/Kolkata", timestamp_string)
                temp_stock_dict = {"price": price, "volume": volume, "timestamp": timestamp}
                stock_data[scrip] = temp_stock_dict
        return stock_data

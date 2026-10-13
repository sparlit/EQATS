
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


"""
    Contains implementaion for Google Finance Stock Syncer library
    inherits the ApiBase base class common to all API implementations
    Warning : This library has been declared deprecated by Google
              and may start failing anytime. Being used just because
              there are no better alternatives
    License : GNU GPLv2
    Author : Rajaram Srinivasan
    Initial Commit : May 2016
"""
import sys
import json
import requests
from ApiBase import ApiBase
class GoogleApi(ApiBase):
    def __init__(self):
        """
            Initialising attributes specific to Google API
        """
        self.url_endpoint = 'http://finance.google.com/finance/info?client=ig&q='
        self.batch_size = 20
        self.method = 'GET'

    def make_request(self, scrips):
        """
            See base class for documentation. Contains Google specific implementation
            Warning : Throws exception. Use within try catch block
        """
        scrip_string = []
        for scrip in scrips:
            scrip_string.append(scrip+':NSE')
        url = self.url_endpoint+','.join(scrip_string)
        resp = requests.get(url)
        if resp.status_code != requests.codes.ok:
            print >> sys.stderr, 'GOOGLE API ERROR'
            print >> sys.stderr, resp.json
            raise Exception('GOOGLE API ERROR')
        return resp
    def process_response(self, text_responses):
        """
            See base class for documentation. Contains Google specific implementation
            Warning : Google API does not return volume data
                      Throws exception. Use within try catch block
        """
        stock_data = {}
        for resp in text_responses:
            content = resp.text
            response = json.loads(content[3:])
            for stock in response:
                try:
                    price = stock['l_cur']
                    if price.startswith('Rs.'):
                        price = price[3:]
                    time = stock['lt_dts']
                    change_in_inr = stock['c']
                    change_in_pc = stock['cp']
                    temp_stock_dict = {'price':price, 'timestamp':time,
                                       'change_inr':change_in_inr,
                                       'change_pc':change_in_pc
                                      }
                    stock_data[stock['t']] = temp_stock_dict
                except Exception, exception_obj:
                    print >> sys.stderr, "Error Parsing Google Response"
                    print >> sys.stderr, exception_obj
                    raise Exception('Error Parsing Google Response')
        return stock_data
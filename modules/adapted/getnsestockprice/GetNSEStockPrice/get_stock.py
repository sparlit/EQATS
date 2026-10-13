
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


import sys
import argparse
from GoogleApi import GoogleApi
from YahooApi import YahooApi
#import email_base
parser = argparse.ArgumentParser(description='Gets stock prices of scrips listed in NSE')
parser.add_argument('scrips', metavar='s',
                    action="store",
                    help='Comma separated list of scrips by scrip_code in NSE')
MAX_RETRIES = 5

def get_stock_price(scrips, api_preference='Google', retries=0):
    """
        Fetches stock prices of scrips supplied as a list of strings
    """
    api_obj = None
    if retries > MAX_RETRIES:
        print >> sys.stderr, "Retries exceeded"
        return None
    if api_preference == 'Google':
        api_obj = GoogleApi()
    else:
        api_obj = YahooApi()
    scrip_data = None
    try:
        scrip_data = api_obj.get_data(scrips)
    except Exception, err_msg:
        email_base.send_mail('%s API call failed with error msg %s'%(api_preference, err_msg))
        if api_preference == 'Google':
            return get_stock_price(scrips, api_preference='Yahoo', retries=retries+1)
        else:
            return get_stock_price(scrips, api_preference='Google',retries=retries+1)
    return scrip_data

if __name__ == '__main__':
    args = parser.parse_args()
    print get_stock_price (args.scrips.split(','))
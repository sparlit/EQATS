
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


import pandas as pd
import MySQLdb
import config
from numpy import NaN
from pandas.stats.api import ols
import matplotlib.pyplot as plt
import sys
'''
first get the data,calculate previous close price,calcalate no of positive days and the distribution of the +ve
effect of open to the day close. Do the same for the -ve days.plot the distribution and as well as its statistics 
'''


def calc_positive_negative_dates(data,pos_x_min=0.005,pos_x_max=0.01,neg_y_max=-0.005,neg_y_min=-0.01):
    pdata=data[((((data.OPEN-data.PREV_CLOSE)/data.PREV_CLOSE)>pos_x_min) & (((data.OPEN-data.PREV_CLOSE)/data.PREV_CLOSE)<pos_x_max)) | ((((data.OPEN-data.PREV_CLOSE)/data.PREV_CLOSE)<neg_y_max) & (((data.OPEN-data.PREV_CLOSE)/data.PREV_CLOSE)>neg_y_min))]
    #calculate prev close to open return andn open to close return and regress
    prev_close_open=(pdata.OPEN-pdata.PREV_CLOSE)/pdata.PREV_CLOSE
    open_close=(pdata.CLOSE-pdata.OPEN)/pdata.OPEN
    fig=plt.figure()
    plt.scatter(x=prev_close_open, y=open_close)
    fig.suptitle('Posb(%03f,%03f)andNeg(%03f,%03f)'%(pos_x_min,pos_x_max,neg_y_max,neg_y_min),fontsize=20)
    plt.xlabel('prev_close_open',fontsize=10)
    plt.ylabel('open_close',fontsize=10)
    plt.savefig('Posb(%03f,%03f)andNeg(%03f,%03f).jpg'%(pos_x_min,pos_x_max,neg_y_max,neg_y_min))
    res=ols(y=open_close,x=prev_close_open)
    print res
if __name__=='__main__':
    data=config.get_symbol_future(sys.argv[1])
    calc_positive_negative_dates(data)    
    
        
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


import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.finance import candlestick2_ochl

##style.use('ggplot')


##Reading csv file and storing as dataframe in df
df = pd.read_csv("TCS.csv")


df_ohlc = df

##Mapping dates of csv file to matplotlib dates  format
df_ohlc["Date"] = df_ohlc["Date"].map(mdates.datestr2num)
##df_volume['Date']=df_volume['Date'].map(mdates.datestr2num)

ax1 = plt.subplot2grid((6, 1), (0, 0), rowspan=5, colspan=1)

##ax2=plt.subplot2grid((6,1),(5,0),rowspan=1,colspan=1,sharex=ax1)

ax1.set_title("TCS")
candlestick2_ochl(
    ax1, df_ohlc["Open"], df_ohlc["Close"], df_ohlc["High"], df_ohlc["Low"], width=2, colorup="g"
)

##ax2.fill_between(df_volume['Date'],df_volume['Total Traded Quantity'].mean(),0)
##ax1.scatter(df_ohlc['Date'],df_ohlc['Total Traded Quantity'])
plt.show()

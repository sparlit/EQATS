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


import argparse
import sys

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import animation, style
from playsound import playsound
from utilities import *

parser = argparse.ArgumentParser(description="Get Live bar graph data of Option Chain")
parser.add_argument(
    "-l",
    "--link",
    type=str,
    metavar="",
    default="https://www.nseindia.com/live_market/dynaContent/live_watch/option_chain/optionKeys.jsp?symbolCode=-9999&symbol=BANKNIFTY&symbol=BANKNIFTY&instrument=OPTIDX&date=-&segmentLink=17&segmentLink=17",
    help="Link of the required Derivative",
)
parser.add_argument(
    "-p", "--pointsnum", type=int, default=6, metavar="", help="Number of points required on either side"
)
##parser.add_argument('-q','--quantity',type=str,default='OI', metavar='',help='What you want to plot')
args = parser.parse_args()
##style.use('fivethirtyeight')

fig = plt.figure()
ax1 = fig.add_subplot(1, 1, 1)
data1 = np.zeros(1)


def animate(i):
    web_data = nse_data(args.link)
    ##Get Data
    global data1
    data = np.asarray(web_data["Data"])
    if not np.array_equal(data1, data):
        playsound("notification.wav")
    ##Total Size of Chart
    ##mid_value = data.shape[0]
    values_from_mid = args.pointsnum
    spot_price = web_data["Price"]
    mid_value = np.argmin(np.abs(data[:, 10] - spot_price))
    ##Number of prices you want
    index_start = int(mid_value - values_from_mid)
    index_end = int(mid_value + values_from_mid)
    bar_width = 0.35
    ## Annotations we need
    strike_prices = data[index_start:index_end, 10]

    indices = np.arange(index_end - index_start)
    y1 = data[index_start:index_end, 0].astype(float)
    y2 = data[index_start:index_end, -1].astype(float)
    z1 = np.divide(y2, y1)
    z2 = np.divide(y1, y2)
    ax1.clear()
    ax1.bar(indices, z1, bar_width, color="b", label="Ratios Put by Call")
    ax1.bar(indices + bar_width, z2, bar_width, color="r", label="Ratios Call by Put")
    ax1.set_xlabel("Strike Prices")
    ax1.set_ylabel("Put Call Ratio")
    ax1.set_title(
        "Live Bar Graph for Put Call Ratio, Total Put Contract : "
        + str(web_data["Total_C_and_P"][-1])
        + " Total Call Contracts : "
        + str(web_data["Total_C_and_P"][0])
        + " P/C ratio : "
        + str(web_data["Total_C_and_P"][-1] / web_data["Total_C_and_P"][0])
    )
    ax1.set_xticks(indices + bar_width / 2)
    ax1.set_xticklabels(strike_prices, rotation=90)
    ax1.legend()
    ax1.grid()
    data1 = data


ani = animation.FuncAnimation(fig, animate, interval=10000)
plt.show()

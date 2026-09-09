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


# install these libraries - nsetools,pprint,csv
from csv import writer
from pprint import pprint

from nsetools import Nse


# function to insert things into csv
def append_list_as_row(file_name, list_of_elem):
    # Open file in append mode
    with open(file_name, "a+", newline="") as write_obj:
        # Create a writer object from csv module
        csv_writer = writer(write_obj)
        # Add contents of list as last row in the csv file
        csv_writer.writerow(list_of_elem)


nse = Nse()

# this list just stores names of the required stocks so that
# you can use this directly into your code and use accordingly
stocks_list = []

# top gainers
top_gainers = nse.get_top_gainers()

# remove comment of the next line to see all fields available
# pprint(top_gainers[0])

# insert column titles
row = ["Stock name", "Open price", "High price", "Low price", "Previous price", "Volume", "Ltp"]

# inserts the columns names into the csv file
append_list_as_row("topGainers.csv", row)


# change value of range to receive your required numbers of stocks max-10
for i in range(5):
    stock_name = top_gainers[i]["symbol"]
    open_price = top_gainers[i]["openPrice"]
    previous_price = top_gainers[i]["previousPrice"]
    volume = top_gainers[i]["tradedQuantity"]
    high_price = top_gainers[i]["highPrice"]
    low_price = top_gainers[i]["lowPrice"]
    ltp = top_gainers[i]["ltp"]
    row = [stock_name, open_price, high_price, low_price, previous_price, volume, ltp]

    # file is named topGainers
    append_list_as_row("topGainers.csv", row)

    # adds the names of gainer stocks to the list
    stocks_list.append(stock_name)


# top losers
top_losers = nse.get_top_losers()

# remove comment of the next line to see all fields available
# pprint(top_losers[0])

# insert column titles
row = ["Stock name", "Open price", "High price", "Low price", "Previous price", "Volume", "Ltp"]

# inserts the columns names into the csv file
append_list_as_row("topLosers.csv", row)

# change value of range to receive your required numbers of stocks max-10
for i in range(5):
    stock_name = top_losers[i]["symbol"]
    open_price = top_losers[i]["openPrice"]
    previous_price = top_losers[i]["previousPrice"]
    volume = top_losers[i]["tradedQuantity"]
    high_price = top_losers[i]["highPrice"]
    low_price = top_losers[i]["lowPrice"]
    ltp = top_losers[i]["ltp"]
    row = [stock_name, open_price, high_price, low_price, previous_price, volume, ltp]

    # file is named topLosers.csv
    append_list_as_row("topLosers.csv", row)

    # adds the name of the loser stocks
    stocks_list.append(stock_name)

# remove the next line's comment to see the stock names or use the list in your code directly
# print(stocks_list)

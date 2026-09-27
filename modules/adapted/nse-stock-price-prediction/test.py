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


import csv

import pandas as pd

# def money_to_float(money_str):
#     return 12
#
# file =  pd.read_csv('EQTY.csv')
# #
# # print(file[[-1]])
#
# file[[-1]] = file[[-1]].apply(money_to_float)
#
# print(file[[-1]])

mylist = []


with open("SCOM.csv", newline="") as csvfile:
    spamreader = csv.reader(csvfile, delimiter=",", quotechar="|")
    for row in spamreader:
        print(row)
        try:
            int(row[-1])
        except:
            n = row[-1]
            m = n.find("M")
            x = n.replace("M", "")
            n = float(x) * 1000000
            # print(int(n))
            row[-1] = int(n)
            mylist.append(row)


myFile = open("safaricom.csv", "w")
writeFile = csv.writer(myFile, delimiter=",")
writeFile.writerows(mylist)


# m = list(file[[-1]])
#
# print(m)

#
#
# for index, i in file.iterrows():
#     # print(i[-1])
#
#     try:
#         int(file[[-1]])
#     except:
#         print(i)
# print(file[[-1]])
# file[[-1]] = 0
# bh =0
# n = i[-1]
# print(n)
# m = n.find("M")
# x = n.replace('M','')
#
# n = float(x)*1000000
#
# print(int(n))


# print(file[[-1]])


# n = '1.42M'
#
# print(n.find("M"))


#
# x = n.replace('M','')
#
# n = float(x)*1000000
#
# print(int(n))

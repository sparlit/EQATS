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


# f = open("nse_data.txt", "r")
myList = []
news = []
date = []
date_in_correct_format = []
demoList = []

with open("nse_data.txt") as f:
    for line in f:
        myList.append(line)

for i in range(2, 12000, 6):
    myList[i] = myList[i].replace(",", ";")
    print(myList[i])
    news.append(myList[i])

f = open("News.txt", "w")
f3 = open("Data.csv", "w")

for i in range(4, 12000, 6):
    date.append(myList[i])

for i in news:
    f.write(i)

f2 = open("Date.txt", "w")

months = {"Jan.": "01", "Feb.": "02", "March": "03"}

for i in date:
    demoList = i.split()
    str = demoList[2]
    if len(demoList[3]) == 2:
        demoList[3] = "0" + demoList[3]
    #    if i[-9] == " ":
    #        i[-9] = "0"
    date_in_correct_format.append(i[-5:-1] + "-" + months[str] + "-" + demoList[3][0:2])


for i in range(len(date_in_correct_format)):
    f3.write(date_in_correct_format[i] + "," + news[i])

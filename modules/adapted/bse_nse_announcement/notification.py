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


import os
import time

import notify2

# path to notification window icon
ICON_PATH = os.getcwd() + "/icon.jpeg"

# fetch news items
# newsitems = topStories()
newsitems = {
    "description": "Months after it was first reported, the feud between Dwayne Johnson and Vin Diesel continues to rage on, with a new report saying that the two ar being kept apart during the promotions of The Fate of the Furious.",
    "link": "http://www.hindustantimes.com/hollywood/vin-diesel-dwayne-johnson-feud-rageson-they-re-being-kept-apart-for-fast-8-tour/story-Bwl2Nx8gja9T15aMvcrcvL.html",
    "media": "http://www.hindustantimes.com/rf/image_size_630x354/HT/p2/2017/04/01/Pictures/_fbcbdc10-1697-11e7-9d7a-cd3db232b835.jpg",
    "pubDate": b"Sat, 01 Apr 2017 05:22:51 GMT ",
    "title": "Vin Diesel, Dwayne Johnson feud rages on; they're being deliberately kept apart",
}

# initialise the d-bus connection
notify2.init("News Notifier")

# create Notification object
n = notify2.Notification(None, icon=ICON_PATH)

# set urgency level
# n.set_urgency(notify2.URGENCY_NORMAL)
n.set_urgency(notify2.URGENCY_CRITICAL)

# set timeout for a notification
n.set_timeout(10000)

for newsitem in newsitems:
    # update notification data for Notification object
    n.update(newsitem[2], newsitem[3])

    # show notification on screen
    n.show()

    # short delay between notifications
    # time.sleep(15)

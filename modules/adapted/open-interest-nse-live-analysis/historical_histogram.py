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


import matplotlib.pyplot as plt
import numpy as np

no_of_bins = 5
data = np.genfromtxt("data.csv", delimiter=",", dtype=str)
values = data[1:, 1:5]
for i in range(values.shape[0]):
    for j in range(values.shape[1]):
        values[i, j] = values[i, j].replace("    ", "")
        values[i, j] = values[i, j].replace('"', "")
values = values.astype(float)
change = values[:, -1] - values[:, 0]
swing = values[:, 1] - values[:, 2]
plt.figure(1)
plt.subplot(211)
plt.hist(change, 100, density=True, facecolor="g", alpha=0.75)
plt.xlabel("Change")
plt.ylabel("Probability")
plt.title("Change Probability")
##plt.axis([-450,450,0,0.0025])
plt.grid(True)

plt.subplot(212)
plt.hist(swing, 100, density=True, facecolor="g", alpha=0.75)
plt.xlabel("Swing")
plt.ylabel("Probability")
plt.title("Swing Probability")
##plt.axis([100,800,0,0.004])
plt.grid(True)
plt.show()

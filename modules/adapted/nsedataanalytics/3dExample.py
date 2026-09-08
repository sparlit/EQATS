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
from matplotlib import cm
from mpl_toolkits.mplot3d import axes3d

fig = plt.figure()
ax = fig.gca(projection="3d")
X, Y, Z = axes3d.get_test_data(0.05)
ax.plot_surface(X, Y, Z, rstride=8, cstride=8, alpha=0.3)
cset = ax.contour(X, Y, Z, zdir="z", offset=-100, cmap=cm.coolwarm)
cset = ax.contour(X, Y, Z, zdir="x", offset=-40, cmap=cm.coolwarm)
cset = ax.contour(X, Y, Z, zdir="y", offset=40, cmap=cm.coolwarm)

ax.set_xlabel("X")
ax.set_xlim(-40, 40)
ax.set_ylabel("Y")
ax.set_ylim(-40, 40)
ax.set_zlabel("Z")
ax.set_zlim(-100, 100)

plt.show()

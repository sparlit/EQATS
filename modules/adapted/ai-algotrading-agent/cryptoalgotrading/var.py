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


"""
var.py

Framework predefined variables.

It is important to define some environment variables before use this
framework, if user wants to use DB and Exchanges' credentials.
"""

from datetime import datetime
from os import getcwd, getenv

# DATABASE VARIABLES
# Best option should be define vars on system
# and then get environment variables.
db_user = getenv("DB_USER") or "user"
db_password = getenv("DB_PASSWD") or "passwd"
db_name = getenv("DB_NAME") or "bd"

data_dir = getenv("DATA_DIR") or "."
logs_dir = getenv("LOGS_DIR") or "."

LOG_FILENAME = logs_dir + "/indicators.log"

fig_dir = "figs/"

db_host = getenv("db_host") or "localhost"
db_port = getenv("db_port") or 8086

# interval must be coincident with Influxdb intervals.
default_interval = "10m"

default_smas = [10, 20, 30]
default_emas = [2, 4, 8]
default_volume_smas = [3, 6]
default_volume_emas = [3, 6]
default_mom = 4

# Stop type:
# - 0: No stop loss method
# - 1: Stop loss
# - 2: Trailing stop loss
# - 3: Both stop loss methods
stop_type = 3
stop_loss_prcnt = 2.0
trailing_loss_prcnt = 3.0

smaller_qnt = 20

validity = 50
refresh_interval = 60  # interval in seconds.

# pairs first market.
main_coins = ["BTC", "USDT"]

default_exchange = "binance"

btr_ky = getenv("BTX_API_KEY") or ""
btr_sct = getenv("BTX_API_SECRET") or ""

bnb_ky = getenv("BNC_API_KEY") or ""
bnb_sct = getenv("BNC_API_SECRET") or ""

# define minimum balance to buy and risk.
usdt_min = 50
btc_min = 0.001
risk = 0.20

bnb_commission = 0.075
commission = True

# Uses system notification to present relevant info
desktop_info = True
# Add special effects to notifications
desktop_cool_mode = True

img_profit = f"{getcwd()}/img/profit.png"
img_loss = f"{getcwd()}/img/loss.png"

# Reports vars
report = True
report_dir = "reports/"
report_file = f"{report_dir}report{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"

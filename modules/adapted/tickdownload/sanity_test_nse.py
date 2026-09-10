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


# A sanity test for all nse download scrips.
# Sanity test should ensure that following downloads are still working
#
# pylint: disable-msg=wrong-import-position,ungrouped-imports
import random

# 1. Get a list of all nse symbols
from tickerplot.nse.nse_utils import nse_get_all_stocks_list

nse_get_all_stocks_list(start=random.randint(1, 10), count=2)
del nse_get_all_stocks_list

# 2. Get Corporate actions for a symbol ('infy')
from corp_actions_nse import get_corp_action_csv

get_corp_action_csv("INFY")
del get_corp_action_csv

# 3. Get a list of symbol name changes
from tickerplot.nse.nse_utils import nse_get_name_change_tuples

nse_get_name_change_tuples()
del nse_get_name_change_tuples

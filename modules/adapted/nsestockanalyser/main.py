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


from NseStockAnalyser.Index_best_buy_stocks import index_52_wk_lows
from NseStockAnalyser.open_interest_graphs import oi_graph_wrapper
from NseStockAnalyser.option_chain_analysis import opt_chain_wrapper
from NseStockAnalyser.put_call_ratio import put_call_wrapper

print("+++++++++++++++++ NSE STOCK ANALYSER ++++++++++++++++++++")
options = ["Option Chain Analysis", "Put/Call Ratio", "Open Interest Graphs", "Index stocks near 52 week low", "Exit"]
while True:
    for i in range(len(options)):
        print(f"{i + 1} : {options[i]}")

    try:
        opt_id = int(input("What analysis you want to perform? (Please enter option ID) : "))
    except ValueError:
        print("Please enter a valid option")
        continue

    if opt_id < 1 or opt_id > len(options):
        print("Please enter a valid option")
        continue

    if opt_id == 1:
        opt_chain_wrapper()

    if opt_id == 2:
        put_call_wrapper()

    if opt_id == 3:
        oi_graph_wrapper()

    if opt_id == 4:
        index_52_wk_lows()

    if opt_id == len(options):
        print("Thank you for using the application")
        break

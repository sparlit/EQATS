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


from NseStockAnalyser.utils import *


@continuation_handler
def opt_chain_wrapper():
    code = input("Enter Stock Code : ")
    data_points = int(input("How many data points you want per category? : "))

    ce_strk_dict, pe_strk_dict, max_pain_dict, lot_size = opt_chain_analysis(code.upper(), data_points)

    for i in range(data_points):
        print(f"Resistance Point {i + 1} :- Strike Price = {ce_strk_dict[i][0]} : OI = {ce_strk_dict[i][1] * lot_size}")

    print("==========================================================================")

    for i in range(data_points):
        print(f"Support Point {i + 1} :- Strike Price = {pe_strk_dict[i][0]} : OI = {pe_strk_dict[i][1] * lot_size}")

    print("==========================================================================")

    for i in range(data_points):
        print(f"Max Pain Point {i + 1} :- Strike Price = {max_pain_dict[i][0]} : OI = {max_pain_dict[i][1] * lot_size}")


def opt_chain_analysis(stock_code, data_points):
    nse = Nse()

    lot_size = nse.get_fno_lot_sizes()[stock_code]

    ce_pe, exp_date = get_opt_chain_data_json(stock_code)

    ce_strk_dict, pe_strk_dict, max_pain_dict = {}, {}, {}

    for val in ce_pe:
        try:
            ce_oi = val["CE"]["openInterest"]
            pe_oi = val["PE"]["openInterest"]
        except KeyError:
            continue

        ce_oi + pe_oi

        ce_strk_dict.update({val["strikePrice"]: ce_oi})
        pe_strk_dict.update({val["strikePrice"]: pe_oi})
        max_pain_dict.update({val["strikePrice"]: ce_oi + pe_oi})

    ce_strk_dict = sorted(ce_strk_dict.items(), key=lambda item: item[1], reverse=True)
    pe_strk_dict = sorted(pe_strk_dict.items(), key=lambda item: item[1], reverse=True)
    max_pain_dict = sorted(max_pain_dict.items(), key=lambda item: item[1], reverse=True)

    print(f"========OPTION CHAIN ANALYSIS DATA FOR {stock_code.upper()} FOR EXPIRY {exp_date.upper()}========")

    return ce_strk_dict, pe_strk_dict, max_pain_dict, lot_size

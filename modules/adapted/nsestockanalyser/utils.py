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


from NseStockAnalyser.imports import *


def continuation_handler(original_fn):
    def wrapper_fn():
        while True:
            try:
                original_fn()
            except (ValueError, KeyError):
                print("Wrong data, or the stock is not traded as derivatives")
                continue

            while True:
                flg = input("\n\rDo you want to know about more stock derivatives?(Y/N) : ").upper()
                if flg in {"Y", "N"}:
                    break
                print("Answer should be either Y(Yes) or N(No)")

            if flg == "N":
                return

    return wrapper_fn


def get_all_index_names():
    return requests.get(NSE_INDICES_URL, headers=headers).json()


def get_index():
    index_lists_json = get_all_index_names()
    index_type_list = list(index_lists_json.keys())
    index_type_list_len = len(index_type_list)
    while True:
        for i in range(index_type_list_len):
            print(f"{i + 1} : {index_type_list[i]}")

        try:
            index_type = int(input(f"Please enter Index Type (Input Range 1 - {index_type_list_len}): "))
            if not 1 <= index_type <= index_type_list_len:
                raise ValueError
        except ValueError:
            print("Please Enter Valid Input")

        while True:
            indices = index_lists_json[index_type_list[index_type - 1]]
            indices_len = len(indices)
            for i in range(indices_len):
                print(f"{i + 1} : {indices[i]}")

            try:
                index = int(input(f"Please enter Index (Input Range 1 - {indices_len}): "))
                if not 1 <= index <= indices_len:
                    raise ValueError
            except ValueError:
                print("Please Enter Valid Input")

            return indices[index - 1]


def get_index_stock_data_json(index):
    url_enc_str = urllib.parse.quote(index.upper())
    url = "https://www.nseindia.com/api/equity-stockIndices?index=" + url_enc_str
    return requests.get(url, headers=headers).json()


def get_raw_json_data(stock_code):
    deriv_type = "indices" if stock_code in {"NIFTY", "NIFTYIT", "BANKNIFTY"} else "equities"

    url = "https://www.nseindia.com/api/option-chain-" + deriv_type + "?symbol=" + stock_code
    return requests.get(url, headers=headers).json()


def get_expiry_date(all_exp_dates):

    today = datetime.now()
    last_thurs = today + relativedelta(day=31, weekday=TH(-1))
    curr_month = last_thurs.month

    flag = 0
    if today > last_thurs:
        curr_month = curr_month + 1
        if curr_month > 12:
            flag = 1
            curr_month = 1

    month_year = cl.month_abbr[curr_month] + "-" + str(today.year + flag)

    curr_month_exp_dates = []
    for i_date in all_exp_dates:
        if month_year in i_date:
            curr_month_exp_dates.append(i_date)

    if len(curr_month_exp_dates) == 1:
        return curr_month_exp_dates[0]

    for i in range(len(curr_month_exp_dates)):
        print(f"{i + 1} : {curr_month_exp_dates[i]}")

    while True:
        try:
            opt_id = int(input(f"Please select expiry date (Input Range 1 - {len(curr_month_exp_dates)}) : "))
            if not 1 <= opt_id <= len(curr_month_exp_dates):
                raise ValueError
            break
        except ValueError:
            print("Please enter a valid option")

    return curr_month_exp_dates[opt_id - 1]


def get_opt_chain_data_json(stock_code):
    data_json = get_raw_json_data(stock_code)
    data_records = data_json["records"]["data"]
    exp_date = get_expiry_date(data_json["records"]["expiryDates"])

    opt_data = []
    for data in data_records:
        if data["expiryDate"] == exp_date:
            opt_data.append(data)

    return opt_data, exp_date

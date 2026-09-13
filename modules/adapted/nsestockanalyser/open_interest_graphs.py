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


def open_interest_graphs(stock_code, no_days, strike_price, opt_type):
    index = False
    if stock_code in {"NIFTY", "NIFTYIT", "BANKNIFTY"}:
        index = True

    end_date = date.today()
    start_date = end_date - timedelta(days=no_days)
    expiry_date = datetime.strptime(
        get_expiry_date(get_raw_json_data(stock_code)["records"]["expiryDates"]), "%d-%b-%Y"
    ).date()

    if opt_type in {"CE", "PE"}:
        stock_opt = get_history(
            symbol=stock_code,
            start=start_date,
            end=end_date,
            option_type=opt_type,
            strike_price=strike_price,
            expiry_date=expiry_date,
            index=index,
        )

        x = list(dict(stock_opt["Open Interest"]).keys())
        y = list(dict(stock_opt["Open Interest"]).values())

    elif opt_type == "TOTAL":
        stock_opt_ce = get_history(
            symbol=stock_code,
            start=start_date,
            end=end_date,
            option_type="CE",
            strike_price=strike_price,
            expiry_date=expiry_date,
            index=index,
        )

        stock_opt_pe = get_history(
            symbol=stock_code,
            start=start_date,
            end=end_date,
            option_type="PE",
            strike_price=strike_price,
            expiry_date=expiry_date,
            index=index,
        )

        x = list(dict(stock_opt_ce["Open Interest"]).keys())
        a = list(dict(stock_opt_ce["Open Interest"]).values())
        b = list(dict(stock_opt_pe["Open Interest"]).values())
        y = [i + j for i, j in zip(a, b, strict=False)]

    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m/%d/%Y"))
    plt.gca().xaxis.set_major_locator(mdates.DayLocator())
    plt.plot(x, y)
    plt.gcf().autofmt_xdate()
    plt.xlabel("Date")
    plt.ylabel("Open Interest")

    plt.title(
        f"{opt_type} Open Interest variation at strike price of Rs.{strike_price} in the past {no_days} days for expiry {expiry_date}\n"
    )
    plt.show()


@continuation_handler
def oi_graph_wrapper():
    stock_code = input("Enter Stock Code : ").upper()
    nse = Nse()

    nse.get_fno_lot_sizes()[stock_code]

    no_days = int(input("Please enter number of days you want past data of (Min = 2, Max = 20) : "))
    if no_days < 2 or no_days > 20:
        raise ValueError

    strike_price_list = get_raw_json_data(stock_code)["records"]["strikePrices"]
    strike_price = int(
        input(
            f"Please enter strike price (Data is available from Rs.{strike_price_list[0]} to Rs.{strike_price_list[-1]}) : "
        )
    )

    if strike_price not in strike_price_list:
        print("Data for this strike price is not available")
        raise ValueError

    while True:
        opt_type = input("Please Enter Option Type (CE/PE/TOTAL) : ").upper()
        if opt_type in {"CE", "PE", "TOTAL"}:
            break
        print("Please enter valid option type")
        raise ValueError

    open_interest_graphs(stock_code, no_days, strike_price, opt_type)

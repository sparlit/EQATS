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


import psycopg2


def get_close_prices():
    cash_market_sql = """
        select symbol, trade_date, close
        from nse_cash_market_tab
        where trade_Date = to_Date('2021-10-22','yyyy-MM-dd')
        order by symbol
    """

    connection = psycopg2.connect(
        database="postgres", user="postgres", password="postgres", host="localhost", port=5432
    )
    cursor = connection.cursor()
    cursor.execute(cash_market_sql)

    # print(datetime.datetime.now())
    cash_market_records = cursor.fetchall()
    # print(datetime.datetime.now())

    symbol_to_close = {}
    for each_record in cash_market_records:
        symbol = each_record[0]
        symbol_to_close[symbol] = each_record[2]

    return symbol_to_close

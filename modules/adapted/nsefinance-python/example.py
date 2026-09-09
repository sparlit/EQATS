
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
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


from nsefinance import NSEFinance

stocks = NSEFinance()



"""
Available keys :
[u'high', u'symbol', u'value', u'deals', u'date', u'low', u'units', u'close', u'open', u'change']

"""
#Get closing prices for all the symbols for the trading day.
result = stocks.get_daily_list()
for i in range(len(result)):
	print result[i]['close'] 



#Get the closing price for the last 5 trading day for a symbol
result = stocks.get_by_symbol("OANDO")
for i in range(len(result)):
	print result[i]['close']




#Get the closing price for a particular symbol on a particular day
symbol = "OANDO"
result = stocks.get_by_symbol(symbol,"2014-02-06")
print result[symbol]['close']
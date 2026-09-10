
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


from config import get_symbol_future,get_symbols
import pandas as pd

def calc_ema_slow_fast(data,sma,lma,symbol,threshold):
    
    if data.empty:
        return
    data['SMA']=pd.ewma(data.CLOSE,span=sma)
    data['LMA']=pd.ewma(data.CLOSE,span=lma)
    last_lema=data.LMA.values[-1]
    last_sema=data.SMA.values[-1]
    close=data.CLOSE.values[-1]
    buydiff=(last_sema-last_lema*(1+threshold))/close
    selldiff=(last_sema-last_lema*(1-threshold))/close
    if (buydiff>0):
        return ("Buy",buydiff)
    elif (selldiff<0):
        return ("Sell",selldiff)
    else:
        return ("Neutral",0)
    

if __name__=='__main__':
    sma=11
    lma=22
    threshold=0.02
    symbols=get_symbols() 
    result=pd.DataFrame()
    for symbol in symbols:
        data=get_symbol_future(symbol)
        if data.empty:
            continue
        (signal,strength)=calc_ema_slow_fast(data, sma, lma, symbol, threshold)
        #print symbol+"\t"+"Signal="+signal+"\n"
        result=result.append({'SYMBOL':symbol,'SIGNAL':signal,'STRENGTH':strength},ignore_index=True)
    result=result.sort(columns='STRENGTH',ascending=False)
    print "Top Buyers are"
    print result.head(5)
    print "Top Sellers are"
    print result.tail(5)
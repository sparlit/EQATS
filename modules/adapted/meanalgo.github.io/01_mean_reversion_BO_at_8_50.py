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


import datetime
import logging
from datetime import datetime as dt

import pandas as pd
import requests
from bs4 import BeautifulSoup

# enable dbug to see request and responses
logging.basicConfig(level=logging.DEBUG)

capital_per_stock = 5000
leverage = 3
trades = []
stock_count = 0
entry_taken = {}


def get_stocks():
    global stock_count, df
    # print('get stocks time :: ', dt.now(tz=zone))
    t = dt.today()

    with requests.Session() as s:
        scanner_url = "https://chartink.com/screener/vishal-mehta-mean-reversion"
        r = s.get(scanner_url)
        soup = BeautifulSoup(r.text, "html.parser")
        csrf = soup.select_one("[name='csrf-token']")["content"]
        s.headers["x-csrf-token"] = csrf

        process_url = "https://chartink.com/screener/process"
        payload = {
            "scan_clause": "( {33489} ( latest close > latest sma( close, 200 ) and latest rsi( 2 ) > 50 and "
            "latest close > 1 day ago close * 1.03 and latest close > 50 and latest close < 5000 and latest close > ( 4 days ago close * 1.0 ) ) ) "
        }

        r = s.post(process_url, data=payload)
        data = r.json()["data"]
        stock_count = len(data)
        print(f"Total stocks today : {stock_count}")
        if stock_count == 0:
            print("There are no stocks in scanner today, returning")
            return
        df = pd.DataFrame()
        for item in r.json()["data"]:
            df = pd.concat([df, pd.DataFrame([item])], ignore_index=True)
        if len(df) > 0:
            df.sort_values(by=["per_chg"], ascending=False, inplace=True)
            df.drop("sr", axis=1, inplace=True)
            df.reset_index(inplace=True)
            df.drop("index", axis=1, inplace=True)
        print(df)
        df.to_csv(t.strftime("data/%Y%m%d_") + "mean_reversion_chartink.csv", index=False)


def process_for_mean_reversion():
    global stock_count
    get_stocks()
    # print('process stocks time :: ', dt.now(tz=zone))
    if stock_count == 0:
        print("There were no stocks in scanner today, returning")
        return
    t = dt.today()
    df = pd.read_csv(t.strftime("data/%Y%m%d_") + "mean_reversion_chartink.csv", index_col=None)
    print(f"number of stocks :: {len(df)}")
    df = df[["nsecode", "per_chg", "close"]]
    trigger_price = round(0.05 * (round(df["close"] * 1.01, 1) / 0.05), 2)
    df["trigger_price"] = trigger_price
    stoploss = round(0.05 * (round(df["trigger_price"] * 1.03, 1) / 0.05), 2)  # 3% stoploss
    df["stoploss"] = stoploss
    target = round(0.05 * round(df["trigger_price"] * 0.95, 1) / 0.05, 2)  # 5% target
    df["target"] = target
    df["qty"] = capital_per_stock // df["trigger_price"]
    df["qty"] = df["qty"].astype(int)
    # df['qty']=1
    if len(df) > 10:
        print("returning only first 10 stocks")
        df = df.head(10)
    df.to_csv(t.strftime("data/mean_reversion.csv"))


if __name__ == "__main__":
    process_for_mean_reversion()

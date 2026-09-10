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


"""Create Correlation and other graph in for nifty with S&P,DAX,Chinese Markets,Gold,Crude Oil"""
import datetime

import matplotlib.pyplot as plt
import MySQLdb
import Quandl

import config

"""CNXNIFTY-YAHOO/INDEX_NSEI,FRED/DCOILBRENTEU-Oil,YAHOO/INDEX_GSPC-S&P500,YAHOO/INDEX_SSEC-China Cmposite Index,YAHOO/INDEX_GDAXI-DAX,LBMA/GOLD-Gold Prices"""


def update_global_data():
    data = Quandl.get(
        [
            "YAHOO/INDEX_NSEI.4",
            "FRED/DCOILBRENTEU.1",
            "YAHOO/INDEX_GSPC.4",
            "YAHOO/INDEX_SSEC.4",
            "YAHOO/INDEX_GDAXI.4",
            "LBMA/GOLD.1",
        ],
        authtoken=config.quandl_apikey,
        trim_start="2001-01-01",
        returns="pandas",
    )
    data.columns = ["NIFTY", "OIL", "SP500", "ChinaComp", "DAX", "GOLD"]
    data = data.fillna(method="ffill")
    db = MySQLdb.connect(config.host, config.user, config.password, "NSE")
    data.to_sql("MACRO", con=db, flavor="mysql", if_exists="replace", chunksize=200)
    """Calcualte ratio Graphs"""

    data["NIFTY_OIL"] = data.NIFTY / data.OIL
    data["NIFTY_SP"] = data.NIFTY / data.SP500
    data["NIFTY_CHINA"] = data.NIFTY / data.ChinaComp
    data["NIFTY_DAX"] = data.NIFTY / data.DAX
    data["NIFTY_GOLD"] = data.NIFTY / data.GOLD
    return data


if __name__ == "__main__":
    update_global_data()
    ratio = data[["NIFTY_OIL", "NIFTY_SP", "NIFTY_CHINA", "NIFTY_DAX", "NIFTY_GOLD"]]
    d = datetime.date.today() - datetime.timedelta(6 * 365 / 12)
    ratio = ratio[ratio.index > d.__str__()]
    ratio.plot(subplots=True)
    plt.show()

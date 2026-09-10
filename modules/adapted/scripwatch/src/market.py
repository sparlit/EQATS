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


# ---------------------------------------------------------------------------------------------
#  Copyright (c) Akash Nag. All rights reserved.
#  Licensed under the MIT License. See LICENSE.md in the project root for license information.
# ---------------------------------------------------------------------------------------------

from formatting import get_current_time
from nsetools import Nse

nse = None

dummy_data = {
    "adhocMargin": None,
    "applicableMargin": 12.5,
    "averagePrice": 1999.82,
    "bcEndDate": None,
    "bcStartDate": None,
    "buyPrice1": 1999.45,
    "buyPrice2": 1999.4,
    "buyPrice3": 1999.35,
    "buyPrice4": 1999.15,
    "buyPrice5": 1999.1,
    "buyQuantity1": 50.0,
    "buyQuantity2": 209.0,
    "buyQuantity3": 22.0,
    "buyQuantity4": 1.0,
    "buyQuantity5": 24.0,
    "change": 25.35,
    "closePrice": None,
    "cm_adj_high_dt": "01-DEC-14",
    "cm_adj_low_dt": "30-MAY-14",
    "cm_ffm": 190659.16,
    "companyName": "Infosys Limited",
    "css_status_desc": "Listed",
    "dayHigh": 2010.0,
    "dayLow": 1972.0,
    "deliveryQuantity": 258080.0,
    "deliveryToTradedQuantity": 51.54,
    "exDate": "02-DEC-14",
    "extremeLossMargin": 5.0,
    "faceValue": 5.0,
    "high52": 2201.1,
    "indexVar": None,
    "isinCode": "INE009A01021",
    "lastPrice": 1999.75,
    "low52": 1440.0,
    "marketType": "N",
    "ndEndDate": None,
    "ndStartDate": None,
    "open": 1972.0,
    "pChange": 1.28,
    "previousClose": 1974.4,
    "priceBand": "No Band",
    "pricebandlower": 1777.0,
    "pricebandupper": 2171.8,
    "purpose": "BONUS 1:1",
    "quantityTraded": 500691.0,
    "recordDate": "03-DEC-14",
    "secDate": "1JAN2015",
    "securityVar": 5.02,
    "sellPrice1": 2000.0,
    "sellPrice2": 2000.5,
    "sellPrice3": 2000.55,
    "sellPrice4": 2000.6,
    "sellPrice5": 2000.85,
    "sellQuantity1": 5.0,
    "sellQuantity2": 21.0,
    "sellQuantity3": 250.0,
    "sellQuantity4": 250.0,
    "sellQuantity5": 250.0,
    "series": "EQ",
    "symbol": "INFY",
    "totalBuyQuantity": 78715.0,
    "totalSellQuantity": 80295.0,
    "totalTradedValue": 22914.16,
    "totalTradedVolume": 1145811.0,
    "varMargin": 7.5,
}


def fetch_data(code):
    global nse
    try:
        updated = get_current_time()
        stockData = nse.get_quote(code)
        return (stockData, updated)
    except Exception:
        return (None, None)


def isValid(code):
    global nse
    return nse.is_valid_code(code)


def init_NSE():
    global nse
    nse = Nse()

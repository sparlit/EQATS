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


# -*- coding: utf-8 -*-
import pandas as pd
import talib as ta
from nseta.archives.archiver import *
from nseta.common.log import default_logger, tracelog
from nseta.live.live import get_live_quote
from nseta.resources.resources import *
from nseta.scanner.baseStockScanner import baseStockScanner

__all__ = ["liveStockScanner"]


class liveStockScanner(baseStockScanner):
    def __init__(self, indicator="all"):
        super().__init__(indicator=indicator)
        self._keys = [
            "symbol",
            "previousClose",
            "lastPrice",
            "deliveryToTradedQuantity",
            "BuySellDiffQty",
            "totalTradedVolume",
            "pChange",
            "FreeFloat",
        ]

    @property
    def keys(self):
        return self._keys

    @tracelog
    def scan_quanta(self, **kwargs):
        stocks = kwargs["items"]
        frames = []
        signalframes = []
        df = None
        signaldf = None
        pd.set_option("mode.chained_assignment", None)
        for stock in stocks:
            try:
                self.update_progress(stock)
                result, primary = get_live_quote(stock, keys=self.keys)
                if primary is not None and len(primary) > 0:
                    row = pd.DataFrame(
                        primary,
                        columns=[
                            "Updated",
                            "Symbol",
                            "close",
                            "LTP",
                            "% Delivery",
                            "Buy - Sell",
                            "TotalTradedVolume",
                            "pChange",
                            "FreeFloat",
                        ],
                        index=[""],
                    )
                    value = (row["LTP"][0]).replace(" ", "").replace(",", "")
                    if stock in self.stocksdict:
                        (self.stocksdict[stock]).append(float(value))
                    else:
                        self.stocksdict[stock] = [float(value)]
                    index = len(self.stocksdict[stock])
                    if index >= 15:
                        dfclose = pd.DataFrame(self.stocksdict[stock], columns=["close"])
                        rsi = ta.RSI(dfclose["close"], resources.rsi().period)
                        rsivalue = rsi[index - 1]
                        row["RSI"] = rsivalue
                        default_logger().debug(stock + " RSI:" + str(rsi))
                        if rsivalue > resources.rsi().upper or rsivalue < resources.rsi().lower:
                            signalframes.append(row)
                    frames.append(row)
            except Exception as e:
                default_logger().debug("Exception encountered for " + stock)
                default_logger().debug(e, exc_info=True)
        if len(frames) > 0:
            df = pd.concat(frames)
            # default_logger().debug(df.to_string(index=False))
        if len(signalframes) > 0:
            signaldf = pd.concat(signalframes)
            # default_logger().debug(signaldf.to_string(index=False))
        return [df, signaldf]

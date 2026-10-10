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


"""
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

"""
import os

from PKDevTools.classes import log as log
from PKDevTools.classes.log import default_logger
from PKDevTools.classes.Singleton import SingletonMixin, SingletonType
from PKDevTools.classes.SuppressOutput import SuppressOutput
from PKNSETools.PKNSEStockDataFetcher import nseStockDataFetcher


class MarketStatus(SingletonMixin, metaclass=SingletonType):
    nseFetcher = nseStockDataFetcher()

    def __init__(self):
        super().__init__()

    @property
    def exchange(self):
        if "exchange" in self.attributes:
            return self.attributes["exchange"]
        else:
            return "^NSEI"

    @exchange.setter
    def exchange(self, exchangeKey):
        if self.exchange != exchangeKey:
            self.marketStatus = self.getMarketStatus(exchangeSymbol=exchangeKey)
        self.attributes["exchange"] = exchangeKey

    @property
    def marketStatus(self):
        if "marketStatus" in self.attributes:
            return self.attributes["marketStatus"]
        else:
            # self.attributes["lock"] = "" # We don't need threading lock here
            self.marketStatus = ""
            return self.marketStatus

    @marketStatus.setter
    def marketStatus(self, status):
        self.attributes["marketStatus"] = status

    def getMarketStatus(self, progress=None, task_id=0, exchangeSymbol="^NSEI", namedOnly=False):
        return "NA"
        lngStatus = ""
        try:
            # if not 'pytest' in sys.modules:
            suppressLogs = True
            if "PKDevTools_Default_Log_Level" in os.environ:
                suppressLogs = os.environ["PKDEVTOOLS_DEFAULT_LOG_LEVEL"] == str(log.logging.NOTSET)
            with SuppressOutput(suppress_stdout=suppressLogs, suppress_stderr=suppressLogs):
                if progress:
                    progress[task_id] = {"progress": 0, "total": 1}
                _, lngStatus, _ = (
                    "",
                    "TODO",
                    "",
                )  # MarketStatus.nseFetcher.capitalMarketStatus(exchange=exchangeSymbol)
                if exchangeSymbol in ["^NSEI", "^BSESN"] and not namedOnly:
                    _, bseStatus, _ = (
                        "",
                        "TODO",
                        "",
                    )  # MarketStatus.nseFetcher.capitalMarketStatus(exchange="^BSESN")
                    lngStatus = f"{lngStatus} | {bseStatus}"
            if progress:
                progress[task_id] = {"progress": 1, "total": 1}
        except KeyboardInterrupt:  # pragma: no cover
            raise KeyboardInterrupt
        except Exception as e:  # pragma: no cover
            default_logger().debug(e, exc_info=True)
            pass
        self.marketStatus = lngStatus
        return lngStatus

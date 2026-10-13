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


#!/usr/bin/python3
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

import json

from PKDevTools.classes.SuppressOutput import SuppressOutput
from pkscreener.classes.PKScheduler import PKScheduler
from pkscreener.classes.PKTask import PKTask


class PKDataService:
    def getSymbolsAndSectorInfo(self, configManager, stockCodes=None):
        from PKNSETools.PKCompanyGeneral import download, initialize

        if stockCodes is None:
            stockCodes = []
        stockDictList = []
        tasksList = []
        for symbol in stockCodes:
            fn_args = symbol
            task = PKTask(
                f"DataDownload-{symbol}", long_running_fn=download, long_running_fn_args=fn_args
            )
            task.userData = symbol
            tasksList.append(task)

        processedStocks = []
        if len(tasksList) > 0:
            # Suppress any multiprocessing errors/warnings
            with SuppressOutput(suppress_stderr=True, suppress_stdout=True):
                initialize()  # Let's get the cookies set-up right
                # We are setting maxWorkers to 1 here to avoid any
                # potential issues with the NSE website blocking
                # requests due to too many parallel requests.
                # This can be increased if you have a large
                # number of stocks and want faster downloads,
                # but be cautious about potential blocking.
                PKScheduler.scheduleTasks(
                    tasksList=tasksList,
                    label=f"Downloading latest symbol/sector info. (Total={len(stockCodes)} records in {len(tasksList)} batches){'Be Patient!' if len(stockCodes) > 2000 else ''}",
                    timeout=(
                        5 + 2.5 * configManager.longTimeout * 4
                    ),  # 5 seconds additional time for getting multiprocessing ready
                    minAcceptableCompletionPercentage=100,
                    submitTaskAsArgs=True,
                    showProgressBars=True,
                    maxWorkers=1,
                )
            for task in tasksList:
                if task.result is not None:
                    taskResult = json.loads(task.result)
                    if (
                        taskResult is not None
                        and isinstance(taskResult, dict)
                        and "info" in taskResult
                    ):
                        stockDictList.append(taskResult.get("info"))
                        processedStocks.append(task.userData)
        leftOutStocks = list(set(stockCodes) - set(processedStocks))
        # default_logger().debug(f"Attempted fresh download of {len(stockCodes)} stocks and downloaded {len(processedStocks)} stocks. {len(leftOutStocks)} stocks remaining.")
        return stockDictList, leftOutStocks

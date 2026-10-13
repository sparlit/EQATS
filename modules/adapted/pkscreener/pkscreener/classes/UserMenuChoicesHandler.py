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
import sys

import pkscreener.classes.ConfigManager as ConfigManager
import pkscreener.classes.Utility as Utility
from PKDevTools.classes.ColorText import colorText
from PKDevTools.classes.OutputControls import OutputControls
from pkscreener.classes import AssetsManager


class UserMenuChoicesHandler:
    configManager = ConfigManager.tools()
    configManager.getConfig(ConfigManager.parser)

    def getDownloadChoices(defaultAnswer=None):
        global userPassedArgs
        argsIntraday = userPassedArgs is not None and userPassedArgs.intraday is not None
        intradayConfig = UserMenuChoicesHandler.configManager.isIntradayConfig()
        intraday = intradayConfig or argsIntraday
        exists, cache_file = AssetsManager.PKAssetsManager.afterMarketStockDataExists(intraday)
        if exists:
            shouldReplace = AssetsManager.PKAssetsManager.promptFileExists(
                cache_file=cache_file, defaultAnswer=defaultAnswer
            )
            if shouldReplace == "N":
                OutputControls().printOutput(
                    cache_file
                    + colorText.END
                    + " already exists. Exiting as user chose not to replace it!"
                )
                sys.exit(0)
            else:
                pattern = f"{'intraday_' if intraday else ''}stock_data_*.pkl"
                UserMenuChoicesHandler.configManager.deleteFileWithPattern(pattern)
        return "X", 12, 0, {"0": "X", "1": "12", "2": "0"}

    def getTopLevelMenuChoices(startupoptions, testBuild, downloadOnly, defaultAnswer=None):
        global selectedChoice, userPassedArgs
        executeOption = None
        menuOption = None
        indexOption = None
        options = []
        if startupoptions is not None:
            options = startupoptions.split(":")
            menuOption = options[0] if len(options) >= 1 else None
            indexOption = options[1] if len(options) >= 2 else None
            executeOption = options[2] if len(options) >= 3 else None
        if testBuild:
            menuOption, indexOption, executeOption, selectedChoice = (
                UserMenuChoicesHandler.getTestBuildChoices(
                    indexOption=indexOption,
                    executeOption=executeOption,
                    menuOption=menuOption,
                )
            )
        elif downloadOnly:
            menuOption, indexOption, executeOption, selectedChoice = (
                UserMenuChoicesHandler.getDownloadChoices(defaultAnswer=defaultAnswer)
            )
            intraday = (
                userPassedArgs.intraday or UserMenuChoicesHandler.configManager.isIntradayConfig()
            )
            filePrefix = "INTRADAY_" if intraday else ""
            _, cache_file_name = AssetsManager.PKAssetsManager.afterMarketStockDataExists(intraday)
            Utility.tools.set_github_output(
                f"{filePrefix}DOWNLOAD_CACHE_FILE_NAME", cache_file_name
            )
        return options, menuOption, indexOption, executeOption

    def getTestBuildChoices(indexOption=None, executeOption=None, menuOption=None):
        if menuOption is not None:
            return (
                str(menuOption),
                indexOption if indexOption is not None else 1,
                executeOption if executeOption is not None else 0,
                {
                    "0": str(menuOption),
                    "1": (str(indexOption) if indexOption is not None else 1),
                    "2": (str(executeOption) if executeOption is not None else 0),
                },
            )
        return "X", 1, 0, {"0": "X", "1": "1", "2": "0"}

    def handleExitRequest(executeOption):
        if executeOption == "Z":
            input(colorText.FAIL + "  [+] Press <Enter> to Exit!" + colorText.END)
            sys.exit(0)

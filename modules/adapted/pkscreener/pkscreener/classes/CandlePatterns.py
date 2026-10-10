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

from PKDevTools.classes.ColorText import colorText
from pkscreener.classes.Pktalib import pktalib

# from PKDevTools.classes.log import measure_time


class CandlePatterns:
    reversalPatternsBullish = [
        "Morning Star",
        "Morning Doji Star",
        "3 Inside Up",
        "Hammer",
        "3 White Soldiers",
        "Bullish Engulfing",
        "Dragonfly Doji",
        "Supply Drought",
        "Demand Rise",
        "Cup and Handle",
    ]
    reversalPatternsBearish = [
        "Evening Star",
        "Evening Doji Star",
        "3 Inside Down",
        "Inverted Hammer",
        "Hanging Man",
        "3 Black Crows",
        "Bearish Engulfing",
        "Shooting Star",
        "Gravestone Doji",
    ]

    def __init__(self):
        pass

    def findCurrentSavedValue(self, screenDict, saveDict, key):
        existingScreen = screenDict.get(key)
        existingSave = saveDict.get(key)
        existingScreen = (
            f"{existingScreen}, "
            if (existingScreen is not None and len(existingScreen) > 0)
            else ""
        )
        existingSave = (
            f"{existingSave}, " if (existingSave is not None and len(existingSave) > 0) else ""
        )
        return existingScreen, existingSave

    # @measure_time
    # Find candle-stick patterns
    # Arrange if statements with max priority from top to bottom
    def findPattern(self, processedData, dict, saveDict, filterPattern=None):
        data = processedData.head(4)
        data = data[::-1]  # Reverse the dataframe so that its the oldest date first
        hasCandleStickPattern = False
        if "Pattern" not in saveDict:
            saveDict["Pattern"] = ""
            dict["Pattern"] = ""
        # Only 'doji' and 'inside' is internally implemented by pandas_ta_classic.
        # Otherwise, for the rest of the candle patterns, they also need
        # TA-Lib.
        check = pktalib.CDLDOJI(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "Doji"
                + colorText.END
            )
            saveDict["Pattern"] = self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Doji"
            hasCandleStickPattern = True

        check = pktalib.CDLMORNINGSTAR(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "Morning Star"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Morning Star"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLCUPANDHANDLE(
            processedData["open"],
            processedData["high"],
            processedData["low"],
            processedData["close"],
        )
        if check:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "Cup and Handle"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Cup and Handle"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLMORNINGDOJISTAR(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "Morning Doji Star"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Morning Doji Star"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLEVENINGSTAR(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.FAIL
                + "Evening Star"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Evening Star"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLEVENINGDOJISTAR(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.FAIL
                + "Evening Doji Star"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Evening Doji Star"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLLADDERBOTTOM(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "Bullish Ladder Bottom"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1]
                    + "Bullish Ladder Bottom"
                )
            else:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.FAIL
                    + "Bearish Ladder Bottom"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1]
                    + "Bearish Ladder Bottom"
                )
            hasCandleStickPattern = True

        check = pktalib.CDL3LINESTRIKE(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "3 Line Strike"
                    + colorText.END
                )
            else:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.FAIL
                    + "3 Line Strike"
                    + colorText.END
                )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "3 Line Strike"
            )
            hasCandleStickPattern = True

        check = pktalib.CDL3BLACKCROWS(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.FAIL
                + "3 Black Crows"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "3 Black Crows"
            )
            hasCandleStickPattern = True

        check = pktalib.CDL3INSIDE(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "3 Inside Up"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "3 Outside Up"
                )
            else:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.FAIL
                    + "3 Inside Down"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "3 Inside Down"
                )
            hasCandleStickPattern = True

        check = pktalib.CDL3OUTSIDE(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "3 Outside Up"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "3 Outside Up"
                )
            else:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.FAIL
                    + "3 Outside Down"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "3 Outside Down"
                )
            hasCandleStickPattern = True

        check = pktalib.CDL3WHITESOLDIERS(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "3 White Soldiers"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "3 White Soldiers"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLHARAMI(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "Bullish Harami"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Bullish Harami"
                )
            else:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.FAIL
                    + "Bearish Harami"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Bearish Harami"
                )
            hasCandleStickPattern = True

        check = pktalib.CDLHARAMICROSS(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "Bullish Harami Cross"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1]
                    + "Bullish Harami Cross"
                )
            else:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.FAIL
                    + "Bearish Harami Cross"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1]
                    + "Bearish Harami Cross"
                )
            hasCandleStickPattern = True

        check = pktalib.CDLMARUBOZU(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "Bullish Marubozu"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Bullish Marubozu"
                )
            else:
                dict["Pattern"] = colorText.FAIL + "Bearish Marubozu" + colorText.END
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Bearish Marubozu"
                )
            hasCandleStickPattern = True

        check = pktalib.CDLHANGINGMAN(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.FAIL
                + "Hanging Man"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Hanging Man"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLHAMMER(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "Hammer"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Hammer"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLINVERTEDHAMMER(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "Inverted Hammer"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Inverted Hammer"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLSHOOTINGSTAR(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.FAIL
                + "Shooting Star"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Shooting Star"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLDRAGONFLYDOJI(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.GREEN
                + "Dragonfly Doji"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Dragonfly Doji"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLGRAVESTONEDOJI(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            dict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                + colorText.FAIL
                + "Gravestone Doji"
                + colorText.END
            )
            saveDict["Pattern"] = (
                self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Gravestone Doji"
            )
            hasCandleStickPattern = True

        check = pktalib.CDLENGULFING(data["open"], data["high"], data["low"], data["close"])
        if check is not None and check.tail(1).item() != 0:
            if check.tail(1).item() > 0:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.GREEN
                    + "Bullish Engulfing"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Bullish Engulfing"
                )
            else:
                dict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[0]
                    + colorText.FAIL
                    + "Bearish Engulfing"
                    + colorText.END
                )
                saveDict["Pattern"] = (
                    self.findCurrentSavedValue(dict, saveDict, "Pattern")[1] + "Bearish Engulfing"
                )
            hasCandleStickPattern = True
        if hasCandleStickPattern:
            return (
                filterPattern in saveDict["Pattern"]
                if (filterPattern is not None and filterPattern != "No Filter")
                else hasCandleStickPattern
            )
        return False

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
import sys

from PKDevTools.classes.ColorText import colorText
from PKDevTools.classes.OutputControls import OutputControls


class PKDemoHandler:
    @classmethod
    def demoForMenu(self, menu):
        # Default: View Various PKScreener Subscription Options
        asciinemaLink = "https://asciinema.org/a/EHYIQBbCP8CAJIAFjWaFGkEEX"
        match menu.menuKey:
            case "F":
                # F > Find a stock in scanners
                asciinemaLink = "https://asciinema.org/a/7TA8H8pq94YmTqsrVvtLCpPel"
            case "M":
                asciinemaLink = "https://asciinema.org/a/NKBXhxc2iWbpxcll35JqwfpuQ"
            case _:  # P_1_1
                asciinemaLink = "https://asciinema.org/a/b31Tp78QLSzZcxcxCzH7Rljog"

        OutputControls().printOutput(
            f"\n[+] {colorText.GREEN}Please check this out in your browser:{colorText.END}\n\n[+] {colorText.FAIL}\x1b[97m\x1b]8;;{asciinemaLink}\x1b\\{asciinemaLink}\x1b]8;;\x1b\\\x1b[0m{colorText.END}\n"
        )
        input("Press any key to exit...")
        sys.exit(0)

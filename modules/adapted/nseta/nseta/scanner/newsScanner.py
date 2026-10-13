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
from nseta.archives.archiver import *
from nseta.common.log import tracelog
from nseta.common.tradingtime import IST_datetime
from nseta.scanner.baseScanner import baseScanner

__all__ = ["newsScanner"]


class newsScanner(baseScanner):
    def __init__(self, scanner_type, stocks=None, indicator=None, background=False):
        if stocks is None:
            stocks = []
        super().__init__(scanner_type, stocks, indicator=indicator, background=background)
        self.response_type = ResponseType.Unknown
        self.archiver = archiver()

    @tracelog
    def scan(self, option=None, analyse=False):
        self.sortAscending = True
        super().scan(option="h" if option is None else option, analyse=analyse)

    @tracelog
    def flush_signals(self, signaldf):
        if self.option is not None and len(self.option) > 0:
            signaldf = signaldf.sort_values(by=self.option, ascending=self.sortAscending)
        user_signaldf = self.configure_user_display(signaldf, columns=self.signal_columns)
        user_signaldf.drop(["h"], axis=1, inplace=True)
        df = self.left_align(user_signaldf)
        print(f"\nAs of {IST_datetime()}, {self.scanner_type.name}:\n{df.to_string(index=False)}\n")
        return True

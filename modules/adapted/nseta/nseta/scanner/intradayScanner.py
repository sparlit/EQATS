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
from nseta.resources.resources import resources
from nseta.scanner.baseScanner import baseScanner

__all__ = ["intradayScanner"]


class intradayScanner(baseScanner):
    def __init__(self, scanner_type, stocks=None, indicator=None, background=False):
        if stocks is None:
            stocks = []
        super().__init__(scanner_type, stocks, indicator, background)
        self.response_type = ResponseType.Intraday
        self.archiver = archiver()

    @tracelog
    def scan(self, option=None, periodicity="1", analyse=False):
        self.signal_columns = resources.scanner().intraday_scan_columns
        self.sortAscending = False
        super().scan(
            option="Cnt_Cdl" if option is None else option, periodicity=periodicity, analyse=analyse
        )

    def scan_background(
        self,
        scannerinstance,
        terminate_after_iter=0,
        wait_time=resources.scanner().background_scan_frequency_intraday,
    ):
        return super().scan_background(
            scannerinstance, terminate_after_iter=terminate_after_iter, wait_time=wait_time
        )

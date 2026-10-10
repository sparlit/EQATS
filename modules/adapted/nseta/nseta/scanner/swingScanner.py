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
from nseta.common.log import default_logger, tracelog
from nseta.resources.resources import resources
from nseta.scanner.baseScanner import baseScanner
from nseta.scanner.baseStockScanner import ScannerType
from nseta.scanner.topPickScanner import topPickScanner

__all__ = ["swingScanner"]


class swingScanner(baseScanner):
    def __init__(self, scanner_type, stocks=None, indicator=None, background=False):
        if stocks is None:
            stocks = []
        super().__init__(scanner_type, stocks, indicator, background)
        self.response_type = ResponseType.History
        self.archiver = archiver()

    @tracelog
    def scan(self, option=None, analyse=False):
        self.signal_columns = resources.scanner().swing_scan_columns
        self.sortAscending = True
        super().scan(option="Symbol", analyse=analyse)

    @tracelog
    def scan_background(self, scannerinstance, terminate_after_iter=0, wait_time=0):
        default_logger().debug(
            "Background running not supported yet. Stay tuned. Executing just once."
        )
        self.background = False
        self.scan(self.option)
        return 0

    def scan_analysis(self, analysis_df):
        scanner = topPickScanner(
            scanner_type=ScannerType.TopPick,
            stocks=analysis_df.loc[:, "Symbol"].tolist(),
            indicator="macd",
            background=self.background,
        )
        scanner.clear_cache(True, force_clear=False)
        scanner.scan(option=None)

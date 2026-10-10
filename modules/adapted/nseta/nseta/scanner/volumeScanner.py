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
from nseta.resources.resources import resources
from nseta.scanner.baseScanner import baseScanner
from nseta.scanner.baseStockScanner import ScannerType
from nseta.scanner.topPickScanner import topPickScanner

__all__ = ["volumeScanner"]


class volumeScanner(baseScanner):
    def __init__(self, scanner_type, stocks=None, indicator=None, background=False):
        if stocks is None:
            stocks = []
        super().__init__(scanner_type, stocks, indicator, background)
        self.response_type = ResponseType.Volume
        self.archiver = archiver()

    @tracelog
    def scan(self, option=None, analyse=False):
        self.signal_columns = resources.scanner().volume_scan_columns
        self.sortAscending = False
        super().scan(option="TDYVol(%)" if option is None else option, analyse=analyse)

    def scan_background(
        self,
        scannerinstance,
        terminate_after_iter=0,
        wait_time=resources.scanner().background_scan_frequency_intraday,
    ):
        return super().scan_background(
            scannerinstance, terminate_after_iter=terminate_after_iter, wait_time=wait_time
        )

    def scan_results(self, df, signaldf, should_cache=True):
        if signaldf is not None and len(signaldf) > 0:
            str_signal_stocks_list = "{}".format(signaldf.loc[:, "Symbol"].tolist())
            should_enum = resources.scanner().enumerate_volume_scan_signals
            csv_signals = (
                str_signal_stocks_list.replace("[", "")
                .replace("]", "")
                .replace("'", "")
                .replace(" ", "")
                if should_enum
                else ""
            )
            if should_enum:
                print(f"\nAs of {IST_datetime()}, volume Signals: {csv_signals}\n")
        super().scan_results(df, signaldf, should_cache)

    def scan_analysis(self, analysis_df):
        scanner = topPickScanner(
            scanner_type=ScannerType.TopPick,
            stocks=analysis_df.loc[:, "Symbol"].tolist(),
            indicator="macd",
            background=self.background,
        )
        scanner.clear_cache(True, force_clear=False)
        scanner.scan(option="")

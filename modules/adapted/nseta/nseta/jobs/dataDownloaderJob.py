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
import datetime
import inspect
import os
import threading
from time import sleep, time

from nseta.archives.archiver import *
from nseta.common.commons import last_x_days_timedelta
from nseta.common.history import historicaldata
from nseta.common.log import *
from nseta.common.multithreadedScanner import multithreaded_scan
from nseta.common.tradingtime import *
from nseta.live.live import get_live_quote
from nseta.resources.resources import *
from nseta.scanner.baseStockScanner import ScannerType

__all__ = ["dataDownloaderJob"]


class dataDownloaderJob:
    def __init__(self):
        self._downloaders = {
            (ScannerType.Intraday).name: dataDownloaderChild(ScannerType.Intraday),
            (ScannerType.Swing).name: dataDownloaderChild(ScannerType.Swing),
            (ScannerType.Volume).name: dataDownloaderChild(ScannerType.Volume),
            (ScannerType.TopPick).name: dataDownloaderChild(ScannerType.TopPick),
            (ScannerType.Quote).name: dataDownloaderChild(ScannerType.Quote),
        }
        # (ScannerType.Live).name:dataDownloaderChild(ScannerType.Live),
        # (ScannerType.News).name:dataDownloaderChild(ScannerType.News)}

    @property
    def downloaders(self):
        return self._downloaders

    def start(self):
        default_logger().debug("Starting job for downloading data")
        frame = inspect.currentframe()
        args, _, _, kwargs = inspect.getargvalues(frame)
        del kwargs["frame"]
        del kwargs["self"]
        kwargs1 = dict(kwargs)
        kwargs1["terminate_after_iter"] = 0
        wait_time = resources().jobs().data_scan_frequency
        kwargs1["wait_time"] = wait_time
        threads = []
        for key in self.downloaders:
            downloaderChild = self.downloaders[key]
            downloaderChild.shouldRun = True
            b = threading.Thread(
                name=f"download_background_{(downloaderChild.scanner_type).name}",
                target=downloaderChild.download_background,
                args=[kwargs1],
                daemon=True,
            )
            b.start()
            threads.append(b)
        for t in threads:
            t.join()

    def stop(self):
        default_logger().debug("Stopping job for downloading data")
        for key in self.downloaders:
            downloaderChild = self.downloaders[key]
            downloaderChild.shouldRun = False


class dataDownloaderChild:
    def __init__(self, scanner_type=ScannerType.Unknown):
        self._total_counter = 0
        self._periodicity = 2 if scanner_type == ScannerType.TopPick else 1
        self._time_spent = 0
        self._scanner_type = scanner_type
        self._responseTypeMap = {
            (ScannerType.Intraday).name: ResponseType.Intraday,
            (ScannerType.Swing).name: ResponseType.History,
            (ScannerType.Volume).name: ResponseType.Volume,
            (ScannerType.TopPick).name: ResponseType.Intraday,
            (ScannerType.Quote).name: ResponseType.Volume,
        }

    @property
    def time_spent(self):
        return self._time_spent

    @property
    def response_type(self):
        return self._responseTypeMap[(self.scanner_type).name]

    @property
    def quote_keys(self):
        return [
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
    def start_date(self):
        sd = datetime.datetime.now()
        if self.scanner_type == ScannerType.Swing:
            return datetime.datetime.now() - datetime.timedelta(
                days=resources().jobs().swing_scan_period
            )
        elif self.scanner_type == ScannerType.Volume:
            return datetime.datetime.now() - datetime.timedelta(days=last_x_days_timedelta())
        return sd

    @time_spent.setter
    def time_spent(self, value):
        self._time_spent = value

    @property
    def periodicity(self):
        return self._periodicity

    @periodicity.setter
    def periodicity(self, value):
        self._periodicity = value

    @property
    def total_counter(self):
        return self._total_counter

    @total_counter.setter
    def total_counter(self, value):
        self._total_counter = value

    @property
    def scanner_type(self):
        return self._scanner_type

    @property
    def runnerFilePath(self):
        return os.path.join(
            resources.default().user_data_dir, f"DO_NOT_DELETE_{(self.scanner_type).name}runner.txt"
        )

    @property
    def shouldRun(self):
        run = os.path.exists(self.runnerFilePath)
        return run

    @property
    def max_iterations(self):
        max_iter = 0
        if self.scanner_type == ScannerType.Intraday:
            if not current_datetime_in_ist_trading_time_range():
                default_logger().debug(
                    f"Running the {self.scanner_type.name} scan for one last time because it is outside the trading hours"
                )
                max_iter = 1
        else:
            max_iter = 1
        return max_iter

    @shouldRun.setter
    def shouldRun(self, value):
        self.flag_file(value)

    def flag_file(self, shouldCreate):
        runnerTmpFile = self.runnerFilePath
        if not os.path.exists(runnerTmpFile):
            if shouldCreate:
                # Creates a new file
                with open(runnerTmpFile, "w"):
                    pass
        elif not shouldCreate:
            os.remove(runnerTmpFile)

    @tracelog
    def stocks_list(self, stocks=None):
        if stocks is None:
            stocks = []
        global __scan_counter__
        __scan_counter__ = 0
        # If stocks array is empty, pull stock list from stocks.txt or userstocks.txt file
        stocks = stocks if stocks is not None and len(stocks) > 0 else resources.default().stocks
        self.total_counter = len(stocks)
        return stocks

    @tracelog
    def scan(self, stocks=None):
        if stocks is None:
            stocks = []
        start_time = time()
        stocks = self.stocks_list(stocks)
        frame = inspect.currentframe()
        _, _, _, kwargs = inspect.getargvalues(frame)
        del kwargs["frame"]
        del kwargs["self"]
        kwargs["scanner_type"] = self.scanner_type
        kwargs["callbackMethod"] = self.multithreadedScanner_callback
        kwargs["items"] = stocks
        kwargs["max_per_thread"] = 3
        multithreaded_scan(**kwargs)
        end_time = time()
        time_spent = end_time - start_time
        self.time_spent += time_spent

    def multithreadedScanner_callback(self, **kwargs):
        kwargs["scanner_type"]
        del kwargs["scanner_type"]
        self.scan_quanta(**kwargs)
        return [None, None]

    @tracelog
    def scan_quanta(self, **kwargs):
        stocks = kwargs["items"]
        for symbol in stocks:
            try:
                arc = archiver()
                symbol_format = self.get_archived_filename(symbol)
                path = os.path.join(arc.get_directory(self.response_type), symbol_format.upper())
                arc.remove_cached_file(path, force_clear=True)
                msg = f"( {self.scanner_type.name} ) : {symbol}"
                set_cursor()
                print(msg)
                if self.scanner_type == ScannerType.Quote:
                    self.ohlcv_quote(symbol)
                else:
                    self.ohlc_history(symbol)
            except Exception as e:
                default_logger().debug(
                    f"Exception encountered for {symbol} during {self.scanner_type.name} downloafd job."
                )
                default_logger().debug(e, exc_info=True)

    @tracelog
    def download_background(self, args):
        iteration = 0
        default_logger().debug(args)
        frame = inspect.currentframe()
        args, _, _, main_args = inspect.getargvalues(frame)
        default_logger().debug(main_args)
        kwargs = main_args["args"]
        default_logger().debug(kwargs)
        terminate_after_iter = kwargs["terminate_after_iter"]
        wait_time = kwargs["wait_time"]
        iteration = 0
        while self.shouldRun:
            iteration = iteration + 1
            try:
                self.scan()
            except Exception as e:
                default_logger().debug(e, exc_info=True)
            set_cursor()
            print(
                "Last {} download job was run at:{} ( {:.2f}s )".format(
                    self.scanner_type.name,
                    datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
                    self.time_spent,
                )
            )
            terminate_after_iter = self.max_iterations
            if terminate_after_iter > 0 and iteration >= terminate_after_iter:
                self.shouldRun = False
                break
            sleep(wait_time)
        default_logger().debug(f"Finished all iterations of download job {self.scanner_type.name}.")

    @tracelog
    def ohlc_history(self, symbol):
        df = None
        try:
            historyinstance = historicaldata()
            archiver()
            df = historyinstance.daily_ohlc_history(
                symbol,
                start=self.start_date,
                end=datetime.datetime.now(),
                intraday=(self.scanner_type in [ScannerType.Intraday, ScannerType.TopPick]),
                type=self.response_type,
                periodicity=self.periodicity,
            )
        except Exception as e:
            default_logger().debug(e, exc_info=True)
            return None
        return df

    @tracelog
    def ohlcv_quote(self, symbol):
        try:
            get_live_quote(symbol, keys=self.quote_keys)
        except Exception as e:
            default_logger().debug(e, exc_info=True)

    def get_archived_filename(self, symbol):
        if self.response_type == ResponseType.Intraday:
            return f"{symbol}_{self.periodicity}"
        elif self.scanner_type == ScannerType.Quote:
            return f"{symbol}_live_quote"
        else:
            return "{}_{}_{}".format(
                symbol,
                self.start_date.strftime("%d-%m-%Y"),
                datetime.datetime.now().strftime("%d-%m-%Y"),
            )

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
import sys

import pandas as pd
from nseta.archives.archiver import *
from nseta.common.history import historicaldata
from nseta.common.log import default_logger, tracelog
from nseta.common.ti import ti
from nseta.scanner.baseStockScanner import baseStockScanner
from nseta.scanner.intradayStockScanner import INTRADAY_KEYS_MAPPING

__all__ = ["swingStockScanner"]

SWING_PERIOD = 90


class swingStockScanner(baseStockScanner):
    def __init__(self, indicator="all"):
        super().__init__(indicator=indicator)

    @tracelog
    def scan_quanta(self, **kwargs):
        stocks = kwargs["items"]
        frames = []
        signalframes = []
        df = None
        signaldf = None
        tiinstance = ti()
        historyinstance = historicaldata()
        tailed_df = None
        # Time frame you want to pull data from
        start_date = datetime.datetime.now() - datetime.timedelta(days=SWING_PERIOD)
        end_date = datetime.datetime.now()
        for symbol in stocks:
            try:
                self.update_progress(symbol)
                df = historyinstance.daily_ohlc_history(
                    symbol, start_date, end_date, type=ResponseType.History
                )
                if df is not None and len(df) > 0:
                    df = tiinstance.update_ti(
                        df, rsi=True, mom=True, bbands=True, obv=True, macd=True, ema=True, atr=True
                    )
                    df = df.sort_values(by="Date", ascending=True)
                    default_logger().debug(df.to_string(index=False))
                    for key in df:
                        # Symbol Series       Date  Prev Close     Open     High      Low     Last    Close     VWAP    Volume      Turnover  Trades  Deliverable Volume  %Deliverable
                        if key not in INTRADAY_KEYS_MAPPING:
                            df.drop([key], axis=1, inplace=True)
                        elif key in INTRADAY_KEYS_MAPPING:
                            searchkey = INTRADAY_KEYS_MAPPING[key]
                            if key != searchkey:
                                df[searchkey] = df[key]
                                df.drop([key], axis=1, inplace=True)
                    tailed_df = df.tail(1)
                    default_logger().debug(tailed_df.to_string(index=False))
                    frames.append(tailed_df)
                    signalframes, df = self.update_signals(signalframes, tailed_df, df)
            except Exception as e:
                default_logger().debug("Exception encountered for " + symbol)
                default_logger().debug(e, exc_info=True)
            except SystemExit:
                sys.exit(1)
        if len(frames) > 0:
            tailed_df = pd.concat(frames)
        if len(signalframes) > 0:
            signaldf = pd.concat(signalframes)
        return [tailed_df, signaldf]

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
import pandas as pd
from bs4 import BeautifulSoup
from nseta.common.commons import ParseNews
from nseta.common.log import default_logger, tracelog
from nseta.common.urls import TICKERTAPE_NEWS_URL
from nseta.scanner.baseStockScanner import baseStockScanner

__all__ = ["stockNewsScanner"]


class stockNewsScanner(baseStockScanner):
    def __init__(self, indicator="all"):
        super().__init__(indicator=indicator)

    @tracelog
    def scan_quanta(self, **kwargs):
        stocks = kwargs["items"]
        signalframes = []
        df = None
        signaldf = None
        pd.set_option("mode.chained_assignment", None)
        for symbol in stocks:
            try:
                self.update_progress(symbol)
                resp = TICKERTAPE_NEWS_URL(symbol.upper())
                default_logger().debug(f"News Response:\n{resp.text}\n")
                bs = BeautifulSoup(resp.text, "lxml")
                news = ParseNews(soup=bs)
                news.parse_news(symbol.upper())
                df = pd.DataFrame(
                    news.news_list, columns=["Symbol", "h", "Hours_ago", "Publisher", "Headline"]
                )
                if df is not None and len(df) > 0:
                    signalframes.append(df)
                    default_logger().debug(df.to_string(index=False))
            except Exception as e:
                default_logger().debug("Exception encountered for " + symbol)
                default_logger().debug(e, exc_info=True)
            except SystemExit:
                sys.exit(1)
        if len(signalframes) > 0:
            signaldf = pd.concat(signalframes)
        return [df, signaldf]

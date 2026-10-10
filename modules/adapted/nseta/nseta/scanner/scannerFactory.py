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
from nseta.scanner.intradayScanner import intradayScanner
from nseta.scanner.liveScanner import liveScanner
from nseta.scanner.newsScanner import newsScanner
from nseta.scanner.quoteScanner import quoteScanner
from nseta.scanner.stockscanner import ScannerType
from nseta.scanner.swingScanner import swingScanner
from nseta.scanner.topPickScanner import topPickScanner
from nseta.scanner.volumeScanner import volumeScanner

__all__ = ["scannerFactory"]


class scannerFactory:
    @staticmethod
    def scanner(scanner_type=ScannerType.Unknown, stocks=None, indicator=None, background=False):
        if stocks is None:
            stocks = []
        scanner_dict = {
            (ScannerType.Intraday).name: intradayScanner,
            (ScannerType.Live).name: liveScanner,
            (ScannerType.Quote).name: quoteScanner,
            (ScannerType.Swing).name: swingScanner,
            (ScannerType.Volume).name: volumeScanner,
            (ScannerType.TopPick).name: topPickScanner,
            (ScannerType.News).name: newsScanner,
        }
        return scanner_dict[scanner_type.name](
            scanner_type=scanner_type, stocks=stocks, indicator=indicator, background=background
        )

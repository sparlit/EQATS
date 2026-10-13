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
from nseta.scanner.baseStockScanner import TECH_INDICATOR_KEYS, ScannerType, baseStockScanner
from nseta.scanner.intradayStockScanner import intradayStockScanner
from nseta.scanner.liveStockScanner import liveStockScanner
from nseta.scanner.stockNewsScanner import stockNewsScanner
from nseta.scanner.swingStockScanner import swingStockScanner
from nseta.scanner.topPickStockScanner import topPickStockScanner
from nseta.scanner.volumeStockScanner import volumeStockScanner

__all__ = ["scanner", "TECH_INDICATOR_KEYS", "ScannerType"]

# PIVOT_KEYS =['PP', 'R1','S1','R2','S2','R3','S3']


class scanner(baseStockScanner):
    def __init__(self, indicator="all"):
        super().__init__(indicator=indicator)

    def get_instance(self, scanner_type=ScannerType.Unknown):
        if scanner_type.name in self.instancedict:
            return self.instancedict[scanner_type.name]
        else:
            instance = scanner.stockScanner(scanner_type=scanner_type, indicator=self.indicator)
            instance.scanner_type = scanner_type
            self.instancedict[scanner_type.name] = instance
            return instance

    @staticmethod
    def stockScanner(scanner_type=ScannerType.Unknown, indicator=None):
        scanner_dict = {
            (ScannerType.Intraday).name: intradayStockScanner,
            (ScannerType.Live).name: liveStockScanner,
            (ScannerType.Swing).name: swingStockScanner,
            (ScannerType.Volume).name: volumeStockScanner,
            (ScannerType.TopPick).name: topPickStockScanner,
            (ScannerType.News).name: stockNewsScanner,
        }
        return scanner_dict[scanner_type.name](indicator=indicator)

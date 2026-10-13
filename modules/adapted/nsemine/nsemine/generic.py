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


import traceback
from datetime import datetime

from nsemine import live


class NSEStock:
    """
    This class provides methods to fetch various data related to a specific stock.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.quote_data = self.get_quotes()
        if self.quote_data:
            self.name = self.quote_data.get("name")
            self.industry = self.quote_data.get("industry")
            self.derivatives = self.quote_data.get("derivatives")
            self.series = self.quote_data.get("series")
            self.date_of_listing = self.quote_data.get("date_of_listing")
            self.last_updated = self.quote_data.get("last_updated")
            self.trading_status = self.quote_data.get("trading_status")
            self.number_of_shares = self.quote_data.get("number_of_shares")
            self.face_value = self.quote_data.get("face_value")
            self.indices = self.quote_data.get("indices")
        else:
            print(f"The Symbol: {self.symbol} is not properly initialized.")

    def get_quotes(self, raw: bool = False) -> dict | None:
        """
        Fetches the live quote of the stock symbol.
        Args:
            raw (bool): Pass True, if you need the raw data without processing. Deafult is False.
        Returns:
            quote_data (dict, None) : Returns the raw data as dictionary if raw=True. By default, it returns cleaned and processed dictionary.
            Returns None if any error occurred.
        """
        try:
            return live.get_stock_live_quotes(stock_symbol=self.symbol, raw=raw)
        except Exception as e:
            print(f"ERROR! - {e}\n")
            traceback.print_exc()

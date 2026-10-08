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


"""
Firstock-specific exchange mapping and capability registry
"""


class FirstockExchangeMapper:
    """Maps between standard exchange codes and Firstock-specific codes"""

    # Mapping from standard codes to Firstock exchange codes
    EXCHANGE_MAP = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NFO",
        "CDS": "CDS",
        "MCX": "MCX",
        "BFO": "BFO",
        "NSE_INDEX": "NSE",  # NSE indices use NSE exchange in Firstock
    }

    # Reverse mapping
    REVERSE_MAP = {v: k for k, v in EXCHANGE_MAP.items()}

    @classmethod
    def get_firstock_exchange(cls, standard_exchange: str) -> str:
        """
        Convert standard exchange code to Firstock-specific code

        Args:
            standard_exchange: Standard exchange code (e.g., 'NSE')

        Returns:
            str: Firstock exchange code
        """
        return cls.EXCHANGE_MAP.get(standard_exchange, standard_exchange)

    @classmethod
    def get_standard_exchange(cls, firstock_exchange: str) -> str:
        """
        Convert Firstock exchange code to standard code

        Args:
            firstock_exchange: Firstock exchange code

        Returns:
            str: Standard exchange code
        """
        return cls.REVERSE_MAP.get(firstock_exchange, firstock_exchange)

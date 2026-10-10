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


import logging

from kiteconnect import KiteConnect

log = logging.getLogger(__name__)


class KiteConnectionManager:
    __kite_client = None

    def __init__(self, secrets):
        log.info("Creating kite client")
        kite_client = KiteConnect(api_key=secrets["api_key"])
        kite_client.set_access_token(secrets["access_token"])
        KiteConnectionManager.__kite_client = kite_client
        self.secrets = secrets

    @staticmethod
    def get_kite_client(secrets):
        if not KiteConnectionManager.__kite_client:
            KiteConnectionManager(secrets)
        return KiteConnectionManager.__kite_client

    @staticmethod
    def check_connection():
        KiteConnectionManager.__kite_client.profile()


class KiteConnector:
    def __init__(self, secrets: dict) -> None:
        self.kite_client = KiteConnectionManager.get_kite_client(secrets)

    def get_ltp(self, trading_symbols: list[str]) -> dict[str, dict[str, float]]:
        """
        :param trading_symbols: list of trading symbols of format exchange:trading_symbol e.g. NSE:ACC
        :return: map of trading symbol to the ltp quote e.g. {'NSE:ACC': {'instrument_token': 5633, 'last_price': 1880.4}}
        """
        return self.kite_client.ltp(trading_symbols)

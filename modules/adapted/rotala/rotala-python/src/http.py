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


from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


class HttpClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.backtest_id = None

        s = Session()
        retries = Retry(
            total=3,
            backoff_factor=0.1,
            status_forcelist=[502, 503, 504],
            allowed_methods={"POST"},
        )
        s.mount("https://", HTTPAdapter(max_retries=retries))
        self.s = s

    def init(self, start_date, end_date, frequency):
        val = f'{{"start_date": {start_date}, "end_date": {end_date}, "frequency": {frequency}}}'
        r = self.s.post(
            f"{self.base_url}/init",
            data=val,
            headers={"Content-type": "application/json"},
        )
        json_response = r.json()
        self.backtest_id = int(json_response["backtest_id"])
        return json_response

    def tick(self):
        if self.backtest_id is None:
            msg = "Called before init"
            raise ValueError(msg)

        r = self.s.get(f"{self.base_url}/backtest/{self.backtest_id}/tick")
        return r.json()

    def insert_orders(self, orders):
        if self.backtest_id is None:
            msg = "Called before init"
            raise ValueError(msg)

        serialized_orders_str = ",".join([o.serialize() for o in orders])
        val = f'{{"orders": [{serialized_orders_str}]}}'
        r = self.s.post(
            f"{self.base_url}/backtest/{self.backtest_id}/insert_orders",
            data=val,
            headers={"Content-type": "application/json"},
        )
        return r.json()

    def info(self):
        if self.backtest_id is None:
            msg = "Called before init"
            raise ValueError(msg)

        r = self.s.get(f"{self.base_url}/backtest/{self.backtest_id}/info")
        return r.json()

    def dataset_info(self):
        r = self.s.get(f"{self.base_url}/dataset/info")
        return r.json()

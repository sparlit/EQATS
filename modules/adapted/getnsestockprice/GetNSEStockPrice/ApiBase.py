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
    Base class for stock syncing API libraries
    To be inheritted by any library implemented in apis directory
    All methods are meant to be overridden by individual API libraries

    License : GNU GPLv2
    Author : Rajaram Srinivasan
    Initial Commit : May 2016
"""


class ApiBase:
    url_endpoint = None
    batch_size = 20  # No. of scrips to pass in a single API call
    url_params = None
    method = "GET"

    def get_data(self, scrips):
        """
        Attempts to get data from corresponding API. Uses other
        helper methods in the same class. Takes care of batching
        the API calls using self.batch_size
        """
        current_head = 0
        total_scrips = len(scrips)
        responses = []
        while current_head <= total_scrips:
            responses.append(
                self.make_request(scrips[current_head : current_head + self.batch_size])
            )
            current_head += self.batch_size
        return self.process_response(responses)

    def make_request(self, scrips):
        """
        Builds the final URL request to make with GET and POST params
        if any
        Input : List of scrips whose API data is to be obtained
        Output : response of requests.get/put/post library
        """
        raise Exception("To be implemented by inherited classes")

    def process_response(self, text_responses):
        """
        Processes API response to return dict of dict with
        scrip data. See Output for output format
        Input : List of requests.get/put/post
        Output:
                {'scrip1': {'price':123,
                            'volume':123,
                            'timestamp':Stringized time with Tz}
                }
        """
        raise Exception("To be implemented by inherited classes")

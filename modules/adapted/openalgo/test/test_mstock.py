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


import os
import unittest

from dotenv import load_dotenv
from openalgo import api as OAClient

# Load environment variables from .env file
load_dotenv()


class TestMstockBroker(unittest.TestCase):
    def setUp(self):
        """Set up for the test case."""
        # The test assumes that the OpenAlgo server is running and
        # the user is already logged into the mstock broker.
        self.api_key = os.getenv(
            "OPENALGO_API_KEY", "3bb8d260915ff680a7258108c0483b9eb7675ced31309a36f5846366943ee9fa"
        )
        self.client = OAClient(api_key=self.api_key, host="http://127.0.0.1:5000")

    def test_place_order(self):
        """Test placing a simple order."""
        # This test requires an active mstock session in the OpenAlgo server
        order_response = self.client.placeorder(
            strategy="TEST",
            symbol="TCS",
            exchange="NSE",
            price_type="MARKET",
            product="MIS",
            action="BUY",
            quantity=1,
        )
        self.assertEqual(order_response.get("status"), "success")
        self.assertIn("orderid", order_response)

    def test_get_positions(self):
        """Test retrieving positions."""
        positions_response = self.client.positionbook()
        self.assertEqual(positions_response.get("status"), "success")

    def test_get_holdings(self):
        """Test retrieving holdings."""
        holdings_response = self.client.holdings()
        self.assertEqual(holdings_response.get("status"), "success")

    def test_get_funds(self):
        """Test retrieving funds."""
        funds_response = self.client.funds()
        self.assertEqual(funds_response.get("status"), "success")


if __name__ == "__main__":
    unittest.main()

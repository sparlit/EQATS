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


import unittest
from datetime import datetime, timedelta
from pathlib import Path

from context import NSE


class TestNseApiH1(unittest.TestCase):
    """Tests NSE class with http1 using requests library"""

    @classmethod
    def setUpClass(cls):
        DIR = Path(__file__).parent
        cls.nse = NSE(DIR, server=False)
        print("\nRunning tests using requests library.\n")

    @classmethod
    def tearDownClass(cls):
        cls.nse.exit()

    def test_status(self):
        response = self.nse.status()

        assert isinstance(response, list)
        assert isinstance(response[0], dict)

    def test_holidays(self):
        response = self.nse.holidays()

        assert isinstance(response, dict)
        assert "CM" in response

    def test_blockdeals(self):
        response = self.nse.blockDeals()

        assert isinstance(response, dict)
        assert "timestamp" in response

    def test_bulkdeals(self):
        today = datetime.now()

        response = self.nse.bulkdeals(option_type="bulk_deals", fromdate=today - timedelta(3), todate=today)

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert "BD_DT_DATE" in response[0]

    def test_equityMetaInfo(self):
        response = self.nse.equityMetaInfo("reliance")

        assert isinstance(response, dict)
        assert "symbol" in response

    def test_quote(self):
        response = self.nse.quote(symbol="reliance", series="EQ")

        assert isinstance(response, dict)
        assert "priceInfo" in response

    def test_live_volume_gainers(self):
        response = self.nse.liveVolumeGainers()

        assert isinstance(response, dict)
        assert isinstance(response["data"], list)

        if response["data"]:
            dct = response["data"][0]
            assert isinstance(dct, dict)
            assert "symbol" in dct
            assert "volume" in dct

    def test_gainers(self):
        test_data = {"data": [{"pChange": i} for i in range(10)]}
        response = self.nse.gainers(test_data)

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert response[0]["pChange"] == 9
        assert response[-1]["pChange"] == 1
        assert len(response) == 9

        response = self.nse.gainers(test_data, count=3)

        assert len(response) == 3
        assert response[0]["pChange"] == 9
        assert response[-1]["pChange"] == 7

    def test_losers(self):
        test_data = {"data": [{"pChange": i} for i in range(-1, -10, -1)]}
        response = self.nse.losers(test_data)

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert response[0]["pChange"] == -9
        assert response[-1]["pChange"] == -1
        assert len(response) == 9

        response = self.nse.losers(test_data, count=3)

        assert len(response) == 3
        assert response[0]["pChange"] == -9
        assert response[-1]["pChange"] == -7

    def test_listEquityStocksByIndex(self):
        response = self.nse.listEquityStocksByIndex(index="NIFTY 50")

        assert isinstance(response, dict)
        assert "data" in response
        assert "pChange" in response["data"][0]

    def test_listIndices(self):
        response = self.nse.listIndices()

        assert isinstance(response, dict)
        assert "data" in response
        assert isinstance(response["data"], list)

    def test_listSme(self):
        response = self.nse.listSme()

        assert isinstance(response, dict)
        assert "data" in response
        assert "pChange" in response["data"][0]

    def test_listEtf(self):
        response = self.nse.listEtf()

        assert isinstance(response, dict)
        assert "data" in response
        assert "symbol" in response["data"][0]

    def test_listSgb(self):
        response = self.nse.listSgb()

        assert isinstance(response, dict)
        assert "data" in response
        assert "symbol" in response["data"][0]

    def test_listCurrentIPO(self):
        response = self.nse.listCurrentIPO()

        assert isinstance(response, list)

        if len(response):
            assert isinstance(response[0], dict)
            assert "symbol" in response[0]

    def test_listUpcomingIPO(self):
        response = self.nse.listUpcomingIPO()

        assert isinstance(response, list)

        if len(response):
            assert isinstance(response[0], dict)
            assert "symbol" in response[0]

    def test_listPastIPO(self):
        response = self.nse.listPastIPO()

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert "symbol" in response[0]

    def test_circulars(self):
        response = self.nse.circulars()

        assert isinstance(response, dict)
        assert "data" in response
        assert isinstance(response["data"], list)

        response = self.nse.circulars(subject="holidays")
        assert isinstance(response, dict)

    def test_actions(self):
        response = self.nse.actions()

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert "symbol" in response[0]

    def test_announcements(self):
        response = self.nse.announcements()

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert "symbol" in response[0]

    def test_boardMeetings(self):
        response = self.nse.boardMeetings()

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert "bm_symbol" in response[0]

    def test_getFuturesExpiry(self):
        response = self.nse.getFuturesExpiry()

        assert isinstance(response, list)
        assert isinstance(response[0], str)

    def test_fnoLots(self):
        response = self.nse.fnoLots()

        assert isinstance(response, dict)

    def test_optionChain(self):
        response = self.nse.optionChain(symbol="nifty")

        assert isinstance(response, dict)
        assert "records" in response

    def test_fetch_historical_vix_data(self):
        response = self.nse.fetch_historical_vix_data()

        assert isinstance(response, list)
        assert "VIX_PERC_CHG" in response[0]

    def test_fetch_historical_fno_data(self):
        response = self.nse.fetch_historical_fno_data(instrument="FUTIDX", symbol="NIFTY")

        assert isinstance(response, list)
        assert "FH_TIMESTAMP" in response[0]

    def test_fetch_historical_index_data(self):
        response = self.nse.fetch_historical_index_data(index="NIFTY 50")

        assert isinstance(response, list)
        assert isinstance(response[0], dict)
        assert "EOD_TIMESTAMP" in response[0]

    def test_fetch_fno_underlying(self):
        response = self.nse.fetch_fno_underlying()

        assert isinstance(response, dict)
        assert "IndexList" in response

    def test_getDetailedScripData(self):
        response = self.nse.getDetailedScripData(symbol="ETERNAL", series="EQ")

        assert isinstance(response, dict)
        assert "equityResponse" in response
        assert response["equityResponse"][0]["metaData"]["symbol"] == "ETERNAL"


if __name__ == "__main__":
    unittest.main()

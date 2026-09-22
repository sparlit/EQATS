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

import pandas as pd
from cryptoalgotrading import aux
from cryptoalgotrading.var import data_dir


class TestAux(unittest.TestCase):
    def test_trailing_stop_loss(self):
        assert not aux.trailing_stop_loss(100, 110, 11)
        assert not aux.trailing_stop_loss(100, 110, 10)
        assert aux.trailing_stop_loss(100, 110, 9)

    def test_stop_loss(self):
        assert not aux.stop_loss(100, 110, 11)
        assert not aux.stop_loss(100, 110, 10)
        assert aux.stop_loss(100, 110, 9)

    def test_check_market_name(self):
        assert aux.check_market_name("ETH") == "BTC-ETH"
        assert aux.check_market_name("go") == "BTC-GO"
        assert aux.check_market_name("gobtc", exchange="binance") == "GOBTC"

    def test_get_time_right(self):
        assert aux.get_time_right("1-2-2018") == "2018-2-1T00:00:00Z"
        assert aux.get_time_right("1-2-2018 23:23") == "2018-2-1T23:23:00Z"
        assert aux.get_time_right("1/2/2018 22:22") == "2018-2-1T22:22:00Z"
        assert aux.get_time_right("1/2") == "2021-2-1T00:00:00Z"
        assert aux.get_time_right("1-2") == "2021-2-1T00:00:00Z"

    def test_num_processors(self):
        assert aux.num_processors("low") == 1
        assert aux.num_processors(2) == 2

    def test_beep(self):
        assert aux.beep() == 0

    def test_log(self):
        assert aux.log("Running unit tests...") == 0

    # def test_connect_db(self):
    #    self.assertEqual()

    def test_get_markets_list(self):
        assert isinstance(aux.get_markets_list(), list)
        assert isinstance(aux.get_markets_list(base="BTC"), list)
        assert isinstance(aux.get_markets_list(exchange="binance", base="BTC"), list)
        assert isinstance(aux.get_markets_list(exchange="cryptopia"), bool)

    def test_get_markets_on_files(self):
        self.assertCountEqual(aux.get_markets_on_files("10m"), ["BTC-SRN", "BTC-XRP"])

    # def test_get_historical_data(self):
    #    self.assertEqual(4,4)

    # def test_get_last_data(self):
    #    self.assertEqual(4,4)

    def test_detect_init(self):
        assert isinstance(aux.detect_init(aux.get_data_from_file("BTC-SRN", interval="10m")), pd.core.frame.DataFrame)

    def test_plot_data(self):
        assert aux.plot_data(aux.get_data_from_file("BTC-SRN", interval="10m"), to_file=True)
        assert aux.plot_data(
            aux.get_data_from_file("BTC-SRN", interval="10m"),
            entry_points=[10, 30, 50],
            exit_points=[20, 40, 60],
            to_file=True,
            show_smas=True,
            show_emas=True,
            show_bbands=True,
        )

    # def test_get_histdata_to_file(self):
    #    self.assertEqual(,4)

    def test_get_data_from_file(self):
        assert isinstance(aux.get_data_from_file("BTC-SRN", interval="10m"), pd.core.frame.DataFrame)
        assert isinstance(aux.get_data_from_file("BTC-DCT", interval="10s", filetype="hdf"), pd.core.frame.DataFrame)

    def test_time_to_index(self):
        assert aux.time_to_index(aux.get_data_from_file("BTC-SRN", interval="10m"), ["01-03-2018", "04-03-2018"]) == (
            33568,
            33998,
        )
        assert aux.time_to_index(
            aux.get_data_from_file("BTC-SRN", interval="10m"), ["01-03-2018 00:00", "04-03-2018"]
        ) == (33568, 33998)

    # def test_timeit(self):
    #    self.assertEqual(timeit(),)

    def test_file_lines(self):
        assert aux.file_lines(data_dir + "/hist-10s/BTC-DGB.csv") == 5088

    def test_manage_files(self):
        assert aux.manage_files(["BTC-XRP"], "10m") == ["BTC-XRP"]
        assert aux.manage_files(["BTC-XXX"], "10m") == []

    def test_binance2btrx(self):
        assert aux.binance2btrx(
            {
                "symbol": "TIETABTC",
                "askPrice": "12",
                "bidPrice": "11",
                "count": "333",
                "highPrice": "15",
                "lastPrice": "11.5",
                "lowPrice": "10",
                "quoteVolume": "1000",
                "volume": "100",
            }
        ) == {
            "MarketName": "TIETABTC",
            "Ask": 12.0,
            "BaseVolume": 1000.0,
            "Bid": 11.0,
            "Count": 333.0,
            "High": 15.0,
            "Last": 11.5,
            "Low": 10.0,
            "Volume": 100.0,
        }

    def test_run_command(self):
        assert aux.run_command("ls") == 0

    def test_desktop_notification(self):
        assert aux.desktop_notification({"type": "buy", "title": "test", "message": "test message"}) == 0
        assert aux.desktop_notification({"type": "P&L", "title": "test", "message": "test message"}) == 0


if __name__ == "__main__":
    unittest.main()

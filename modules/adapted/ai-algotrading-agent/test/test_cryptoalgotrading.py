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

import cryptoalgotrading.exit as exit_
from cryptoalgotrading import entry
from cryptoalgotrading.aux import get_data_from_file
from cryptoalgotrading.cryptoalgotrading import backtest, backtest_market, is_time_to_buy, is_time_to_exit, tick_by_tick


class TestCryptoalgotrading(unittest.TestCase):
    def test_is_time_to_buy(self):

        q = get_data_from_file("BTC-XRP", interval="10m")

        assert not is_time_to_buy(q[4416 : 4416 + 50], [entry.cross_smas], [4, 8, 12], [4, 8, 12])
        assert is_time_to_buy(q[4417 : 4417 + 50], [entry.cross_smas], [4, 8, 12], [4, 8, 12])
        assert not is_time_to_buy(q[4418 : 4418 + 50], [entry.cross_smas], [4, 8, 12], [4, 8, 12])

    def test_is_time_to_exit(self):

        q = get_data_from_file("BTC-XRP", interval="10m")

        assert not is_time_to_exit(q[4778 : 4778 + 50], [exit_.cross_smas], [4, 8, 12], [4, 8, 12])
        assert is_time_to_exit(q[4779 : 4779 + 50], [exit_.cross_smas], [4, 8, 12], [4, 8, 12])
        assert not is_time_to_exit(q[4780 : 4780 + 50], [exit_.cross_smas], [4, 8, 12], [4, 8, 12])

    def test_tick_by_tick(self):
        assert (
            round(
                tick_by_tick(
                    "BTC-DGB",
                    entry.cross_smas,
                    exit_.cross_smas,
                    interval="10s",
                    from_file=True,
                    plot=False,
                    refresh_interval=0.01,
                ),
                2,
            )
            == -18.82
        )

    def test_backtest(self):
        assert (
            round(
                backtest(
                    ["BTC-XRP", "BTC-SRN"],
                    entry.cross_smas,
                    exit_.cross_smas,
                    interval="10m",
                    from_file=True,
                    smas=[5, 10, 18],
                ),
                2,
            )
            == -217.49
        )

        assert (
            round(
                backtest(
                    "BTC-XRP", entry.cross_smas, exit_.cross_smas, interval="10m", from_file=True, smas=[5, 10, 18]
                ),
                2,
            )
            == -43.4
        )

        assert (
            backtest("BTC-XXX", entry.cross_smas, exit_.cross_smas, interval="10m", from_file=False, smas=[5, 10, 18])
            == 0
        )

    def test_backtest_market(self):
        assert (
            round(
                backtest_market(
                    [entry.cross_smas],
                    [exit_.cross_smas],
                    "10m",
                    [0, 0],
                    [5, 10, 18],
                    [5, 10, 18],
                    True,
                    False,
                    False,
                    "bittrex",
                    0,
                    1,
                    "BTC-XRP",
                ),
                2,
            )
            == -43.4
        )


if __name__ == "__main__":
    unittest.main()

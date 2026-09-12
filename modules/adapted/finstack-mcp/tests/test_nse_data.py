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


import pandas as pd
from finstack.data.nse import get_market_movers
from finstack.data.nse_advanced import _format_calendar_value


class _Columns:
    def get_level_values(self, _index: int):
        return ["RELIANCE.NS", "TCS.NS"]


class _FakeDownload:
    columns = _Columns()

    def __getitem__(self, key: str):
        datasets = {
            "RELIANCE.NS": pd.DataFrame({"Close": [100.0, 103.0], "Volume": [1000, 1200]}),
            "TCS.NS": pd.DataFrame({"Close": [100.0, 98.0], "Volume": [1500, 1300]}),
        }
        return datasets[key]


def test_market_movers_losers_only_include_negative_changes(monkeypatch):
    monkeypatch.setattr("finstack.data.nse.yf.download", lambda *args, **kwargs: _FakeDownload())

    result = get_market_movers("losers")

    assert result["stocks"]
    assert all(item["change_pct"] < 0 for item in result["stocks"])


def test_format_calendar_value_normalizes_dates():
    result = _format_calendar_value([pd.Timestamp("2026-04-24")])

    assert result in (["2026-04-24 00:00:00"], ["2026-04-24"])

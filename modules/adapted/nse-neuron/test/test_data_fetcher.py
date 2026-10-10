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


"""Tests for utils/data_fetcher.py - the raw CSV cache layer."""
import os

import pandas as pd

from utils import data_fetcher as fetcher


def test_get_cache_path_uses_symbol_and_date():
    path = fetcher._get_cache_path("SUZLON", "03-08-2026")
    assert os.path.basename(path) == "SUZLON_03-08-2026.csv"
    assert os.path.dirname(path).endswith(os.path.join("data", "raw"))


def test_load_or_fetch_reads_from_cache_without_calling_the_api(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "RAW_DATA_DIR", str(tmp_path))
    cached = pd.DataFrame({"Date": ["01-Jan-2024"], "ClosePrice": [100.0]})
    cached.to_csv(tmp_path / "SUZLON_01-01-2024.csv", index=False)

    def explode(**kwargs):
        raise AssertionError("the NSE API must not be called on a cache hit")

    monkeypatch.setattr(
        fetcher.capital_market, "price_volume_and_deliverable_position_data", explode
    )

    out = fetcher._load_or_fetch("SUZLON", "01-01-1996", "01-01-2024")
    assert out["ClosePrice"].iloc[0] == 100.0


def test_load_or_fetch_calls_api_and_writes_cache_on_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "RAW_DATA_DIR", str(tmp_path))
    fetched = pd.DataFrame({"Date": ["02-Jan-2024"], "ClosePrice": [101.0]})
    calls = []

    def fake_api(**kwargs):
        calls.append(kwargs)
        return fetched

    monkeypatch.setattr(
        fetcher.capital_market, "price_volume_and_deliverable_position_data", fake_api
    )

    out = fetcher._load_or_fetch("SBIN", "01-01-1996", "02-01-2024")
    assert out["ClosePrice"].iloc[0] == 101.0
    assert calls[0]["symbol"] == "SBIN"
    assert calls[0]["from_date"] == "01-01-1996"
    assert calls[0]["to_date"] == "02-01-2024"
    assert (tmp_path / "SBIN_02-01-2024.csv").exists()


def test_load_or_fetch_creates_the_cache_directory(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "raw"
    monkeypatch.setattr(fetcher, "RAW_DATA_DIR", str(target))
    monkeypatch.setattr(
        fetcher.capital_market,
        "price_volume_and_deliverable_position_data",
        lambda **kw: pd.DataFrame({"Date": [], "ClosePrice": []}),
    )
    fetcher._load_or_fetch("NTPC", "01-01-1996", "01-01-2024")
    assert target.is_dir()


def test_cache_key_is_per_day(tmp_path, monkeypatch):
    """A new trading day must miss the previous day's cache file."""
    monkeypatch.setattr(fetcher, "RAW_DATA_DIR", str(tmp_path))
    pd.DataFrame({"Date": ["01-Jan-2024"]}).to_csv(tmp_path / "SUZLON_01-01-2024.csv", index=False)
    calls = []
    monkeypatch.setattr(
        fetcher.capital_market,
        "price_volume_and_deliverable_position_data",
        lambda **kw: calls.append(kw) or pd.DataFrame({"Date": []}),
    )
    fetcher._load_or_fetch("SUZLON", "01-01-1996", "02-01-2024")
    assert len(calls) == 1

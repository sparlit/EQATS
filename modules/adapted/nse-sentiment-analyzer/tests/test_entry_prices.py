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


"""Tests for entry price persistence and portfolio news matching."""

import pytest


class TestEntryPrices:
    """Tests for save_entry_price() and load_entry_prices()."""

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):

        from persistence import load_entry_prices, save_entry_price

        # Redirect data dir to tmp_path
        monkeypatch.setattr("persistence.DATA_DIR", tmp_path)
        monkeypatch.setattr("persistence.ENTRY_PRICES_FILE", tmp_path / "entry_prices.json")

        save_entry_price("RELIANCE", 2850.50, qty=10)
        prices = load_entry_prices()

        assert prices["RELIANCE"]["price"] == 2850.50
        assert prices["RELIANCE"]["qty"] == 10

    def test_load_empty_returns_empty_dict(self, tmp_path, monkeypatch):

        from persistence import load_entry_prices

        monkeypatch.setattr("persistence.DATA_DIR", tmp_path)
        monkeypatch.setattr("persistence.ENTRY_PRICES_FILE", tmp_path / "entry_prices.json")

        prices = load_entry_prices()

        assert prices == {}

    def test_update_existing_entry(self, tmp_path, monkeypatch):

        from persistence import load_entry_prices, save_entry_price

        monkeypatch.setattr("persistence.DATA_DIR", tmp_path)
        monkeypatch.setattr("persistence.ENTRY_PRICES_FILE", tmp_path / "entry_prices.json")

        save_entry_price("RELIANCE", 2850.50, qty=10)
        save_entry_price("RELIANCE", 2900.00, qty=15)
        prices = load_entry_prices()

        assert prices["RELIANCE"]["price"] == 2900.00
        assert prices["RELIANCE"]["qty"] == 15

    def test_migrates_old_flat_format(self, tmp_path, monkeypatch):

        from persistence import load_entry_prices

        monkeypatch.setattr("persistence.ENTRY_PRICES_FILE", tmp_path / "entry_prices.json")
        # Write old flat format
        import json

        (tmp_path / "entry_prices.json").write_text(json.dumps({"SBIN": 800.50}), encoding="utf-8")

        prices = load_entry_prices()

        assert prices["SBIN"]["price"] == 800.50
        assert prices["SBIN"]["qty"] == 1

    def test_calc_portfolio_pnl(self):
        from persistence import calc_portfolio_pnl

        result = calc_portfolio_pnl(2850.50, 3277.00, 12)

        assert result["pnl_abs"] == pytest.approx(5118.0, rel=0.1)
        assert "pnl_pct" in result

    def test_calc_portfolio_pnl_negative(self):
        from persistence import calc_portfolio_pnl

        result = calc_portfolio_pnl(512.0, 454.0, 14)

        assert result["pnl_abs"] < 0
        assert result["pnl_pct"] < 0

    def test_calc_portfolio_pnl_none_price(self):
        from persistence import calc_portfolio_pnl

        result = calc_portfolio_pnl(100.0, None, 10)

        assert result["pnl_pct"] == 0.0
        assert result["pnl_abs"] == 0.0
